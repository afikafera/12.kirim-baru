"""
PATCH1 numeric-fidelity gate -- Step 2: numeric classification harness.

Design (agreed 2026-09-08): separate NUMERIC FIDELITY classification from
CONTEXT DISAMBIGUATION. This script implements and tests ONLY the
classifier -- it does NOT decide accept/reject, and it is NOT wired into
fact_checker.py. That wiring (and whether/how AMBIGUOUS ever gets
resolved by a later context-aware layer) is a separate, later decision.

classify_value_support() returns one of four states per fact value:
    EXACT                 -- the extracted value appears verbatim in the
                              source (identical to OLD's current check).
    UNAMBIGUOUS_NORMALIZED -- the value does not appear verbatim, but a
                              numeric token in the source can be parsed
                              into EXACTLY ONE valid interpretation
                              (multi-separator grouping, mixed separator
                              types, or a separator whose trailing group
                              is not exactly 3 digits) and that
                              interpretation equals the extracted value.
    AMBIGUOUS              -- a numeric token in the source has the
                              classic irreducible shape (exactly one
                              separator, exactly 3 trailing digits) whose
                              THOUSANDS reading matches the extracted
                              value, but the DECIMAL reading is equally
                              valid syntactically and cannot be ruled out
                              from the number's shape alone.
    MISMATCH               -- no source token, under any reading,
                              supports the extracted value at all
                              (the original PATCH1 case: fabricated
                              values). Fail-closed, same spirit as OLD.

For a value containing multiple numbers (e.g. "exchange_prices" listing
several prices), the overall classification is the WORST of all its
numbers' classifications (MISMATCH < AMBIGUOUS < UNAMBIGUOUS_NORMALIZED
< EXACT), mirroring OLD's `all(num in haystack for num in numbers)`
fail-closed combination.

Run (no server/production import needed -- this is standalone new code,
not yet wired into fact_checker.py):
    python3 patch1_step2_classifier_harness.py
"""
import re


_CANDIDATE_NUM_PATTERN = re.compile(r'\d+(?:[.,]\d+)?')  # same as OLD's _NUM_PATTERN

# BUGFIX (2026-09-08, after live Step 2 run): the (?!\d) lookahead after
# each 3-digit group prevents the first alternative from greedily eating
# only the first 3 digits of a LONGER digit run (e.g. it used to split
# "0,0058" into "0,005"+"8" instead of recognizing the whole thing as one
# 4-digit-fraction decimal token). Without this guard, a group is only
# accepted if it is genuinely a complete, standalone 3-digit group.
_SOURCE_TOKEN_PATTERN = re.compile(
    r'\d{1,3}(?:[.,]\d{3}(?!\d))+(?:[.,]\d+)?|\d+(?:[.,]\d+)?'
)

EXACT = "EXACT"
UNAMBIGUOUS_NORMALIZED = "UNAMBIGUOUS_NORMALIZED"
AMBIGUOUS = "AMBIGUOUS"
MISMATCH = "MISMATCH"

_RANK = {MISMATCH: 0, AMBIGUOUS: 1, UNAMBIGUOUS_NORMALIZED: 2, EXACT: 3}


def _parse_candidate_number(token: str):
    v = token.strip().rstrip('%')
    v = re.sub(r'[TMBK]$', '', v, flags=re.IGNORECASE)
    v = v.replace(',', '')
    try:
        return float(v)
    except ValueError:
        return None


def _classify_source_token(token: str):
    """Return a list of 1 or 2 float readings for one raw source token.
    2 readings => the ambiguous (thousands vs 3-decimal) case."""
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
            # mixed separators (e.g. "78.378,18") -> unambiguous:
            # earlier separator(s) = grouping, LAST separator = decimal.
            int_part = "".join(groups[:-1])
            try:
                return [float(f"{int_part}.{groups[-1]}")]
            except ValueError:
                return []
        if all(len(g) == 3 for g in groups[1:]):
            # uniform thousands grouping (e.g. "1,507,904")
            try:
                return [float("".join(groups))]
            except ValueError:
                return []
        # same separator repeated but not uniform 3-digit groups ->
        # best-effort: last group is decimal, rest is integer part.
        int_part = "".join(groups[:-1])
        try:
            return [float(f"{int_part}.{groups[-1]}")]
        except ValueError:
            return []

    # exactly one separator
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


def classify_number_support(candidate_number: str, source_content: str) -> str:
    haystack = source_content or ""
    cand_str = candidate_number.strip()

    if cand_str and cand_str in haystack:
        return EXACT

    cand_f = _parse_candidate_number(cand_str)
    if cand_f is None:
        return EXACT  # non-numeric token slipped in; not this classifier's concern

    best = MISMATCH
    for token in _SOURCE_TOKEN_PATTERN.findall(haystack):
        readings = _classify_source_token(token)
        if not readings:
            continue
        if len(readings) == 1:
            if abs(readings[0] - cand_f) < 1e-9 and _RANK[UNAMBIGUOUS_NORMALIZED] > _RANK[best]:
                best = UNAMBIGUOUS_NORMALIZED
        else:
            if any(abs(r - cand_f) < 1e-9 for r in readings) and _RANK[AMBIGUOUS] > _RANK[best]:
                best = AMBIGUOUS
    return best


def classify_value_support(value: str, source_content: str) -> str:
    """Combine per-number classification for a (possibly multi-number)
    value string. Empty/non-numeric value -> EXACT (fidelity check N/A,
    mirrors OLD's `if not numbers: return True`)."""
    numbers = _CANDIDATE_NUM_PATTERN.findall(value or "")
    if not numbers:
        return EXACT

    worst = EXACT
    for num in numbers:
        cls = classify_number_support(num, source_content)
        if _RANK[cls] < _RANK[worst]:
            worst = cls
    return worst


# ---------------------------------------------------------------------
# TEST MATRIX A: abstract classification-shape cases (from the 2026-09-08
# design discussion) -- proves the CLASSIFIER's shape-detection logic in
# isolation, decoupled from any real trace.
# ---------------------------------------------------------------------
ABSTRACT_CASES = [
    # (label, candidate_value, source_snippet, expected_class)
    ("mixed_sep",        "78378.18", "78.378,18", UNAMBIGUOUS_NORMALIZED),
    ("single_sep_2dig",  "3.13",     "3,13",      UNAMBIGUOUS_NORMALIZED),
    ("multi_group",      "1507904",  "1,507,904", UNAMBIGUOUS_NORMALIZED),
    ("single_sep_2dig_pct", "0.70",  "0,70%",     UNAMBIGUOUS_NORMALIZED),

    ("ambiguous_dot_short",  "78347", "78.347",  AMBIGUOUS),
    ("ambiguous_comma_3dig", "966030","966,030", AMBIGUOUS),
    ("ambiguous_dot_1234",   "1234",  "1.234",   AMBIGUOUS),
    ("ambiguous_comma_1234", "1234",  "1,234",   AMBIGUOUS),

    ("exact_literal_1234",   "1.234", "1.234",   EXACT),
    ("candidate_has_comma",  "1,234", "1.234",   AMBIGUOUS),

    ("real_mismatch",        "78347", "78348",   MISMATCH),
    ("fabricated_no_digits", "12",    "no numbers here at all", MISMATCH),

    # Regression test for the 2026-09-08 tokenizer bug: a 4+ digit
    # fractional part must NOT be chopped into a false 3-digit group.
    ("multi_digit_fraction", "0.0058", "Funding Rate: 0,0058%", UNAMBIGUOUS_NORMALIZED),
]

# ---------------------------------------------------------------------
# TEST MATRIX B: the 22 real fields from live trace
# 01f3a9ee80d71aafc971ec5b6543daa8 (TradingView + CoinDesk, BTC),
# re-classified with the new 4-state classifier instead of OLD's binary
# gate, to show exactly how many are rescued now vs still need Step 3.
# ---------------------------------------------------------------------
TRACE_CASES = [
    ("current_price_usd", "78347", "Harga Bitcoin (BTC) saat ini adalah: 78.347 USD"),
    ("price_change_24h_percent", "-0.94", "telah turun sebesar -0,94% dalam 24 jam terakhir"),
    ("price_change_7d_percent", "0.25", "Harga Bitcoin telah naik sebesar: 0,25"),
    ("price_change_1y_percent", "-29.54", "Bitcoin mengalami penurunan sebesar: -29,54"),
    ("market_cap_usd", "1.57T", "Kapitalisasi pasar: 1,57 T USD"),
    ("fully_diluted_market_cap_usd", "1.64T", "Cap Pasar Terdilusi Sepenuhnya: 1,64 T USD"),
    ("circulating_supply", "20.08M", "Suplai sirkulasi: 20,08 M"),
    ("max_supply", "21.00M", "Suplai maksimum: 21,00 M"),
    ("total_supply", "20.08M", "Total suplai: 20,08 M"),
    ("open_interest_usd", "26.41B", "Minat terbuka 26,41 B USD 0,93%"),
    ("liquidations_24h_usd", "21.88M", "Likuidasi (24h) 21,88 M USD"),
    ("funding_rate_percent", "0.0058", "Funding Rate: 0,0058%"),
    ("trading_volume_24h_usd", "23.40B", "volume trading Bitcoin (BTC) dalam 24 jam adalah 23,40 B USD"),
    ("price_change_1m_percent", "21.36", "kinerja bulannya menunjukkan peningkatan sebesar 21,36 %"),
    ("price_usd_coindesk", "78378.18", "Bitcoin BTC #1 $78.378,18 Turun 1,35 persen"),
    ("block_number", "966030", "Nomor Blok 966,030"),
    ("block_reward", "3.13", "Hadiah Blok 3,13"),
    ("last_block_size", "1507904", "Ukuran Blok Terakhir 1,507,904"),
    ("volume_to_market_cap_ratio_24h_percent_coindesk", "0.70", "Vol/Kap. Pasar (24j) 0,70%"),
    ("exchange_prices",
     "Binance: 78389.16 USDT (-1.31%), Bybit: 78391.60 USDT (-1.31%), Gateio: 78396.80 USDT, Okex: 78388.80 USDT, Bullish: 78360.07 USDC (-1.36%)",
     "BTC-USDT BTCUSDT Binance AA : 78.389,16 USDT: -1,31% BTC-USDT BTCUSDT Bybit A : 78.391,60 BTC-USDT BTC_USDT Gateio A : 78.396,80 BTC-USDT BTC-USDT Okex A : 78.388,80 BTC-USDC BTCUSDC Bullish AA : 78.360,07 USDC: -1,36%"),
    # already-surviving sanity controls (English-formatted stat box)
    ("market_cap_usd_coindesk", "1.57T", "Kapitalisasi Pasar $1.57T Turun 1,35 persen"),
    ("total_supply_coindesk", "20.08M BTC", "Total Pasokan 20.08M BTC"),
    # negative control: fabricated, must stay MISMATCH
    ("fabricated_port_width", "12-inch", "This enclosure ships in three trim colors and a padded travel case."),
]


def run_matrix(title, cases, has_expected):
    print("=" * 100)
    print(title)
    print("=" * 100)
    counts = {}
    for row in cases:
        if has_expected:
            label, value, source, expected = row
        else:
            label, value, source = row
            expected = None
        result = classify_value_support(value, source)
        counts[result] = counts.get(result, 0) + 1
        mark = ""
        if expected is not None:
            mark = "ok" if result == expected else f"MISMATCH-vs-expected(exp={expected})"
        print(f"{label:52s} {value[:30]:30s} -> {result:24s} {mark}")
    print("-" * 100)
    print("Distribution:", counts)
    print()


if __name__ == "__main__":
    run_matrix("MATRIX A: abstract classification-shape cases", ABSTRACT_CASES, has_expected=True)
    run_matrix("MATRIX B: real trace 01f3a9ee80d71aafc971ec5b6543daa8 fields (no expected -- observe distribution)", TRACE_CASES, has_expected=False)
