import json
import re
import logging
from collections import Counter

logger = logging.getLogger(__name__)


def extract_json(text: str):
    try:
        return json.loads(text)
    except:
        pass
    for pattern in [r'\{.*\}', r'\[.*\]']:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
    return {}


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
            "timeout",
            "timed out",
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

        prompt = f"""Dari evidence berikut, EKSTRAK SEMUA fakta yang ada.

ATURAN:
1. Ekstrak SEMUA: spesifikasi, perintah, kode, langkah, gejala, penyebab, solusi, tools.
2. Normalisasi key ke snake_case pendek.
3. Abaikan menu/navigasi/footer/copyright.
4. Sertakan source URL DAN source_type.
5. JANGAN mengarang.

EVIDENCE:
{final_evidence}

Return JSON: {{"field_id": {{"value": "nilai", "source": "URL", "source_type": "tipe"}}}}"""

        try:
            result = self.llm.analyze(
                "Kamu universal fact extractor. Ekstrak SEMUA fakta. Normalisasi key ke snake_case.",
                prompt,
                temperature=0.1,
                model="deepseek-chat",
            )

            logger.info("=" * 80)
            logger.info("[RAW EXTRACT RESPONSE]")
            logger.info(result["content"])
            logger.info("=" * 80)
            all_kvs = extract_json(result["content"])

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

                    elif len(item) == 1:
                        k, v = next(iter(item.items()))
                        normalized[k] = v

                all_kvs = normalized

            elif not isinstance(all_kvs, dict):
                all_kvs = {}

            # Provenance guard: fact hanya boleh memakai source URL
            # yang benar-benar ada di evidence yang diberikan ke extractor.
            valid_urls = {
                str(e.get("url", "")).strip()
                for e in all_evidence
                if e.get("url")
            }

            validated = {}
            for key, value in all_kvs.items():
                if not isinstance(value, dict):
                    continue

                src = str(value.get("source", "")).strip()

                if not src or src not in valid_urls:
                    logger.warning(
                        "[FACT REJECT] field=%s source=%r not in evidence",
                        key,
                        src,
                    )
                    continue

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
        filled, empty = [], []

        for field_id, v in facts.items():
            if v.get("value"):
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
