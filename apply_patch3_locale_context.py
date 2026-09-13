"""
PATCH 3 (2026-09-08): applies to hermes_agent/fact_checker.py.

What this does:
  1. Fixes _value_is_example_scoped (PATCH 2c) -- the end-of-clause
     search now starts after the matched value/number, not at its
     start, so a value containing its own '.' (e.g. "1.5 cf") can no
     longer collide with that internal '.' and miss an example marker
     that follows it in the same clause. Proven via isolated
     OLD-vs-CANDIDATE audit, 7/7, zero regressions.
  2. Adds classify_value_support() -- the Step 2 numeric-fidelity
     classifier (EXACT / UNAMBIGUOUS_NORMALIZED / AMBIGUOUS / MISMATCH).
  3. Adds resolve_ambiguous() -- the Step 3 contextual disambiguation
     resolver for AMBIGUOUS facts only (currency/unit adjacency +
     windowed document-consistency propagation; never field_id, never
     "plausible for X" reasoning).
  4. Replaces the fact-validation block inside extract_facts_batch()
     with the approved order: PATCH2 example-scope (hard gate, always
     checked first) -> Step 2 classify -> (MISMATCH: reject immediately;
     AMBIGUOUS: Step 3 resolve, reject unless ACCEPT_CONTEXTUAL;
     EXACT/UNAMBIGUOUS_NORMALIZED: fall through to accept).

Does NOT touch FactRanker, dedup logic, evaluate(), or search/fetch
components -- only fact_checker.py, only the pieces above.

Usage:
    cd ~/research-assistant
    python3 apply_patch3_locale_context.py

On success: hermes_agent/fact_checker.py is patched in place, a
timestamped backup is left next to it, and the file is confirmed to
py_compile. On any assertion or compile failure, the original file is
restored automatically and nothing is left half-applied.

This script does NOT run the regression suite (Step 2 harness, PATCH2
audit, Step 3 harness, integration_harness, production FactChecker
regression, BTC trace replay, full 80/80) -- those are separate,
subsequent steps per the agreed procedure. A successful run of this
script means "compiles", not "verified".
"""
import py_compile
import shutil
import sys
from datetime import datetime

TARGET = "hermes_agent/fact_checker.py"

OLD_BLOCK_1 = '''def _value_is_example_scoped(value: str, source_content: str) -> bool:
    """Deterministic example-scope gate (PATCH 2): a fact is rejected if
    its value sits in the same clause as an example/illustration marker
    in the source content. Values inside an illustrative example (e.g. a
    formula's worked example) are not the subject's actual values, even
    though PATCH 1's numeric fidelity gate correctly lets them through
    (the numbers genuinely appear in the source).

    Clause boundaries are '.', '!', '?', newline, and ';' (PATCH 2b) --
    the semicolon is included so a compound sentence like "For example,
    X; this one specifies Y" does not let the leading example marker
    reach across the semicolon and wrongly reject the genuine value Y.
    No contrastive-conjunction heuristic (but/however/this model) is
    used -- semicolon only, kept deterministic and minimal."""
    if not value or not source_content:
        return False

    idx = source_content.find(value)
    if idx == -1:
        for num in _NUM_PATTERN.findall(value):
            idx = source_content.find(num)
            if idx != -1:
                break
    if idx == -1:
        return False

    start = max(
        source_content.rfind('.', 0, idx),
        source_content.rfind('\\n', 0, idx),
        source_content.rfind('!', 0, idx),
        source_content.rfind('?', 0, idx),
        source_content.rfind(';', 0, idx),
    )
    end_candidates = [
        p for p in (
            source_content.find('.', idx),
            source_content.find('!', idx),
            source_content.find('?', idx),
            source_content.find(';', idx),
        ) if p != -1
    ]
    end = min(end_candidates) if end_candidates else len(source_content)

    sentence = source_content[start + 1:end + 1]
    return bool(_EXAMPLE_MARKERS.search(sentence))'''

NEW_BLOCK_1 = '''def _value_is_example_scoped(value: str, source_content: str) -> bool:
    """Deterministic example-scope gate (PATCH 2, fixed 2026-09-08 --
    PATCH 2c): a fact is rejected if its value sits in the same clause
    as an example/illustration marker in the source content. Values
    inside an illustrative example (e.g. a formula's worked example)
    are not the subject's actual values, even though PATCH 1's numeric
    fidelity gate correctly lets them through (the numbers genuinely
    appear in the source).

    Clause boundaries are '.', '!', '?', newline, and ';' (PATCH 2b) --
    the semicolon is included so a compound sentence like "For example,
    X; this one specifies Y" does not let the leading example marker
    reach across the semicolon and wrongly reject the genuine value Y.
    No contrastive-conjunction heuristic (but/however/this model) is
    used -- semicolon only, kept deterministic and minimal.

    PATCH 2c: the end-of-clause search now starts after the matched
    value/number (idx + match_len) instead of at its start (idx). A
    value containing its own '.' (e.g. a decimal like "1.5 cf") was
    colliding with that internal '.' as a false clause end, silently
    missing any example marker that came AFTER the value in the same
    clause. Proven via isolated OLD-vs-CANDIDATE audit: 7/7, including
    a regression-safety case (marker in the genuinely next clause) and
    a semicolon-boundary case, both unaffected by this change."""
    if not value or not source_content:
        return False

    idx = source_content.find(value)
    match_len = len(value)
    if idx == -1:
        for num in _NUM_PATTERN.findall(value):
            idx = source_content.find(num)
            if idx != -1:
                match_len = len(num)
                break
    if idx == -1:
        return False

    end_search_from = idx + match_len

    start = max(
        source_content.rfind('.', 0, idx),
        source_content.rfind('\\n', 0, idx),
        source_content.rfind('!', 0, idx),
        source_content.rfind('?', 0, idx),
        source_content.rfind(';', 0, idx),
    )
    end_candidates = [
        p for p in (
            source_content.find('.', end_search_from),
            source_content.find('!', end_search_from),
            source_content.find('?', end_search_from),
            source_content.find(';', end_search_from),
        ) if p != -1
    ]
    end = min(end_candidates) if end_candidates else len(source_content)

    sentence = source_content[start + 1:end + 1]
    return bool(_EXAMPLE_MARKERS.search(sentence))


# ---------------------------------------------------------------------
# PATCH 3 (2026-09-08): numeric-fidelity classifier (Step 2) and
# contextual disambiguation resolver (Step 3).
#
# Step 2 separates "does this value's number appear in the source under
# ANY valid locale reading" (EXACT / UNAMBIGUOUS_NORMALIZED / AMBIGUOUS
# / MISMATCH) from Step 3's "can surrounding context PROVE which
# reading is correct" for the AMBIGUOUS case only. Context may PROVE an
# interpretation; it may never INVENT a value. Verified via isolated
# harnesses (numeric-classification matrix, contextual-disambiguation
# matrix with real-trace excerpts and adversarial leakage probes, and a
# full Step2->PATCH2->Step3 integration matrix, 7/7) before being
# wired in here.
# ---------------------------------------------------------------------

EXACT = "EXACT"
UNAMBIGUOUS_NORMALIZED = "UNAMBIGUOUS_NORMALIZED"
AMBIGUOUS = "AMBIGUOUS"
MISMATCH = "MISMATCH"

_FACT_CLASS_RANK = {
    MISMATCH: 0,
    AMBIGUOUS: 1,
    UNAMBIGUOUS_NORMALIZED: 2,
    EXACT: 3,
}

_SOURCE_TOKEN_PATTERN = re.compile(
    r'\\d{1,3}(?:[.,]\\d{3}(?!\\d))+(?:[.,]\\d+)?|\\d+(?:[.,]\\d+)?'
)


def _parse_candidate_number(token: str):
    """Parse an LLM-extracted numeric token (already normalized to
    English style: no thousands separators, '.' only as a genuine
    decimal point) into a float. Strips a single trailing unit letter
    (T/M/B/K) and a trailing '%'."""
    v = token.strip().rstrip('%')
    v = re.sub(r'[TMBK]$', '', v, flags=re.IGNORECASE)
    v = v.replace(',', '')
    try:
        return float(v)
    except ValueError:
        return None


def _classify_source_token(token: str):
    """Return the list of 1 or 2 float readings a raw SOURCE token can
    represent. 2 readings means the token has the irreducibly ambiguous
    shape (exactly one separator, exactly 3 trailing digits): it could
    be a thousands-grouped integer OR a 3-decimal fraction, and the
    shape alone cannot tell which."""
    seps = re.findall(r'[.,]', token)
    groups = re.split(r'[.,]', token)

    if len(seps) == 0:
        try:
            return [float(token)]
        except ValueError:
            return []

    if len(seps) >= 2:
        distinct_seps = set(seps)
        if len(distinct_seps) == 2:
            int_part = "".join(groups[:-1])
            try:
                return [float(f"{int_part}.{groups[-1]}")]
            except ValueError:
                return []
        if all(len(g) == 3 for g in groups[1:]):
            try:
                return [float("".join(groups))]
            except ValueError:
                return []
        int_part = "".join(groups[:-1])
        try:
            return [float(f"{int_part}.{groups[-1]}")]
        except ValueError:
            return []

    int_part, frac_part = groups[0], groups[1]
    if len(frac_part) == 3:
        try:
            return [float(int_part + frac_part), float(f"{int_part}.{frac_part}")]
        except ValueError:
            return []
    try:
        return [float(f"{int_part}.{frac_part}")]
    except ValueError:
        return []


def _classify_number_support(candidate_number: str, source_content: str) -> str:
    haystack = source_content or ""
    cand_str = candidate_number.strip()

    if cand_str and cand_str in haystack:
        return EXACT

    cand_f = _parse_candidate_number(cand_str)
    if cand_f is None:
        return EXACT

    best = MISMATCH
    for token in _SOURCE_TOKEN_PATTERN.findall(haystack):
        readings = _classify_source_token(token)
        if not readings:
            continue
        if len(readings) == 1:
            if abs(readings[0] - cand_f) < 1e-9 and _FACT_CLASS_RANK[UNAMBIGUOUS_NORMALIZED] > _FACT_CLASS_RANK[best]:
                best = UNAMBIGUOUS_NORMALIZED
        else:
            if any(abs(r - cand_f) < 1e-9 for r in readings) and _FACT_CLASS_RANK[AMBIGUOUS] > _FACT_CLASS_RANK[best]:
                best = AMBIGUOUS
    return best


def classify_value_support(value: str, source_content: str) -> str:
    """Numeric-fidelity classifier (Step 2). Classifies how well a
    candidate fact value's number(s) are supported by source_content:
    EXACT (literal substring match), UNAMBIGUOUS_NORMALIZED (not a
    literal match, but a source number parses into exactly one valid
    locale reading -- multi-group thousands, mixed separator types, or
    a fractional group that isn't exactly 3 digits -- equal to the
    candidate), AMBIGUOUS (a source number has the irreducible
    "1 separator + 3 digits" shape whose thousands reading matches the
    candidate, but the decimal reading is equally valid from shape
    alone), or MISMATCH (no source number, under any reading, supports
    the candidate -- fail-closed, same spirit as the original numeric
    fidelity gate).

    For a value containing multiple numbers, the overall result is the
    WORST of all its numbers' classifications (fail-closed combination,
    same as the original gate's all(...))."""
    numbers = _NUM_PATTERN.findall(value or "")
    if not numbers:
        return EXACT

    worst = EXACT
    for num in numbers:
        cls = _classify_number_support(num, source_content)
        if _FACT_CLASS_RANK[cls] < _FACT_CLASS_RANK[worst]:
            worst = cls
    return worst


# --- Step 3: contextual disambiguation, AMBIGUOUS facts only. --------

ACCEPT_CONTEXTUAL = "ACCEPT_CONTEXTUAL"
REJECT_CONTEXTUAL = "REJECT_CONTEXTUAL"
UNRESOLVED = "UNRESOLVED"

# Window (characters) searched on each side of an AMBIGUOUS token for a
# same-separator precedent that Step 2 already resolves unambiguously
# (Rule 2, document-consistency propagation). Swept across
# 50/100/200/300/500 chars against the real BTC trace plus adversarial
# leakage cases with zero change in outcome; 300 is a working default,
# not proven optimal -- revisit if a future case shows sensitivity.
WINDOW_CHARS = 300

_CLAUSE_BOUNDARY_CHARS = ('.', '!', '?', '\\n', ';')

_CURRENCY_MARKERS = re.compile(
    r'\\bUSD\\b|\\bUSDT\\b|\\bUSDC\\b|\\bIDR\\b|\\bRp\\b|\\bEUR\\b|\\bGBP\\b|\\$',
    re.IGNORECASE,
)


def _clause_span(source_content: str, token_start: int, token_end: int):
    """Clause boundaries: '.', '!', '?', newline, ';' -- same convention
    as _value_is_example_scoped. The END boundary is searched starting
    from token_end (right after the matched token), not token_start, so
    a token's own internal separator (e.g. the '.' in "78.347") is never
    mistaken for the end of the clause."""
    start = max(
        (source_content.rfind(c, 0, token_start) for c in _CLAUSE_BOUNDARY_CHARS),
        default=-1,
    )
    end_candidates = [
        p for p in (source_content.find(c, token_end) for c in _CLAUSE_BOUNDARY_CHARS)
        if p != -1
    ]
    end = min(end_candidates) if end_candidates else len(source_content)
    return start + 1, end + 1


def _find_ambiguous_occurrences(candidate_value: str, source_content: str):
    cand_f = _parse_candidate_number(candidate_value)
    if cand_f is None:
        return []
    spans = []
    for m in _SOURCE_TOKEN_PATTERN.finditer(source_content):
        readings = _classify_source_token(m.group())
        if len(readings) == 2 and any(abs(r - cand_f) < 1e-9 for r in readings):
            spans.append((m.start(), m.end(), m.group()))
    return spans


def _rule1_currency_adjacency(source_content: str, match_start: int, match_end: int) -> bool:
    """Rule 1 (POLICY, not mathematical proof): a currency/unit marker
    in the SAME CLAUSE as the ambiguous token. Standard money notation
    uses 2 decimal places, not 3 -- a 3-digit fractional reading is
    inconsistent with money notation for any currency, so the thousands
    reading is the only one consistent with it. This is a documented
    Hermes policy choice (a general currency-formatting convention), not
    a mathematical proof that a 3-digit decimal currency is impossible."""
    clause_start, clause_end = _clause_span(source_content, match_start, match_end)
    clause = source_content[clause_start:clause_end]
    return bool(_CURRENCY_MARKERS.search(clause))


def _rule2_document_consistency(source_content: str, match_start: int, match_end: int, token_text: str, cand_f: float, window_chars: int = WINDOW_CHARS) -> bool:
    """Rule 2: if the same separator character is used UNAMBIGUOUSLY
    elsewhere within window_chars of the ambiguous token (per Step 2's
    own multi-group/mixed-type/non-3-digit-fraction rules), that
    resolved role (thousands vs decimal) is propagated to the ambiguous
    token. Bounded window because the same separator can mean different
    things in different sections of the same document (observed live:
    a source page can use ',' as decimal in one section and as
    thousands in another)."""
    sep_match = re.search(r'[.,]', token_text)
    if not sep_match:
        return False
    sep_char = sep_match.group()

    win_start = max(0, match_start - window_chars)
    win_end = min(len(source_content), match_end + window_chars)
    window = source_content[win_start:win_end]

    for m in _SOURCE_TOKEN_PATTERN.finditer(window):
        if m.group() == token_text and (win_start + m.start()) == match_start:
            continue
        if sep_char not in m.group():
            continue
        readings = _classify_source_token(m.group())
        if len(readings) != 1:
            continue

        g = re.split(r'[.,]', m.group())
        try:
            thousands_try = float("".join(g))
        except ValueError:
            thousands_try = None
        role_is_thousands = (
            thousands_try is not None and abs(thousands_try - readings[0]) < 1e-9
        )

        our_groups = re.split(r'[.,]', token_text)
        if role_is_thousands:
            candidate_reading = float("".join(our_groups))
        else:
            candidate_reading = float(f"{our_groups[0]}.{our_groups[1]}")

        if abs(candidate_reading - cand_f) < 1e-9:
            return True
    return False


def resolve_ambiguous(candidate_value: str, source_content: str, window_chars: int = WINDOW_CHARS) -> str:
    """Contextual disambiguation (Step 3) for a fact value Step 2
    classified AMBIGUOUS. Uses only: the clause/context around the
    candidate number, explicit currency/unit markers, same-document
    numeric precedent within a bounded window, and clause boundaries --
    never field_id, never internal variable names, never "this number
    is plausible" reasoning. PATCH 2's example-scope gate is checked
    first and always wins (REJECT_CONTEXTUAL) regardless of Rule 1/2."""
    cand_f = _parse_candidate_number(candidate_value)
    if cand_f is None:
        return UNRESOLVED

    occurrences = _find_ambiguous_occurrences(candidate_value, source_content)
    if not occurrences:
        return UNRESOLVED

    saw_accept = False
    for match_start, match_end, token_text in occurrences:
        clause_start, clause_end = _clause_span(source_content, match_start, match_end)
        clause = source_content[clause_start:clause_end]

        if _value_is_example_scoped(token_text, clause) or _value_is_example_scoped(candidate_value, clause):
            return REJECT_CONTEXTUAL

        if _rule1_currency_adjacency(source_content, match_start, match_end):
            saw_accept = True
            continue

        if _rule2_document_consistency(source_content, match_start, match_end, token_text, cand_f, window_chars):
            saw_accept = True
            continue

    return ACCEPT_CONTEXTUAL if saw_accept else UNRESOLVED'''

OLD_BLOCK_2 = '''                fact_value = str(value.get("value", ""))
                source_content = url_to_content.get(src, "")
                if not _value_supported_by_source(fact_value, source_content):
                    logger.warning(
                        "[FACT REJECT] field=%s reason=value_not_in_evidence value=%r source=%r",
                        key,
                        fact_value,
                        src,
                    )
                    continue

                if _value_is_example_scoped(fact_value, source_content):
                    logger.warning(
                        "[FACT REJECT] field=%s reason=example_value_not_actual value=%r source=%r",
                        key,
                        fact_value,
                        src,
                    )
                    continue'''

NEW_BLOCK_2 = '''                fact_value = str(value.get("value", ""))
                source_content = url_to_content.get(src, "")

                # PATCH 2 example-scope is a hard gate, checked first,
                # for ALL facts -- an example-scoped value must never be
                # accepted regardless of what the numeric classifier or
                # Step 3 contextual resolver would otherwise say.
                if _value_is_example_scoped(fact_value, source_content):
                    logger.warning(
                        "[FACT REJECT] field=%s reason=example_value_not_actual value=%r source=%r",
                        key,
                        fact_value,
                        src,
                    )
                    continue

                numeric_class = classify_value_support(fact_value, source_content)

                if numeric_class == MISMATCH:
                    logger.warning(
                        "[FACT REJECT] field=%s reason=value_not_in_evidence value=%r source=%r",
                        key,
                        fact_value,
                        src,
                    )
                    continue

                if numeric_class == AMBIGUOUS:
                    contextual = resolve_ambiguous(fact_value, source_content)
                    if contextual != ACCEPT_CONTEXTUAL:
                        logger.warning(
                            "[FACT REJECT] field=%s reason=ambiguous_numeric_%s value=%r source=%r",
                            key,
                            contextual.lower(),
                            fact_value,
                            src,
                        )
                        continue

                # EXACT / UNAMBIGUOUS_NORMALIZED, or AMBIGUOUS resolved
                # ACCEPT_CONTEXTUAL by Step 3: fall through to accept.'''


def main():
    with open(TARGET, "r", encoding="utf-8") as f:
        src = f.read()

    assert src.count(OLD_BLOCK_1) == 1, (
        f"OLD_BLOCK_1 not found exactly once (found {src.count(OLD_BLOCK_1)}) -- "
        "source has drifted from what was audited, aborting without changes."
    )
    assert src.count(OLD_BLOCK_2) == 1, (
        f"OLD_BLOCK_2 not found exactly once (found {src.count(OLD_BLOCK_2)}) -- "
        "source has drifted from what was audited, aborting without changes."
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{TARGET}.bak_patch3_locale_context_{timestamp}"
    shutil.copy2(TARGET, backup_path)
    print(f"[backup] {backup_path}")

    new_src = src.replace(OLD_BLOCK_1, NEW_BLOCK_1, 1)
    new_src = new_src.replace(OLD_BLOCK_2, NEW_BLOCK_2, 1)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(new_src)
    print(f"[written] {TARGET}")

    try:
        py_compile.compile(TARGET, doraise=True)
        print("[py_compile] OK")
    except py_compile.PyCompileError as e:
        print(f"[py_compile] FAILED: {e}")
        shutil.copy2(backup_path, TARGET)
        print(f"[rollback] restored {TARGET} from {backup_path}")
        sys.exit(1)

    print()
    print("PATCH 3 applied and compiles. NOT YET VERIFIED.")
    print("Next: run the regression sequence (Step 2 harness, PATCH2 audit,")
    print("Step 3 harness, integration_harness, production FactChecker")
    print("regression, BTC trace replay, full 80/80) before calling this VERIFIED.")


if __name__ == "__main__":
    main()
