"""
APPLY diagnostic logging for doc_type classification -- audit only, no
logic change to Classifier or any decision-making code.

Purpose: prove definitively (not by manual regex tracing on old traces)
whether Classifier.classify()'s kvs >= 8 branch is what tags a given URL
as "datasheet" -- specifically for the BigGo and Tokopedia sources found
in the trace-4ad156f37f494b6e8deca27eb1f61a8d.json audit. Follows the
exact same pattern already used in this file for the prior "[TRACE XMAX]"
audit (additive log line, no behavior change), generalized to fire on
every DocumentIntelligence.process() call instead of only when an
xmax/5.65 marker is present.

Changes (two files, both purely additive):

1. aran_search/evidence/__init__.py
   - process() gains an optional `url: str = ""` parameter (backward
     compatible -- any other caller that doesn't pass url still works
     identically, defaulting to "").
   - One new log.info() line: [AUDIT DOCTYPE] url=... doc_type=...
     kvs=... normalized_len=...
   - kv_count is computed by calling the classifier's OWN existing
     compiled regex (self.classifier.KV_LINE.findall(normalized)) --
     not a reimplementation, so there is zero risk of the diagnostic
     count drifting from what classify() itself actually evaluated.
   - Classifier.classify() itself is NOT touched at all.

2. hermes_agent/orchestrator.py
   - The single production call site (_fetch_url_parallel) now passes
     url=url through to docintel.process(), so the new log line can
     identify which source produced which doc_type. No other change to
     that function.

Safety:
  - Timestamped backup of both files before writing anything.
  - Exact-match count == 1 assertion for each changed block; aborts
    with no changes written if either file has drifted from what was
    audited.
  - py_compile on both files, with automatic rollback of both on any
    failure (all-or-nothing for this one small change).

Run ON THE SERVER:
    cd ~/research-assistant
    python3 apply_doctype_diagnostic_logging.py
"""
import datetime
import py_compile
import shutil
import sys

DOCINTEL_TARGET = "aran_search/evidence/__init__.py"
ORCH_TARGET = "hermes_agent/orchestrator.py"


def main():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    with open(DOCINTEL_TARGET, "r", encoding="utf-8") as f:
        docintel_src = f.read()
    with open(ORCH_TARGET, "r", encoding="utf-8") as f:
        orch_src = f.read()

    docintel_backup = f"{DOCINTEL_TARGET}.bak_doctype_diag_{timestamp}"
    orch_backup = f"{ORCH_TARGET}.bak_doctype_diag_{timestamp}"
    shutil.copy2(DOCINTEL_TARGET, docintel_backup)
    shutil.copy2(ORCH_TARGET, orch_backup)
    print(f"[backup] {DOCINTEL_TARGET} -> {docintel_backup}")
    print(f"[backup] {ORCH_TARGET} -> {orch_backup}")

    # -----------------------------------------------------------------
    # FIX 1: aran_search/evidence/__init__.py -- add diagnostic log line
    # -----------------------------------------------------------------
    old_process = '''    def process(self, raw_content: str, query: str) -> dict:
        if not raw_content:
            return {"formatted": "", "doc_type": "unknown", "sections": 0}
        normalized = self.normalizer.normalize(raw_content)
        doc_type = self.classifier.classify(normalized)
        all_sections = self.sections.split_sections(normalized)
        formatted = self.sections.rank_and_filter(all_sections, query)'''

    new_process = '''    def process(self, raw_content: str, query: str, url: str = "") -> dict:
        if not raw_content:
            return {"formatted": "", "doc_type": "unknown", "sections": 0}
        normalized = self.normalizer.normalize(raw_content)
        doc_type = self.classifier.classify(normalized)
        kv_count = len(self.classifier.KV_LINE.findall(normalized))
        logger.info(
            "[AUDIT DOCTYPE] url=%s doc_type=%s kvs=%d normalized_len=%d",
            url, doc_type, kv_count, len(normalized),
        )
        all_sections = self.sections.split_sections(normalized)
        formatted = self.sections.rank_and_filter(all_sections, query)'''

    count = docintel_src.count(old_process)
    assert count == 1, f"FIX 1: expected exactly 1 match for process() header, found {count}. Aborting, no changes written."
    docintel_src = docintel_src.replace(old_process, new_process)
    print("[fix 1] [AUDIT DOCTYPE] log line added to DocumentIntelligence.process()")

    # -----------------------------------------------------------------
    # FIX 2: hermes_agent/orchestrator.py -- pass url through
    # -----------------------------------------------------------------
    old_call = '''            if raw and len(raw) > 50:
                processed = self.docintel.process(raw, query)'''

    new_call = '''            if raw and len(raw) > 50:
                processed = self.docintel.process(raw, query, url=url)'''

    count = orch_src.count(old_call)
    assert count == 1, f"FIX 2: expected exactly 1 match for docintel.process() call, found {count}. Aborting, no changes written."
    orch_src = orch_src.replace(old_call, new_call)
    print("[fix 2] url passed through to docintel.process() in _fetch_url_parallel")

    with open(DOCINTEL_TARGET, "w", encoding="utf-8") as f:
        f.write(docintel_src)
    with open(ORCH_TARGET, "w", encoding="utf-8") as f:
        f.write(orch_src)
    print(f"[write] {DOCINTEL_TARGET} updated")
    print(f"[write] {ORCH_TARGET} updated")

    try:
        py_compile.compile(DOCINTEL_TARGET, doraise=True)
        print(f"[py_compile] OK: {DOCINTEL_TARGET}")
        py_compile.compile(ORCH_TARGET, doraise=True)
        print(f"[py_compile] OK: {ORCH_TARGET}")
    except py_compile.PyCompileError as e:
        print(f"[py_compile] FAILED: {e}")
        print(f"[rollback] restoring backups")
        shutil.copy2(docintel_backup, DOCINTEL_TARGET)
        shutil.copy2(orch_backup, ORCH_TARGET)
        sys.exit(1)

    print("")
    print("Diagnostic logging applied successfully (audit-only, no logic change).")
    print(f"Backups kept at:")
    print(f"  {docintel_backup}")
    print(f"  {orch_backup}")
    print("")
    print("Next: diff both files against their backups, restart the service,")
    print("then run ONE controlled test query that fetches the BigGo and/or")
    print("Tokopedia URLs (e.g. re-run the same ACR 12500 Black ported box")
    print("query), and grep server.log for:")
    print("  grep '\\[AUDIT DOCTYPE\\]' server.log")
    print("to see url / doc_type / kvs / normalized_len for each source.")


if __name__ == "__main__":
    main()
