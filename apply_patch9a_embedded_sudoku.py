"""PATCH 9A: preserve a strict embedded Sudoku grid as transient input.

Run only on the VM:
    cd ~/research-assistant
    python3 apply_patch9a_embedded_sudoku.py
"""
from datetime import datetime
from pathlib import Path
import py_compile
import shutil
import sys

TARGET = Path("hermes_agent/orchestrator.py")

OLD_REQUEST_FACTS = '''        request_facts = {}
        request_facts_lock = threading.Lock()
        semantic_completion_cache = {}'''
NEW_REQUEST_FACTS = '''        request_facts = {}
        # PATCH 9A: input/ facts are request-local and cannot satisfy the
        # req_id/ predicate in request_requirement_complete().
        request_input_facts = {}
        request_facts_lock = threading.Lock()
        semantic_completion_cache = {}'''

OLD_RESEARCH_DEF = '''    def research(self, goal: str, context: str = "", attachments: list | None = None) -> dict:'''
NEW_RESEARCH_DEF = '''    @staticmethod
    def _extract_embedded_sudoku_grid(goal: str) -> str | None:
        """Return a data-only, strict 9x9 Sudoku block, if present."""
        if not isinstance(goal, str) or "sudoku" not in goal.lower():
            return None
        allowed_cells = set("1234567890.")
        rows = []
        for line in goal.splitlines():
            compact = "".join(ch for ch in line.strip() if ch not in " \t|")
            if len(compact) == 9 and all(ch in allowed_cells for ch in compact):
                rows.append(compact)
                if len(rows) == 9:
                    return "\\n".join(rows)
                continue
            if rows:
                stripped = line.strip()
                if stripped and set(stripped) <= set("-|+ \t"):
                    continue
                rows = []
        return None

    def research(self, goal: str, context: str = "", attachments: list | None = None) -> dict:'''

OLD_AFTER_DIRECT = '''
        # KnowledgeGraph is research-only. Direct requests must not acquire
        # the global KG lock.
        kg = KnowledgeGraph()'''
NEW_AFTER_DIRECT = '''
        # PATCH 9A: retain only a canonical grid, never the whole goal.
        # It is intentionally excluded from the attachment early gate, whose
        # successful path can skip web research.
        embedded_user_evidence = []
        embedded_sudoku_grid = self._extract_embedded_sudoku_grid(goal)
        if embedded_sudoku_grid:
            embedded_user_evidence.append({
                "content": embedded_sudoku_grid,
                "source_type": "user_input",
                "evidence_type": "user_input",
                "doc_type": "user_input",
                "url": "user://request",
                "transient": True,
            })
            request_input_facts["input/user_sudoku_grid"] = {
                "value": embedded_sudoku_grid,
                "source": "user://request",
                "source_type": "user_input",
            }
            logger.info(
                "[AUDIT EMBEDDED INPUT] req_id=%s type=sudoku_grid chars=%d",
                req_id,
                len(embedded_sudoku_grid),
            )

        # KnowledgeGraph is research-only. Direct requests must not acquire
        # the global KG lock.
        kg = KnowledgeGraph()'''

OLD_FETCH_STOP = '''                latency.stop("fetch")

                log_event(
                    "fetch_done",'''
NEW_FETCH_STOP = '''                # PATCH 9A: append after normal fetch, before the existing
                # source-policy and relevance gates. Require actual web
                # evidence so an embedded grid cannot replace web research.
                has_web_evidence = any(
                    str(e.get("url", "")).startswith(("http://", "https://"))
                    for e in evidence_for_req
                )
                if has_web_evidence and embedded_user_evidence:
                    for evidence in embedded_user_evidence:
                        evidence_copy = {**evidence, "req_id": req_id}
                        evidence_for_req.append(evidence_copy)
                        all_evidence.append(evidence_copy)
                    logger.info(
                        "[AUDIT EMBEDDED INPUT] req_id=%s decision=APPEND_AFTER_FETCH documents=%d",
                        req_id,
                        len(embedded_user_evidence),
                    )

                latency.stop("fetch")

                log_event(
                    "fetch_done",'''

OLD_RANKED = '''                    # PATCH: simpan seluruh fakta hasil ranking.
                    # Jangan dipotong di level node.
                    ranked = dict(ranked.items())

                    logger.info(
                        "[AUDIT RANKED FACTS] req_id=%s topic=%s count=%d fields=%s",'''
NEW_RANKED = '''                    # PATCH: simpan seluruh fakta hasil ranking.
                    # Jangan dipotong di level node.
                    ranked = dict(ranked.items())

                    # PATCH 9A: user input can reach extraction but cannot be
                    # persisted or satisfy a req_id/ requirement completion.
                    persistent_ranked = {
                        field: fact
                        for field, fact in ranked.items()
                        if isinstance(fact, dict)
                        and str(fact.get("source", "")) != "user://request"
                    }
                    logger.info(
                        "[AUDIT EMBEDDED INPUT] req_id=%s ranked=%d persistent=%d transient=%d",
                        req_id,
                        len(ranked),
                        len(persistent_ranked),
                        len(ranked) - len(persistent_ranked),
                    )

                    logger.info(
                        "[AUDIT RANKED FACTS] req_id=%s topic=%s count=%d fields=%s",'''

OLD_LEARN = '''                    if eval_result["coverage_pct"] >= self.MIN_COVERAGE:
                        kg.learn(req_id, ranked, plan)

                        # Simpan hanya facts hasil extraction run ini.
                        # Historical facts di persistent KG tidak masuk
                        # ke synthesis.
                        with request_facts_lock:
                            for field, fact in ranked.items():
                                if isinstance(fact, dict):
                                    request_facts[f"{req_id}/{field}"] = {
                                        "value": fact.get("value"),
                                        "source": fact.get("source", "unknown"),
                                        "source_type": fact.get("source_type", "other"),
                                    }

                        kg.update_status(req_id, "found")
                    else:
                        kg.update_status(req_id, "partial")'''
NEW_LEARN = '''                    if (
                        eval_result["coverage_pct"] >= self.MIN_COVERAGE
                        and persistent_ranked
                    ):
                        kg.learn(req_id, persistent_ranked, plan)

                        # Only web/non-transient facts may satisfy the
                        # requirement or enter persistent KG. The canonical
                        # grid remains under request_input_facts.
                        with request_facts_lock:
                            for field, fact in persistent_ranked.items():
                                request_facts[f"{req_id}/{field}"] = {
                                    "value": fact.get("value"),
                                    "source": fact.get("source", "unknown"),
                                    "source_type": fact.get("source_type", "other"),
                                }

                        kg.update_status(req_id, "found")
                    else:
                        kg.update_status(req_id, "partial")'''

OLD_ALL_FACTS = '''        all_facts = dict(request_facts)'''
NEW_ALL_FACTS = '''        # PATCH 9A: semantic fulfillment and synthesis see the
        # canonical grid, but it remains outside persistent KG and req_id/.
        all_facts = {**request_facts, **request_input_facts}'''

def replace_once(source, old, new, label):
    count = source.count(old)
    if count != 1:
        raise AssertionError(f"{label}: expected 1 exact match, found {count}")
    return source.replace(old, new, 1)

def main():
    if not TARGET.is_file():
        raise FileNotFoundError(f"Missing target: {TARGET}")
    source = TARGET.read_text(encoding="utf-8")
    backup = TARGET.with_name(
        f"{TARGET.name}.bak.patch9a_{datetime.now():%Y%m%d_%H%M%S}"
    )
    shutil.copy2(TARGET, backup)
    try:
        updated = source
        for old, new, label in (
            (OLD_RESEARCH_DEF, NEW_RESEARCH_DEF, "helper insertion"),
            (OLD_REQUEST_FACTS, NEW_REQUEST_FACTS, "input fact store"),
            (OLD_AFTER_DIRECT, NEW_AFTER_DIRECT, "embedded input setup"),
            (OLD_FETCH_STOP, NEW_FETCH_STOP, "post-fetch injection"),
            (OLD_RANKED, NEW_RANKED, "transient partition"),
            (OLD_LEARN, NEW_LEARN, "persistent learn guard"),
            (OLD_ALL_FACTS, NEW_ALL_FACTS, "final facts merge"),
        ):
            updated = replace_once(updated, old, new, label)
        TARGET.write_text(updated, encoding="utf-8")
        py_compile.compile(str(TARGET), doraise=True)
    except Exception as exc:
        shutil.copy2(backup, TARGET)
        print(f"PATCH 9A FAILED; restored {backup}: {exc}", file=sys.stderr)
        return 1
    print("PATCH 9A APPLIED")
    print(f"backup: {backup}")
    print("py_compile: PASS")
    print("next: python3 patch9a_embedded_user_data_harness.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
