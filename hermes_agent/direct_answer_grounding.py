"""Fail-closed, proof-carrying DIRECT answers, without research or external data.

The model proposes source excerpts and arithmetic, never final factual prose.
Only exact user excerpts and locally checked calculations reach the renderer.
An arithmetic result is labelled literal arithmetic, not an inferred attribute
or entity count. This deliberately trades free-form answers for verifiability.
"""
import ast
import json
import logging
import re
from fractions import Fraction

from hermes_agent.direct_provider_recovery import analyze_direct, DirectProviderFailure
from hermes_agent.direct_contract import ContractViolation as GroundingViolation, decode_proof, has_missing_input_evidence
from hermes_agent.direct_calculation import render_plan

logger = logging.getLogger(__name__)
MAX_REPAIR_ATTEMPTS = 1
MAX_CONTENT_CHARS = 32000
MAX_ITEMS = 32
MAX_NUMBER_BITS = 256
NUMBER = re.compile(r'(?<![\w.])[+-]?\d+(?:[.,]\d+)?(?!\w|[.,]\d)')
HALF = re.compile(r'\b(?:half|setengah(?:nya)?)\b', re.I)
PAIR = re.compile(r'(?<!\w)(\d+(?:[.,]\d+)?)\s+(?:pairs?|couples?|pasang)\b', re.I)
EXAMPLE_REQUEST = re.compile(
    r'\b(?:give|show|provide|buat|buatkan|beri|berikan|tunjukkan)\b.{0,100}'
    r'\b(?:examples?|contoh)\b|\b(?:hypothetical example|contoh hipotetis)\b', re.I | re.S)
EXAMPLE_DENIAL = re.compile(
    r"\b(?:do not|don't|never|jangan|tanpa|without|no)\b.{0,100}"
    r'\b(?:examples?|contoh|hypothetical|hipotetis)\b', re.I | re.S)

UNKNOWN = (
    'UNKNOWN: hasil tidak dapat ditentukan dari informasi yang diberikan. '
    'Input yang belum diberikan perlu diklarifikasi; tidak ada nilai asumsi yang dipakai.'
)

DIRECT_GROUNDING_PROMPT = """
DIRECT: return one compact JSON object, no prose, no Markdown.
For arithmetic, units, rates or time use the code-executed plan:
{"v":2,"q":["exact quantity excerpt from user input"],"s":[["+",0,1]],
 "o":[[2,"target unit"]],"u":[]}
q contains only source-exact quantity excerpts, e.g. "3 liter", "2 kg",
"250 mililiter per detik", "3 liter setiap 5 menit", "08.00 pagi".
All q entries get zero-based indexes first; each step appends one new value.
Steps use ["+",i,j], ["-",i,j], ["*",i,j], ["/",i,j], or ["half",i].
References must point to earlier values. Do not put numeric values in steps.
Code parses numbers/units, converts compatible metric units and checks dimensions.
Code computes exact results; do not calculate, round or repeat results yourself.
o selects value indexes and output units (e.g. kg, L, menit, or clock).
To add a duration to a starting clock use ["+",clock_index,duration_index].
half requires the user to say half/setengah. Preserve fractional entity counts.
u names genuinely missing input parameters only. Unsupported units, formatting
failures or inability to build a plan are not proof that user data is missing.
Never invent quantities, units, rates or entity attributes; a capacity does not
prove an actual entity count. Do not use prior ASSISTANT output or persistent
memory as new supplied facts. No external search or research.

Existing excerpt proofs are also accepted, with exactly four list fields:
{"facts":["exact user excerpt"],"calculations":[{"expression":"7*6","result":"42"}],
 "unknowns":["missing input name"],"examples":[]}
In this legacy form numeric literals must be supplied by the user; half(x) and
pair(n) require explicit half/pairs. Never insert conversion constants.
Do not label arithmetic as an unproved entity attribute. Hypothetical examples
are allowed only when the current user explicitly requests them.
"""


class DirectOutputFailure(DirectProviderFailure):
    """A contract/validation failure is not evidence of missing user data."""
    def __init__(self, reason, attempts, requested_model=None, request_id=None):
        super().__init__('invalid_output', attempts, requested_model, request_id)
        self.failure_subtype = reason
        self.failure_class = 'DIRECT_OUTPUT_INVALID'

    def public_error(self):
        error = super().public_error()
        error['type'] = 'direct_output_error'
        error['message'] = 'Jawaban gagal diverifikasi. Coba lagi atau pilih model lain.'
        return error


def supplied_input(goal, context='', attachment_context=''):
    """Keep current input/attachments and prior USER turns, not model assertions."""
    roles = re.findall(
        r'(?:^|\n\n)(USER|ASSISTANT|SYSTEM|DEVELOPER|TOOL):\s*(.*?)'
        r'(?=\n\n(?:USER|ASSISTANT|SYSTEM|DEVELOPER|TOOL):|\Z)',
        context or '', re.S,
    )
    return '\n\n'.join([goal] + [body for role, body in roles if role == 'USER']
                        + ([attachment_context] if attachment_context else []))


def _number(text):
    try:
        if len(str(text)) > 120:
            raise GroundingViolation('number_too_large')
        value = Fraction(str(text).replace(',', '.'))
    except (ValueError, ZeroDivisionError, TypeError) as exc:
        raise GroundingViolation('invalid_number') from exc
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_NUMBER_BITS:
        raise GroundingViolation('number_too_large')
    return value


def _format(value):
    if value.denominator == 1:
        return str(value.numerator)
    remainder = value.denominator
    for divisor in (2, 5):
        while remainder % divisor == 0:
            remainder //= divisor
    if remainder != 1:
        return f'{value.numerator}/{value.denominator}'
    digits = []
    integral, remainder = divmod(abs(value.numerator), value.denominator)
    while remainder:
        digit, remainder = divmod(remainder * 10, value.denominator)
        digits.append(str(digit))
    return ('-' if value < 0 else '') + str(integral) + '.' + ''.join(digits)


def _evaluate(expression, source, previous, hypothetical=False):
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 2000:
        raise GroundingViolation('invalid_expression')
    try:
        tree = ast.parse(expression, mode='eval')
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise GroundingViolation('invalid_expression') from exc
    if sum(1 for _ in ast.walk(tree)) > 128:
        raise GroundingViolation('expression_too_large')
    supplied = {_number(m.group()) for m in NUMBER.finditer(source)}
    # A sign belongs to a unary arithmetic operation as well as to a supplied
    # literal. Its magnitude is the same operand, not an invented parameter.
    supplied |= {abs(value) for value in supplied}
    paired = {_number(m.group(1)) for m in PAIR.finditer(source)}

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = _number(ast.get_source_segment(expression, node))
            if not hypothetical and value not in supplied:
                raise GroundingViolation('unsupplied_operand')
            return value
        if isinstance(node, ast.Name) and node.id in previous:
            return previous[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            if isinstance(node.operand, ast.Constant) and type(node.operand.value) in (int, float):
                signed = _number(re.sub(r'\s+', '', ast.get_source_segment(expression, node)))
                if hypothetical or signed in supplied:
                    return signed
            value = visit(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left = visit(node.left)
            # Literal division by two is the same source-backed operation as
            # half(x); it does not authorize two in other expressions.
            half_divisor = (
                isinstance(node.op, ast.Div)
                and isinstance(node.right, ast.Constant)
                and type(node.right.value) in (int, float)
                and _number(ast.get_source_segment(expression, node.right)) == 2
                and HALF.search(source)
            )
            right = Fraction(2) if half_divisor else visit(node.right)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                value = left * right
            else:
                if right == 0:
                    raise GroundingViolation('division_by_zero')
                value = left / right
            return _number(value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and len(node.args) == 1 and not node.keywords:
            value = visit(node.args[0])
            if node.func.id == 'half' and HALF.search(source):
                return value / 2
            if node.func.id == 'pair' and value in paired:
                return value * 2
        raise GroundingViolation('unsupported_expression')

    value = _number(visit(tree.body))

    def display(node):
        # Only checked AST nodes reach this formatter. Show ordinary arithmetic
        # and resolved intermediate values, never raw comments or internal refs.
        if isinstance(node, ast.Constant):
            return _format(_number(ast.get_source_segment(expression, node)))
        if isinstance(node, ast.Name):
            text = _format(previous[node.id])
            return '(' + text + ')' if '/' in text else text
        if isinstance(node, ast.UnaryOp):
            return '(' + ('-' if isinstance(node.op, ast.USub) else '+') + display(node.operand) + ')'
        if isinstance(node, ast.BinOp):
            operator = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/'}[type(node.op)]
            return '(' + display(node.left) + ' ' + operator + ' ' + display(node.right) + ')'
        operator = '/' if node.func.id == 'half' else '*'
        return '(' + display(node.args[0]) + ' ' + operator + ' 2)'

    text = display(tree.body)
    if text.startswith('(') and text.endswith(')'):
        text = text[1:-1]
    return value, text


def validate_and_render(content, source, goal):
    """No raw model prose is released, even if its JSON claims to be grounded."""
    record = decode_proof(content)
    if isinstance(record, dict) and 'v' in record:
        return render_plan(record, source)
    fields = {'facts', 'calculations', 'unknowns', 'examples'}
    if not isinstance(record, dict) or set(record) != fields:
        raise GroundingViolation('invalid_fields')
    if any(not isinstance(record[key], list) or len(record[key]) > MAX_ITEMS for key in fields):
        raise GroundingViolation('invalid_list')

    lines = []
    for quote in record['facts']:
        if not isinstance(quote, str) or not quote.strip():
            raise GroundingViolation('unsupported_fact')
        if quote not in source:
            # Restore only an unambiguous case-only match to the exact input.
            # Never release the model's spelling or normalize other wording.
            matches = {match.group() for match in re.finditer(re.escape(quote), source, re.I)}
            if len(matches) != 1:
                raise GroundingViolation('unsupported_fact')
            quote = matches.pop()
        # Quoted input stays visibly attributed, not interpreted as a new fact.
        lines.append('Input yang diberikan: ' + json.dumps(quote, ensure_ascii=False))

    def calculations(items, hypothetical=False):
        previous = {}
        for index, item in enumerate(items):
            if not isinstance(item, dict) or set(item) != {'expression', 'result'} or not isinstance(item['result'], str):
                raise GroundingViolation('invalid_calculation')
            value, expression = _evaluate(item['expression'], source, previous, hypothetical)
            if value != _number(item['result']):
                raise GroundingViolation('incorrect_arithmetic')
            previous[f'r{index}'] = value
            prefix = 'Contoh hipotetis (bukan fakta): ' if hypothetical else 'Hasil hitung literal: '
            lines.append(prefix + expression + ' = ' + _format(value))
            if value.denominator != 1:
                lines.append(
                    'Hasil pecahan dipertahankan. Sebagai jumlah entitas diskret, '
                    'hasil ini tidak konsisten dan perlu klarifikasi; tidak dibulatkan.'
                )

    calculations(record['calculations'])
    if record['examples']:
        if EXAMPLE_DENIAL.search(goal) or not EXAMPLE_REQUEST.search(goal):
            raise GroundingViolation('unrequested_hypothetical')
        calculations(record['examples'], hypothetical=True)
    if record['unknowns'] and not record['calculations'] and not has_missing_input_evidence(source):
        raise GroundingViolation('unsubstantiated_missing_input')
    for name in record['unknowns']:
        if not isinstance(name, str) or not name.strip() or len(name) > 200 or '\n' in name:
            raise GroundingViolation('invalid_missing_input')
        if NUMBER.search(name) or not re.fullmatch(r'[\w\s()/\-]+', name):
            raise GroundingViolation('missing_input_has_value')
        # Names are questions, never quantities or unverified assertions.
        lines.append('UNKNOWN — input yang diperlukan: ' + name + '. Tidak dapat ditentukan dari informasi yang diberikan.')
    if not lines:
        raise GroundingViolation('empty_answer')
    return '\n\n'.join(lines)


def enforce_direct_answer(llm, result, *, source, goal, request_id=None):
    """Check output, repair once, then expose technical failure separately."""
    candidate = result
    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        content = candidate['content']
        try:
            if candidate.get('finish_reason') == 'length':
                raise GroundingViolation('truncated_output')
            answer = validate_and_render(content, source, goal)
        except GroundingViolation as exc:
            reason = str(exc)
            logger.warning('[direct-grounding] request_id=%s attempt=%d decision=REJECT reason=%s',
                           request_id, attempt, reason)
        else:
            logger.info('[direct-grounding] request_id=%s attempt=%d decision=ACCEPT', request_id, attempt)
            return answer
        if attempt == MAX_REPAIR_ATTEMPTS:
            break
        try:
            candidate = analyze_direct(
                llm, request_id=request_id,
                system_prompt=('Repair the DIRECT output contract using supplied user input only. '
                               'Remove unsupported assumptions. Return a compact plan for code to calculate. '
                               'Do not search or invoke research. ' + DIRECT_GROUNDING_PROMPT),
                user_query=json.dumps({'user_question': goal, 'supplied_input': source,
                                       'violation': reason,
                                       'untrusted_draft': content[:MAX_CONTENT_CHARS] if isinstance(content, str) else ''},
                                      ensure_ascii=False),
                temperature=0.0,
            )
        except DirectProviderFailure as exc:
            logger.warning('[direct-grounding] request_id=%s decision=ERROR repair_provider_failure=%s',
                           request_id, exc.failure_subtype)
            raise
    logger.warning('[direct-grounding] request_id=%s decision=ERROR repair_exhausted=true reason=%s',
                   request_id, reason)
    get_model = getattr(llm, 'get_requested_model', None)
    model = get_model() if callable(get_model) else None
    raise DirectOutputFailure(reason, MAX_REPAIR_ATTEMPTS + 1, model, request_id)
