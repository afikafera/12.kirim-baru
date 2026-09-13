"""
Verification suite for Candidate 1: Evidence Preservation / SectionEngine.
Directly binds to production aran_search.evidence.section_engine.
"""

import os
import sys
import re
import inspect

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from aran_search.evidence.section_engine import SectionEngine

MODULE_FILE = inspect.getfile(SectionEngine)
print(f"[VERIFY RUNNER] Target Module: {MODULE_FILE}")
assert "aran_search" in MODULE_FILE.replace("\\", "/"), f"FATAL: Expected aran_search, got {MODULE_FILE}"


def load_jpl_content():
    possible_paths = [
        os.path.join(REPO_ROOT, "scratch", "jpl_raw.txt"),
        "scratch/jpl_raw.txt",
    ]
    for p in possible_paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read()[:8000]

    try:
        import subprocess
        res = subprocess.run(
            ["curl", "-s", "-L", "https://r.jina.ai/https://ssd.jpl.nasa.gov/planets/phys_par.html"],
            capture_output=True, text=True, timeout=15
        )
        if res.stdout and len(res.stdout) > 800:
            os.makedirs(os.path.join(REPO_ROOT, "scratch"), exist_ok=True)
            cache_path = os.path.join(REPO_ROOT, "scratch", "jpl_raw.txt")
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(res.stdout)
            return res.stdout[:8000]
    except Exception:
        pass

    raise FileNotFoundError("jpl_raw.txt not found and could not be fetched")


def run_tests():
    se = SectionEngine()
    results = []

    # CASE 1: Single-section table (JPL SSD)
    try:
        jpl_8k = load_jpl_content()
        secs = se.split_sections(jpl_8k)
        out = se.rank_and_filter(secs, "mars diameter planetary physical parameters", max_chars=6000)

        has_mars = "Mars" in out and "3396.19" in out
        within_budget = len(out) <= 6000

        lines = [l.strip() for l in out.splitlines() if l.strip()]
        last_table_line = lines[-1] if lines else ""
        clean_row = last_table_line.endswith("|")

        mars_line = next((l for l in lines if "**Mars**" in l), "")
        mars_complete = mars_line.startswith("|") and mars_line.endswith("|")

        passed = has_mars and within_budget and clean_row and mars_complete
        detail = (
            f"Mars in out={has_mars}, len={len(out)}<=6000({within_budget}), "
            f"clean_row={clean_row}, mars_complete={mars_complete}"
        )
        results.append(("CASE 1: single-section table (JPL)", passed, detail))
    except Exception as e:
        results.append(("CASE 1: single-section table (JPL)", False, f"Exception: {e}"))

    # CASE 2: Multi-section narrative
    try:
        content = (
            "# Introduction\n" + ("This is introductory background text about astronomy. " * 30) + "\n\n"
            "# Methodology\n" + ("Here we describe telescope observations and data reduction. " * 30) + "\n\n"
            "# Results\n" + ("The planetary measurements show excellent consistency across runs. " * 30) + "\n\n"
            "# Discussion\n" + ("Implications for atmospheric models and future space exploration. " * 30) + "\n"
        )
        secs = se.split_sections(content)
        out = se.rank_and_filter(secs, "astronomy telescope planetary measurements discussion", max_chars=6000)

        kept_sections = [l for l in out.splitlines() if l.startswith("## ")]
        diverse_kept = len(kept_sections) >= 3
        within_budget = len(out) <= 6000

        section_blocks = out.split("## ")
        section_lens = [len(b) for b in section_blocks if b.strip()]
        all_capped = all(l < 1100 for l in section_lens)

        passed = diverse_kept and within_budget and all_capped
        detail = f"sections_kept={len(kept_sections)}, max_sec_len={max(section_lens) if section_lens else 0}<=1100, total_len={len(out)}"
        results.append(("CASE 2: multi-section narrative", passed, detail))
    except Exception as e:
        results.append(("CASE 2: multi-section narrative", False, f"Exception: {e}"))

    # CASE 3: Multi-section + table
    try:
        table_rows = [f"| Entity_{i:02d} | Measurement_{i*10} km | Density_{i*0.5:.2f} g/cm3 | Status_{i} |" for i in range(40)]
        table_text = "| Name | Value | Density | Status |\n| --- | --- | --- | --- |\n" + "\n".join(table_rows)

        content = (
            "# Project Overview\n" + ("General context and background on stellar survey measurements. " * 15) + "\n\n"
            "# Parameter Table\n" + table_text + "\n\n"
            "# Scientific Analysis\n" + ("Detailed analysis of stellar densities and orbital constraints. " * 15) + "\n"
        )
        secs = se.split_sections(content)
        out = se.rank_and_filter(secs, "parameter table stellar survey measurements", max_chars=6000)

        has_intro = "Project Overview" in out
        has_table = "Parameter Table" in out
        has_analysis = "Scientific Analysis" in out
        within_budget = len(out) <= 6000

        table_part = ""
        for block in out.split("## "):
            if block.startswith("Parameter Table"):
                table_part = block
                break

        table_lines = [l.strip() for l in table_part.splitlines() if l.strip() and "|" in l]
        table_clean = len(table_lines) > 2 and table_lines[-1].endswith("|")
        table_capped = len(table_part) <= 1150

        passed = has_intro and has_table and has_analysis and within_budget and table_clean and table_capped
        detail = (
            f"sections: intro={has_intro}, table={has_table}, analysis={has_analysis}, "
            f"table_clean={table_clean}, table_len={len(table_part)}<=1150, total={len(out)}"
        )
        results.append(("CASE 3: multi-section + table", passed, detail))
    except Exception as e:
        results.append(("CASE 3: multi-section + table", False, f"Exception: {e}"))

    # CASE 4: Table larger than budget
    try:
        rows = [f"| Planet_{i:02d} | ParamA_{i*111} | ParamB_{i*222} | ParamC_{i*333} | LongDescription_{i:02d}_filler_text_padding |" for i in range(50)]
        table_content = "| Planet | Param A | Param B | Param C | Notes |\n| --- | --- | --- | --- | --- |\n" + "\n".join(rows)

        secs = se.split_sections(table_content)
        budget = 1500
        out = se.rank_and_filter(secs, "planet parameters", max_chars=budget)

        within_budget = len(out) <= budget
        lines = [l.strip() for l in out.splitlines() if l.strip() and "|" in l]
        header_preserved = len(lines) >= 2 and "| Planet |" in lines[0] and "---" in lines[1]
        last_row = lines[-1] if lines else ""
        clean_row_end = last_row.startswith("|") and last_row.endswith("|")
        no_mid_row_cut = not any(l.endswith("ParamA_") or l.endswith("filler_") for l in lines)

        passed = within_budget and header_preserved and clean_row_end and no_mid_row_cut
        detail = f"len={len(out)}<={budget}, header={header_preserved}, clean_end={clean_row_end}, no_mid_cut={no_mid_row_cut}"
        results.append(("CASE 4: table larger than budget", passed, detail))
    except Exception as e:
        results.append(("CASE 4: table larger than budget", False, f"Exception: {e}"))

    # CASE 5: No table (existing truncation behavior preserved)
    try:
        narrative = "Standard narrative article without any tables. " * 60
        secs = se.split_sections(narrative)
        out = se.rank_and_filter(secs, "standard narrative article", max_chars=6000)

        out_body = out.replace("## \n", "").replace("## \r\n", "")
        is_capped_1000 = len(out_body) == 1000
        matches_prefix = out_body == narrative[:1000]

        passed = is_capped_1000 and matches_prefix
        detail = f"out_body_len={len(out_body)}==1000({is_capped_1000}), prefix_match={matches_prefix}"
        results.append(("CASE 5: no table (existing cap 1000 preserved)", passed, detail))
    except Exception as e:
        results.append(("CASE 5: no table (existing cap 1000 preserved)", False, f"Exception: {e}"))

    # CASE 6: URL #refs (has_ts MUST NOT become True merely because of 'fs')
    try:
        ref_text = (
            "URL Source: https://ssd.jpl.nasa.gov/planets/phys_par.html#refs\n"
            "See the references section for further details. The method itself has tariffs applied."
        )
        if hasattr(se, "_has_ts_marker"):
            has_ts = se._has_ts_marker(ref_text)
        else:
            haystack = ref_text.lower()
            has_ts = any(m in haystack for m in se.TS_MARKERS)

        passed = (has_ts is False)
        detail = f"has_ts={has_ts} (must be False for #refs/references/itself/tariffs)"
        results.append(("CASE 6: URL #refs false positive guard", passed, detail))
    except Exception as e:
        results.append(("CASE 6: URL #refs false positive guard", False, f"Exception: {e}"))

    # CASE 7: Legitimate Thiele-Small/audio document (has_ts MUST remain True)
    try:
        audio_texts = [
            "Subwoofer Specifications: Fs: 32 Hz, Qts: 0.38, Vas: 55 L, Xmax: 5.65 mm",
            "Speaker drivers: Fs = 45.2 Hz, Qms = 3.8, Qes = 0.42, Mms = 22 g",
            "Thiele-Small parameters: bl: 12.5, dcr: 3.4 ohm, cms: 0.35 mm/N",
        ]
        all_detected = True
        for at in audio_texts:
            if hasattr(se, "_has_ts_marker"):
                detected = se._has_ts_marker(at)
            else:
                detected = any(m in at.lower() for m in se.TS_MARKERS)
            if not detected:
                all_detected = False
                break

        passed = all_detected
        detail = f"all_audio_specs_detected={all_detected} (must be True for Fs/Qts/Vas/Xmax/BL/dst)"
        results.append(("CASE 7: legitimate Thiele-Small spec detection", passed, detail))
    except Exception as e:
        results.append(("CASE 7: legitimate Thiele-Small spec detection", False, f"Exception: {e}"))

    print("\n" + "=" * 80)
    print(" CANDIDATE 1 VERIFICATION RESULTS: TABLE PRESERVATION & TS MARKERS")
    print("=" * 80)
    all_pass = True
    for name, passed, detail in results:
        status = "[PASS]" if passed else "[FAIL]"
        if not passed:
            all_pass = False
        print(f" {status} {name}")
        print(f"        -> {detail}")
    print("=" * 80)
    print(f" TOTAL: {sum(1 for _, p, _ in results if p)}/{len(results)} PASSED")
    print("=" * 80 + "\n")
    return all_pass


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
