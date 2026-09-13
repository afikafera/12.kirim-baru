import json
import re
import logging
from collections import Counter

from hermes_agent.llm_output_contract import llm_output_failure

logger = logging.getLogger(__name__)


def extract_json(text: str):
    try:
        return json.loads(text)
    except:
        pass
    first_brace = text.find('{')
    first_bracket = text.find('[')
    if first_bracket != -1 and (first_brace == -1 or first_bracket < first_brace):
        patterns = [r'\[.*\]', r'\{.*\}']
    else:
        patterns = [r'\{.*\}', r'\[.*\]']
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
    return {}


_NUM_PATTERN = re.compile(r'\d+(?:[.,]\d+)?')


def _value_supported_by_source(value: str, source_content: str) -> bool:
    """Deterministic numeric fidelity gate (PATCH 1): every numeric token
    in a candidate fact value must literally appear in the raw content of
    the source it claims to come from. Non-numeric values pass through
    unchanged (semantic/text validation is out of scope for PATCH 1)."""
    numbers = _NUM_PATTERN.findall(value or "")
    if not numbers:
        return True
    haystack = source_content or ""
    return all(num in haystack for num in numbers)


_NON_FACT_SENTINELS = re.compile(
    r'^(not\s+(found|available|specified|mentioned|provided|in\s+evidence|present)|'
    r'none|n/?a|unknown|null|nil|'
    r'tidak\s+(ditemukan|tersedia|ada)|data\s+tidak\s+ditemukan)'
    r'(\s+(in\s+evidence|dalam\s+bukti|in\s+document|pada\s+dokumen))?[\s.]*$',
    re.IGNORECASE,
)


def _is_sentinel_non_fact(value: str) -> bool:
    """Non-fact sentinel gate: checks whether a candidate fact value
    merely asserts the absence of evidence (e.g. 'Not found in evidence',
    'N/A', 'none', 'tidak ditemukan'). Such negative assertions are not
    substantive facts and must never be accepted as evidence."""
    if not value or not isinstance(value, str):
        return True
    cleaned = value.strip()
    if not cleaned:
        return True
    return bool(_NON_FACT_SENTINELS.match(cleaned))


_EXAMPLE_MARKERS = re.compile(
    r'\b(example|e\.g\.|for instance|for example|sample calculation|'
    r'misalnya|contoh|sebagai contoh)\b',
    re.IGNORECASE,
)


def _value_is_example_scoped(value: str, source_content: str) -> bool:
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
        source_content.rfind('\n', 0, idx),
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
    r'\d{1,3}(?:[.,]\d{3}(?!\d))+(?:[.,]\d+)?|\d+(?:[.,]\d+)?'
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

_HARD_BOUNDARY_PATTERN = re.compile(r'[.!?;]|\n[ \t]*\n')

_CURRENCY_MARKERS = re.compile(
    r'\bUSD\b|\bUSDT\b|\bUSDC\b|\bIDR\b|\bRp\b|\bEUR\b|\bGBP\b|\$',
    re.IGNORECASE,
)


def _clause_span(source_content: str, token_start: int, token_end: int):
    """Clause boundaries (PATCH 3B, 2026-09-08): '.', '!', '?', ';', or
    a blank-line run ('\n' plus optional spaces/tabs plus '\n') are
    HARD boundaries. A single bare '\n' is layout-only whitespace (e.g.
    a scraper line break between a number and its immediately adjacent
    unit, such as TradingView's "78.347\nUSD") and is NOT a boundary by
    itself -- only a genuine blank-line run ends the clause. Verified
    via an isolated A/B/C candidate comparison (12-case matrix,
    including adversarial leak probes) plus a byte-exact replay against
    the real TradingView/CoinDesk evidence before being wired in here;
    this was the only candidate to pass every case.

    The END boundary is searched starting from token_end (right after
    the matched token), not token_start, so a token's own internal
    separator (e.g. the '.' in "78.347") is never mistaken for a clause
    boundary (PATCH 3 behavior, unchanged by this patch)."""
    clause_start = 0
    for m in _HARD_BOUNDARY_PATTERN.finditer(source_content):
        if m.start() >= token_start:
            break
        clause_start = m.end()

    m2 = _HARD_BOUNDARY_PATTERN.search(source_content, token_end)
    clause_end = m2.start() if m2 else len(source_content)

    return clause_start, clause_end


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
        # PATCH 3B: PATCH 2's example-scope check (Rule 0) now runs
        # against the FULL source_content, not a Step-3-computed clause
        # -- this decouples it completely from whichever clause-
        # boundary rule Rule 1 uses below. _value_is_example_scoped's
        # own internal boundary logic is untouched by this patch.
        if _value_is_example_scoped(token_text, source_content) or _value_is_example_scoped(candidate_value, source_content):
            return REJECT_CONTEXTUAL

        if _rule1_currency_adjacency(source_content, match_start, match_end):
            saw_accept = True
            continue

        if _rule2_document_consistency(source_content, match_start, match_end, token_text, cand_f, window_chars):
            saw_accept = True
            continue

    return ACCEPT_CONTEXTUAL if saw_accept else UNRESOLVED


def _normalize_extraction_kvs(all_kvs: dict, all_evidence: list) -> dict:
    """
    PATCH 10: Transform flat key-value pairs with root metadata into canonical nested dicts:
      {"field": {"value": "...", "source": "...", "source_type": "..."}}
    Preserves already-nested dicts unchanged.
    Strictly provenance-aware: root_source must match a URL present in all_evidence.
    If root_source is absent or invalid, flat primitives are NOT converted to facts.
    """
    if not isinstance(all_kvs, dict):
        return {}

    valid_urls = {
        str(e.get("url", "")).strip()
        for e in (all_evidence or [])
        if e.get("url")
    }

    root_source = all_kvs.get("source_url") or all_kvs.get("source")
    root_source_type = all_kvs.get("source_type", "other")

    if not root_source and len(all_evidence or []) == 1 and all_evidence[0].get("url"):
        root_source = all_evidence[0]["url"]
        root_source_type = (
            all_evidence[0].get("source_type")
            or all_evidence[0].get("doc_type")
            or "other"
        )

    clean_root_source = str(root_source).strip() if root_source else ""
    if clean_root_source not in valid_urls:
        clean_root_source = None

    normalized = {}
    metadata_keys = {"source_url", "source", "source_type", "url"}

    for key, value in all_kvs.items():
        if key in metadata_keys:
            continue

        if isinstance(value, dict):
            item_dict = dict(value)
            if not item_dict.get("source") and clean_root_source:
                item_dict["source"] = clean_root_source
            if not item_dict.get("source_type") and clean_root_source and root_source_type:
                item_dict["source_type"] = str(root_source_type).strip()
            normalized[key] = item_dict
        elif isinstance(value, (str, int, float, bool)) and clean_root_source:
            normalized[key] = {
                "value": str(value),
                "source": clean_root_source,
                "source_type": str(root_source_type).strip(),
            }
        else:
            continue

    return normalized


class FactChecker:

    MAX_EVIDENCE_SOURCES = 3
    MAX_CHARS_PER_SOURCE = 5000
    MAX_EVIDENCE_CHARS = 15000

    SOURCE_WEIGHTS = {
        "datasheet": 1.0, "pdf": 0.9, "official_docs": 0.9,
        "manual": 0.85, "spec_table": 0.85, "measurement": 0.8,
        "tsb": 0.8, "catalog": 0.7, "forum": 0.5,
        "tutorial": 0.4, "review": 0.35, "video": 0.3,
        "github": 0.7, "other": 0.2, "": 0.1,
    }

    def __init__(self, llm_analyzer):
        self.llm = llm_analyzer

    def generate_checklist(self, query: str, intent: str, domain: str) -> tuple:
        checklist = [{"field_id": "facts", "label": "All extracted facts"}]
        return (checklist, {"tokens_input": 0, "tokens_output": 0, "api_cost": 0})

    def extract_facts_batch(self, all_evidence: list, checklist: list) -> tuple:
        if not all_evidence:
            return ({}, {"tokens_input": 0, "tokens_output": 0, "api_cost": 0})

        BAD_PATTERNS = (
            "error fetch",
            "error_fetch",
            "traceback",
            "access denied",
            "cloudflare",
            "captcha",
            "enable javascript",
            "request failed",
        )

        candidates = [
            e for e in all_evidence
            if isinstance(e, dict) and e.get("content")
            and not any(
                pat in e["content"].lower()
                for pat in BAD_PATTERNS
            )
        ]

        # Keep the most valuable documents instead of spending tokens on a
        # long tail of search results.  The full evidence remains available
        # in the graph; this only limits a single extraction prompt.
        source_priority = {
            "datasheet": 5,
            "pdf": 5,
            "official_docs": 4,
            "manual": 4,
            "spec_table": 4,
            "catalog": 3,
            "forum": 2,
            "video": 1,
        }
        for e in candidates:
            c = e.get("content", "")
            if "xmax" in c.lower() or "5.65" in c:
                logger.info(
                    "[TRACE XMAX] stage=fact_checker_candidates url=%s doc_type=%s priority=%s content_len=%d",
                    e.get("url"), e.get("doc_type"),
                    source_priority.get(str(e.get("evidence_type") or e.get("doc_type") or "").lower(), 0),
                    len(c),
                )

        selected = sorted(
            candidates,
            key=lambda e: source_priority.get(
                str(e.get("evidence_type") or e.get("doc_type") or "").lower(),
                0,
            ),
            reverse=True,
        )[:self.MAX_EVIDENCE_SOURCES]

        selected_urls = [e.get("url") for e in selected]
        for e in candidates:
            c = e.get("content", "")
            if ("xmax" in c.lower() or "5.65" in c) and e.get("url") not in selected_urls:
                logger.info(
                    "[TRACE XMAX] stage=fact_checker_DROPPED_by_priority url=%s doc_type=%s",
                    e.get("url"), e.get("doc_type"),
                )

        evidence_blocks = []

        # Hitung kuota karakter dinamis per sumber.
        # Tetap menjaga total evidence dalam batas global.
        num_selected = max(1, len(selected))
        dynamic_limit = self.MAX_EVIDENCE_CHARS // num_selected
        per_source_limit = min(self.MAX_CHARS_PER_SOURCE, dynamic_limit)

        for i, e in enumerate(selected):
            source_type = e.get("evidence_type") or e.get("doc_type") or "other"
            header = (
                f"### SUMBER {i+1}: {e.get('url', 'unknown')} "
                f"(tipe: {source_type})\n"
            )

            raw_content = e.get("content", "")

            # Jangan potong raw text di tengah baris.
            paragraphs = raw_content.split("\n")

            source_text = header
            for p in paragraphs:
                if len(source_text) + len(p) + 1 <= per_source_limit:
                    source_text += p + "\n"
                else:
                    break

            evidence_blocks.append(source_text.strip())

        evidence_text = "\n\n".join(evidence_blocks)

        logger.info(
            "[TOKEN OPTIMIZATION] extract candidates=%d selected=%d evidence_chars=%d cap=%d",
            len(candidates),
            len(selected),
            len(evidence_text),
            self.MAX_EVIDENCE_CHARS,
        )
        final_evidence = evidence_text
        logger.info(
            "[TRACE XMAX] stage=fact_checker_evidence_text xmax_survives=%s",
            ("xmax" in final_evidence.lower() or "5.65" in final_evidence),
        )

        # Guard kedua: evidence bisa kosong setelah BAD_PATTERNS filter.
        if not final_evidence.strip():
            logger.info(
                "[extract] skip: evidence kosong setelah filter "
                "(all_evidence=%d candidates=%d selected=%d)",
                len(all_evidence), len(candidates), len(selected),
            )
            return ({}, {"tokens_input": 0, "tokens_output": 0, "api_cost": 0})

        requirement_lines = []
        for item in checklist or []:
            if not isinstance(item, dict):
                continue
            field_id = str(item.get("field_id", "")).strip()
            label = str(item.get("label", "")).strip()
            if field_id or label:
                requirement_lines.append(f"- {field_id}: {label}")

        requirement_scope = "\n".join(requirement_lines).strip()

        if not requirement_scope:
            requirement_scope = "- No specific research requirement supplied."

        prompt = f"""Extract ONLY facts required to satisfy the research requirements.

RESEARCH REQUIREMENTS:
{requirement_scope}

EXTRACTION SCOPE:
- Extract only facts directly answering the research requirements above.
- Ignore unrelated facts, even when they are substantive.
- Preserve exact values, units, timestamps, URLs, commands, and technical terms.
- Do not invent, infer, or fabricate missing information.

RULES:
1. Extract substantive facts only: specifications, values, numbers, commands,
   code, steps, symptoms, causes, solutions, tools, endpoints, configuration,
   and other relevant technical information.
2. Ignore menus, navigation, footers, copyright notices, breadcrumbs,
   page titles, section names, link lists, and UI text that does not contain
   substantive facts.
3. Do not turn page titles or navigation labels into domain facts.
4. A URL may be extracted only when the URL itself is a relevant fact,
   such as an API endpoint, documentation URL, download URL, or target URL.
5. Normalize keys to short snake_case names.
6. Specify source URL and source_type at root level or inside each fact.
7. NEVER invent, infer, or fabricate values that are not explicitly present
   in the evidence.
8. If the evidence contains only metadata or navigation and no substantive
   facts, return no facts rather than creating facts to fill the output.
9. Preserve exact numeric values, units, URLs, commands, and technical terms
   from the evidence.

EVIDENCE:
{final_evidence}

Return JSON:
{{"source_url": "URL", "source_type": "type", "field_name": "value"}}
or nested:
{{"field_id": {{"value": "value", "source": "URL", "source_type": "type"}}}}"""

        try:
            # PATCH 5: retry-before-give-up with an adaptive output
            # budget, mirroring PATCH 4/4c's TaskPlanner pattern. Retry
            # fires only on a call exception or a detected output-
            # contract failure (empty content / non-string content /
            # finish_reason == "length") -- NOT just because
            # extract_json() ends up returning {} on an otherwise-clean
            # response, since a genuinely fact-free evidence page is a
            # valid outcome (extractor rule 8), not a bug.
            # PATCH 11: token budget [2048, 4096] and partial JSON salvage
            extraction_max_tokens_schedule = [2048, 4096]
            all_kvs = {}
            # "content": "" so the SECOND logger.info(result["content"])
            # block further down (unchanged, pre-existing debug logging)
            # does not KeyError if every attempt is exhausted -- that
            # case must fall through as a clean empty-facts result, not
            # get mistaken for an exception in server.log.
            result = {"content": "", "tokens_input": 0, "tokens_output": 0, "api_cost": 0}
            for extract_attempt in range(1, len(extraction_max_tokens_schedule) + 1):
                attempt_max_tokens = extraction_max_tokens_schedule[extract_attempt - 1]
                try:
                    attempt_result = self.llm.analyze(
                        "You are a universal fact extractor. Extract substantive facts only. Normalize keys to short snake_case names.",
                        prompt,
                        temperature=0.1,
                        max_tokens=attempt_max_tokens,
                    )
                except Exception as e:
                    logger.warning(
                        f"[extract] call failed (attempt {extract_attempt}/{len(extraction_max_tokens_schedule)}, "
                        f"max_tokens={attempt_max_tokens}): {e}"
                    )
                    continue

                result = attempt_result

                failure = llm_output_failure(result)
                if failure is not None:
                    logger.warning(
                        f"[extract] output contract failed (attempt {extract_attempt}/{len(extraction_max_tokens_schedule)}, "
                        f"max_tokens={attempt_max_tokens}): {failure}"
                    )
                    # Truncation salvage on final attempt: salvage completed key-values
                    if failure == "length_truncated" and extract_attempt == len(extraction_max_tokens_schedule):
                        raw_c = result.get("content", "")
                        salvaged = extract_json(raw_c)
                        if not salvaged and "{" in raw_c:
                            s_idx = raw_c.find("{")
                            cand_body = raw_c[s_idx:].rstrip()
                            for cut in range(len(cand_body) - 1, 0, -1):
                                if cand_body[cut] in (",", "}", "]"):
                                    try:
                                        test_p = json.loads(cand_body[:cut].rstrip(",") + "\n}")
                                        if isinstance(test_p, dict) and test_p:
                                            salvaged = test_p
                                            break
                                    except Exception:
                                        continue
                        if salvaged and isinstance(salvaged, dict):
                            logger.info(f"[extract] salvaged {len(salvaged)} facts from length-truncated response")
                            all_kvs = salvaged
                            break
                    continue

                logger.info("=" * 80)
                logger.info("[RAW EXTRACT RESPONSE]")
                logger.info(result["content"])
                logger.info("=" * 80)
                all_kvs = extract_json(result["content"])
                break
            else:
                logger.warning(
                    f"[extract] all {len(extraction_max_tokens_schedule)} attempts exhausted, "
                    "proceeding with empty facts"
                )

            # PATCH: normalize list -> dict
            if isinstance(all_kvs, list):
                normalized = {}

                for item in all_kvs:
                    if not isinstance(item, dict):
                        continue

                    if "field_id" in item:
                        key = str(item["field_id"])
                        value = dict(item)
                        value.pop("field_id", None)
                        normalized[key] = value

                    elif "id" in item and "value" in item:
                        # PATCH 7: the extractor prompt asks for
                        # {"field_id": {...}}, but a model occasionally
                        # returns {"id": ..., "value": ..., "source": ...,
                        # "source_type": ...} instead -- same shape,
                        # different name for the identifier key. Treat
                        # it exactly like a "field_id" item rather than
                        # silently dropping it (proven live: 8/8 facts
                        # lost this way in trace
                        # 47b49071d6f3a15665268de66cdb2852).
                        key = str(item["id"])
                        value = dict(item)
                        value.pop("id", None)
                        normalized[key] = value

                    elif len(item) == 1:
                        k, v = next(iter(item.items()))
                        normalized[k] = v

                all_kvs = normalized

            elif not isinstance(all_kvs, dict):
                all_kvs = {}

            # PATCH 10: normalize flat JSON to canonical nested dicts with provenance guard
            all_kvs = _normalize_extraction_kvs(all_kvs, all_evidence)

            # Provenance guard: fact hanya boleh memakai source URL
            # yang benar-benar ada di evidence yang diberikan ke extractor.
            valid_urls = {
                str(e.get("url", "")).strip()
                for e in all_evidence
                if e.get("url")
            }
            url_to_content = {
                str(e.get("url", "")).strip(): e.get("content", "")
                for e in all_evidence
                if e.get("url")
            }

            validated = {}
            for key, value in all_kvs.items():
                if not isinstance(value, dict):
                    continue

                src = str(value.get("source", "")).strip()

                logger.info(
                    "[TRACE PROVENANCE] src=%r valid_urls=%r",
                    src,
                    sorted(valid_urls),
                )

                if not src or src not in valid_urls:
                    logger.warning(
                        "[FACT REJECT] field=%s source=%r not in evidence",
                        key,
                        src,
                    )
                    continue

                fact_value = str(value.get("value", ""))
                source_content = url_to_content.get(src, "")

                # Sentinel / Non-fact gate: do not accept absence-of-evidence
                # assertions (e.g. "Not found in evidence", "N/A", "None") as facts.
                if _is_sentinel_non_fact(fact_value):
                    logger.warning(
                        "[FACT REJECT] field=%s reason=non_fact_sentinel value=%r source=%r",
                        key,
                        fact_value,
                        src,
                    )
                    continue

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
                # ACCEPT_CONTEXTUAL by Step 3: fall through to accept.

                validated[key] = value

            all_kvs = validated

            logger.info("=" * 80)
            logger.info("[RAW EXTRACT RESPONSE]")
            logger.info(result["content"])
            logger.info("=" * 80)

            logger.info("[PARSED FACTS] total=%d", len(all_kvs))
            for k, v in all_kvs.items():
                logger.info("%s = %s", k, json.dumps(v, ensure_ascii=False))


            norm_values = [str(v.get("value", "")).strip().lower() for v in all_kvs.values()]
            dupe_counts = Counter(norm_values)
            all_kvs = {k: v for k, v in all_kvs.items()
                       if dupe_counts[str(v.get("value", "")).strip().lower()] < 3}

            logger.info(f"[extract] {len(all_kvs)} facts: {list(all_kvs.keys())[:20]}")

            for f in all_kvs.values():
                src = f.get("source", "")
                for e in all_evidence:
                    if src in e.get("url", ""):
                        e["had_facts"] = True

            return (all_kvs, result)
        except Exception as e:
            logger.warning(f"[extract] fail: {e}")
            return ({}, {"tokens_input": 0, "tokens_output": 0, "api_cost": 0})

    def generate_gap_queries(self, product: str, empty_fields: list, evidence_types: list) -> tuple:
        """Generate gap queries berdasarkan tipe evidence yang kurang."""
        if not evidence_types:
            return ([], {"tokens_input": 0, "tokens_output": 0, "api_cost": 0})

        # Cek tipe sumber yang belum ada
        missing_types = []
        for desired in ["datasheet", "pdf", "official_docs", "manual", "forum", "tutorial"]:
            if desired not in evidence_types:
                missing_types.append(desired)

        if not missing_types:
            return ([], {"tokens_input": 0, "tokens_output": 0, "api_cost": 0})

        # Buat query untuk tipe sumber yang kurang
        queries = []
        for mt in missing_types[:3]:
            if mt in ("datasheet", "pdf"):
                queries.append(f"{product} datasheet PDF download")
            elif mt == "official_docs":
                queries.append(f"site:official {product} documentation")
            elif mt == "manual":
                queries.append(f"{product} user manual guide")
            elif mt == "forum":
                queries.append(f"{product} forum discussion review")
            elif mt == "tutorial":
                queries.append(f"{product} tutorial step by step")

        logger.info(f"[gap] missing source types: {missing_types}, queries: {queries}")
        return (queries, {"tokens_input": 0, "tokens_output": 0, "api_cost": 0})

    def evaluate(self, checklist: list, facts: dict, evidence_list: list) -> dict:
        logger.info(
            "[AUDIT EVALUATE INPUT] checklist=%s facts=%s evidence=%d",
            checklist,
            list(facts.keys()),
            len(evidence_list or []),
        )

        filled, empty = [], []

        for field_id, v in facts.items():
            val = v.get("value")
            if val and not _is_sentinel_non_fact(str(val)):
                source_type = v.get("source_type", "other")
                weight = self.SOURCE_WEIGHTS.get(source_type, 0.2)
                filled.append({
                    "field": field_id, "label": field_id,
                    "value": v["value"],
                    "source": v.get("source", "unknown"),
                    "source_type": source_type, "weight": weight,
                })
            else:
                empty.append({"field_id": field_id, "label": field_id})

        total = len(facts) if facts else 1
        coverage_pct = len(filled) / total * 100 if total else 0
        weighted_score = sum(f["weight"] for f in filled) / len(filled) * 100 if filled else 0
        source_types_found = set(f["source_type"] for f in filled)
        has_official = any(st in ["datasheet", "pdf", "official_docs", "manual", "spec_table"] for st in source_types_found)
        diversity_bonus = (len(source_types_found) / max(len(filled), 1)) * 20 if len(filled) >= 3 else 0
        combined = (coverage_pct * 0.5) + (weighted_score * 0.3) + diversity_bonus

        # Sufficient = punya cukup fakta DAN sumber beragam ATAU ada sumber resmi
        sufficient = (len(filled) >= 5 and len(source_types_found) >= 2) or has_official

        return {
            "total_fields": total,
            "filled": len(filled), "empty": len(empty),
            "coverage_pct": coverage_pct,
            "weighted_score": weighted_score,
            "has_official_source": has_official,
            "source_types": list(source_types_found),
            "filled_fields": filled, "empty_fields": empty,
            "sufficient": sufficient, "combined_score": combined,
        }
