"""Source-anchored quantity plans, exact arithmetic, units and clock rendering.

The model selects excerpts and operations. Code owns parsing, conversion factors,
arithmetic and output text. Dimensional correctness is not proof that a model's
chosen formula answers the question; results remain labelled calculations.
"""
import re
from dataclasses import dataclass
from fractions import Fraction

from hermes_agent.direct_contract import ContractViolation as Violation, PLAN_FIELDS, has_missing_input_evidence

TOKEN = r'[+-]?\d+(?:[.,]\d+)*'
ID_LANGUAGE = re.compile(r'\b(?:sebuah|berapa|pukul|setiap|detik|menit|tangki|berat|penumpang|setengah)\b', re.I)
EN_LANGUAGE = re.compile(r'\b(?:convert|calculate|divide|multiply|add|subtract|half|every|seconds?|minutes?|hours?|weight)\b', re.I)
HALF = re.compile(r'\b(?:half|setengah(?:nya)?)\b', re.I)
MAX_ITEMS = 32


def number(text, locale):
    if not isinstance(text, str) or len(text) > 120 or not re.fullmatch(TOKEN, text):
        raise Violation('invalid_number')
    if locale is None and re.search(r'[.,]\d{3}(?:[.,]|$)', text):
        raise Violation('ambiguous_number_locale')
    decimal, group = (',', '.') if locale == 'id' else ('.', ',')
    sign = text[0] if text[0] in '+-' else ''
    unsigned = text[len(sign):]
    pieces = unsigned.split(decimal)
    if len(pieces) > 2:
        raise Violation('invalid_number')
    integral = pieces[0]
    if group in integral:
        if not re.fullmatch(r'\d{1,3}(?:' + re.escape(group) + r'\d{3})+', integral):
            raise Violation('invalid_number_grouping')
        integral = integral.replace(group, '')
    if len(pieces) == 2 and (not pieces[1].isdigit()):
        raise Violation('invalid_number')
    canonical = sign + integral + ('.' + pieces[1] if len(pieces) == 2 else '')
    try:
        return checked(Fraction(canonical))
    except (ValueError, ZeroDivisionError) as exc:
        raise Violation('invalid_number') from exc


def checked(value):
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > 256:
        raise Violation('number_too_large')
    return value


def exact(value):
    if value.denominator == 1:
        return str(value.numerator)
    remainder = value.denominator
    for prime in (2, 5):
        while remainder % prime == 0:
            remainder //= prime
    if remainder != 1:
        return f'{value.numerator}/{value.denominator}'
    integral, remainder = divmod(abs(value.numerator), value.denominator)
    digits = []
    while remainder:
        digit, remainder = divmod(remainder * 10, value.denominator)
        digits.append(str(digit))
    return ('-' if value < 0 else '') + str(integral) + '.' + ''.join(digits)


def dims(name):
    return ((name, 1),) if name else ()


def combine(left, right, sign):
    result = dict(left)
    for key, exponent in right:
        result[key] = result.get(key, 0) + sign * exponent
    if any(abs(n) > 8 for n in result.values()):
        raise Violation('dimension_too_large')
    return tuple(sorted((key, n) for key, n in result.items() if n))


@dataclass(frozen=True)
class Unit:
    factor: Fraction
    dimensions: tuple
    label: str


@dataclass(frozen=True)
class Quantity:
    value: Fraction
    dimensions: tuple


@dataclass(frozen=True)
class Clock:
    seconds: Fraction


UNITS = {}


def register(aliases, factor, dimension, label):
    unit = Unit(Fraction(factor), dims(dimension), label)
    for alias in aliases.split('|'):
        UNITS[alias] = unit


register('l|liter|litre|liters|litres', 1, 'volume', 'L')
register('ml|mililiter|milliliter|millilitre|milliliters|millilitres', '1/1000', 'volume', 'mL')
register('kl|kiloliter|kilolitre', 1000, 'volume', 'kL')
register('kg|kilogram|kilograms', 1, 'mass', 'kg')
register('g|gram|grams', '1/1000', 'mass', 'g')
register('mg|miligram|milligram', '1/1000000', 'mass', 'mg')
register('t|ton|tonne|tonnes|metric ton', 1000, 'mass', 'ton')
register('s|detik|second|seconds', 1, 'time', 'detik')
register('min|menit|minute|minutes', 60, 'time', 'menit')
register('h|jam|hour|hours', 3600, 'time', 'jam')
register('day|days|hari', 86400, 'time', 'hari')
register('m|meter|meters|metre|metres', 1, 'length', 'm')
register('cm|sentimeter|centimeter', '1/100', 'length', 'cm')
register('mm|milimeter|millimeter', '1/1000', 'length', 'mm')
register('km|kilometer|kilometre', 1000, 'length', 'km')
register('%|persen|percent', '1/100', '', '%')
register('orang|penumpang|anggota|people|persons|person|passengers|members|workers', 1, 'count:person', 'orang')
register('gerbong|carriage|carriages', 1, 'count:carriage', 'gerbong')
register('roda|wheel|wheels', 1, 'count:wheel', 'roda')
register('box|boxes|kotak|container|containers', 1, 'count:box', 'kotak')
register('item|items|unit|units|buah|paket', 1, 'count:item', 'item')
register('pasang|pair|pairs|couples', 2, 'count:person', 'orang')
register('', 1, '', '')


def unit(text):
    if not isinstance(text, str) or len(text) > 60:
        raise Violation('unsupported_unit')
    text = text.strip().casefold()
    if text in UNITS:
        return UNITS[text]
    parts = text.split('/')
    if len(parts) == 2 and all(p.strip() in UNITS for p in parts):
        left, right = (UNITS[p.strip()] for p in parts)
        return Unit(left.factor / right.factor,
                    combine(left.dimensions, right.dimensions, -1),
                    left.label + '/' + right.label)
    raise Violation('unsupported_unit')


def source_excerpt(quote, source):
    if not isinstance(quote, str) or not quote.strip() or len(quote) > 500:
        raise Violation('unsupported_input')
    matches = []
    for match in re.finditer(re.escape(quote), source, re.I):
        # A model cannot extract 5 from the user-provided 95 or 0.5.
        before = source[match.start() - 1:match.start()] if match.start() else ''
        after = source[match.end():match.end() + 1]
        if quote[0].isdigit() and before and (before.isalnum() or before in '.,+-'):
            continue
        if quote[-1].isdigit() and after and (after.isalnum() or
                after in '.,' and source[match.end() + 1:match.end() + 2].isdigit()):
            continue
        matches.append(match.group())
    spellings = set(matches)
    if quote in spellings:
        return quote
    if len(spellings) != 1:
        raise Violation('unsupported_input')
    return spellings.pop()


def parse_input(quote, source, locale):
    quote = source_excerpt(quote, source)
    clock = re.fullmatch(r'(?:pukul\s+)?(\d{1,2})[.:](\d{2})(?::(\d{2}))?\s*(pagi|siang|sore|malam|am|pm)?', quote, re.I)
    if clock and (':' in quote or clock.group(4) or quote.casefold().startswith('pukul')):
        hour, minute, second = (int(clock.group(i) or 0) for i in (1, 2, 3))
        suffix = (clock.group(4) or '').casefold()
        if hour > 23 or minute > 59 or second > 59 or suffix and hour > 12:
            raise Violation('invalid_clock')
        if suffix in {'pm', 'siang', 'sore', 'malam'}:
            hour = hour % 12 + (0 if suffix == 'malam' and hour == 12 else 12)
        elif suffix in {'am', 'pagi'}:
            hour %= 12
        return Clock(Fraction(hour * 3600 + minute * 60 + second))
    rate = re.fullmatch(r'(.+?)\s+(?:per|setiap|every)\s+(?:(' + TOKEN + r')\s+)?(.+)', quote, re.I)
    if rate:
        numerator = parse_input(rate.group(1), source, locale)
        denominator_unit = unit(rate.group(3))
        divisor = number(rate.group(2), locale) if rate.group(2) else Fraction(1)
        if not isinstance(numerator, Quantity) or divisor <= 0:
            raise Violation('invalid_rate')
        return Quantity(checked(numerator.value / (divisor * denominator_unit.factor)),
                        combine(numerator.dimensions, denominator_unit.dimensions, -1))
    match = re.fullmatch(r'(' + TOKEN + r')\s*(.*?)', quote)
    if not match:
        raise Violation('invalid_quantity')
    scale = unit(match.group(2))
    return Quantity(checked(number(match.group(1), locale) * scale.factor), scale.dimensions)


def operation(row, values, source):
    if not isinstance(row, list) or len(row) not in (2, 3):
        raise Violation('invalid_operation')
    name, *refs = row
    if not isinstance(name, str):
        raise Violation('unsupported_operation')
    if any(type(i) is not int or i < 0 or i >= len(values) for i in refs):
        raise Violation('invalid_reference')
    operands = [values[i] for i in refs]
    if name == 'half' and len(operands) == 1 and HALF.search(source) and isinstance(operands[0], Quantity):
        return Quantity(checked(operands[0].value / 2), operands[0].dimensions)
    if name not in {'+', '-', '*', '/'} or len(operands) != 2:
        raise Violation('unsupported_operation')
    left, right = operands
    if isinstance(left, Clock):
        if name in {'+', '-'} and isinstance(right, Quantity) and right.dimensions == dims('time'):
            return Clock(checked(left.seconds + (right.value if name == '+' else -right.value)))
        if name == '-' and isinstance(right, Clock):
            return Quantity(checked(left.seconds - right.seconds), dims('time'))
        raise Violation('dimension_mismatch')
    if not isinstance(left, Quantity) or not isinstance(right, Quantity):
        raise Violation('dimension_mismatch')
    if name in {'+', '-'}:
        if left.dimensions != right.dimensions:
            raise Violation('dimension_mismatch')
        return Quantity(checked(left.value + (right.value if name == '+' else -right.value)), left.dimensions)
    if name == '*':
        return Quantity(checked(left.value * right.value), combine(left.dimensions, right.dimensions, 1))
    if right.value == 0:
        raise Violation('division_by_zero')
    return Quantity(checked(left.value / right.value), combine(left.dimensions, right.dimensions, -1))


def missing_inputs(items):
    lines = []
    for name in items:
        if not isinstance(name, str) or not name.strip() or len(name) > 200 or re.search(r'\d', name) or not re.fullmatch(r'[\w ()/\-]+', name):
            raise Violation('invalid_missing_input')
        lines.append('UNKNOWN — input yang diperlukan: ' + name + '. Tidak dapat ditentukan dari informasi yang diberikan.')
    return lines


def render_clock(seconds):
    if seconds < 0:
        raise Violation('invalid_clock_result')
    whole = seconds.numerator // seconds.denominator
    days, within = divmod(whole, 86400)
    hour, within = divmod(within, 3600)
    minute, second = divmod(within, 60)
    text = f'{hour:02d}:{minute:02d}:{second:02d}'
    fraction = seconds - whole
    if fraction:
        text += ' + ' + exact(fraction) + ' detik'
    if days:
        text += f' (+{days} hari)'
    return text


def render_plan(record, source):
    if not isinstance(record, dict) or set(record) != PLAN_FIELDS or type(record['v']) is not int or record['v'] != 2:
        raise Violation('invalid_fields')
    if any(not isinstance(record[k], list) or len(record[k]) > MAX_ITEMS for k in ('q', 's', 'o', 'u')):
        raise Violation('invalid_list')
    has_id, has_en = bool(ID_LANGUAGE.search(source)), bool(EN_LANGUAGE.search(source))
    locale = 'id' if has_id and not has_en else 'en' if has_en and not has_id else None
    values = [parse_input(q, source, locale) for q in record['q']]
    for row in record['s']:
        values.append(operation(row, values, source))
    lines = []
    for row in record['o']:
        if not isinstance(row, list) or len(row) != 2 or type(row[0]) is not int or not 0 <= row[0] < len(values):
            raise Violation('invalid_output_reference')
        value, target = values[row[0]], row[1]
        if target == 'clock' and isinstance(value, Clock):
            lines.append('Waktu hasil perhitungan: ' + render_clock(value.seconds))
        elif isinstance(value, Quantity):
            scale = unit(target)
            if scale.dimensions != value.dimensions:
                raise Violation('dimension_mismatch')
            shown = checked(value.value / scale.factor)
            lines.append('Hasil hitung: ' + exact(shown) + (' ' + scale.label if scale.label else ''))
            if any(key.startswith('count:') for key, power in value.dimensions) and value.value.denominator != 1:
                lines.append('Hasil pecahan dipertahankan. Sebagai jumlah entitas diskret, hasil ini tidak konsisten dan perlu klarifikasi; tidak dibulatkan.')
        else:
            raise Violation('invalid_output_unit')
    if record['u'] and not has_missing_input_evidence(source):
        raise Violation('unsubstantiated_missing_input')
    lines.extend(missing_inputs(record['u']))
    if not lines:
        raise Violation('empty_answer')
    return '\n\n'.join(lines)
