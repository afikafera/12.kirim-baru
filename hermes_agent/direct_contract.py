"""Bounded DIRECT transport decoding; never repairs or executes model text."""
import json
import re

MAX_CONTENT_CHARS = 32000
LEGACY_FIELDS = {'facts', 'calculations', 'unknowns', 'examples'}
PLAN_FIELDS = {'v', 'q', 's', 'o', 'u'}
MISSING_INPUT = re.compile(
    r'\b(?:missing|not\s+(?:given|provided|specified)|'
    r'(?:tidak|belum)\s+(?:diberikan|disebutkan|diketahui|dihitung|diukur|tersedia))\b', re.I)


def has_missing_input_evidence(source):
    """A model's inability to calculate is not a user statement of missing data."""
    return bool(MISSING_INPUT.search(source))


class ContractViolation(ValueError):
    pass


def serialize_content(content):
    """Only recognized proof objects may cross a structured-content adapter."""
    if not isinstance(content, dict) or set(content) not in (LEGACY_FIELDS, PLAN_FIELDS):
        raise ContractViolation('invalid_content')
    try:
        text = json.dumps(content, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ContractViolation('invalid_content') from exc
    if len(text) > MAX_CONTENT_CHARS:
        raise ContractViolation('invalid_content')
    return text


def decode_proof(content):
    if isinstance(content, dict):
        content = serialize_content(content)
    if not isinstance(content, str) or len(content) > MAX_CONTENT_CHARS:
        raise ContractViolation('invalid_content')
    text = content.strip()
    fence = chr(96) * 3
    if text.startswith(fence):
        match = re.fullmatch(re.escape(fence) + r'(?:json)?\s*\n(.*?)\n' + re.escape(fence), text, re.S | re.I)
        if not match:
            raise ContractViolation('invalid_json')
        text = match.group(1)

    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ContractViolation('duplicate_field')
            obj[key] = value
        return obj

    def reject_constant(_value):
        raise ContractViolation('invalid_number')

    try:
        return json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ContractViolation('invalid_json') from exc
