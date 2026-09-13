import re
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

TABLE_SEP = re.compile(r'^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$')


def _has_markdown_table(text: str) -> bool:
    return any(TABLE_SEP.match(line) for line in text.splitlines())


def _truncate_preserving_table(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text

    if not _has_markdown_table(text):
        return text[:cap]

    lines = text.splitlines(keepends=True)
    kept = []
    current_len = 0
    for line in lines:
        if current_len + len(line) <= cap:
            kept.append(line)
            current_len += len(line)
        else:
            break

    result = "".join(kept).rstrip()
    return result if result else text[:cap]


class SectionEngine:
    TS_MARKERS = ("fs", "qts", "qes", "qms", "mms", "cms", " bl ", "vas", "xmax", "dcr", "thiele")
    TS_PATTERNS = (
        re.compile(r'\b(fs|qts|qes|qms|mms|cms|vas|xmax|dcr|thiele)\b', re.IGNORECASE),
        re.compile(r'\bbl\b', re.IGNORECASE),
    )

    def _has_ts_marker(self, text: str) -> bool:
        return any(p.search(text) for p in self.TS_PATTERNS)

    HEADING = re.compile(r'^#{1,4}\s+(.+)$', re.MULTILINE)
    KV_LINE = re.compile(r'^([A-Za-z][\w\s/()-]{2,40})[:\s]{2,}(.+)$', re.MULTILINE)
    BOILERPLATE = {"menu", "navigation", "footer", "copyright", "all rights reserved",
        "home", "products", "news", "about us", "contact", "catalogue",
        "agents", "download the app", "follow us", "other brands", "showroom", "main office"}

    def split_sections(self, content: str) -> list:
        sections = []
        matches = list(self.HEADING.finditer(content))
        if not matches:
            return [{"heading": "", "text": content, "kvs": dict(self.KV_LINE.findall(content))}]
        for i, match in enumerate(matches):
            heading = match.group(1)
            start = match.end()
            end = matches[i+1].start() if i+1 < len(matches) else len(content)
            text = content[start:end].strip()
            kvs = dict(self.KV_LINE.findall(text))
            sections.append({"heading": heading, "text": text, "kvs": kvs})
        return sections

    def is_boilerplate(self, heading: str, text: str) -> bool:
        combined = (heading + " " + text[:200]).lower()
        return any(bp in combined for bp in self.BOILERPLATE)

    def score_section(self, heading: str, text: str, kvs: dict, query: str) -> float:
        score = 0.0
        q = query.lower()
        h = heading.lower()
        t = text[:500].lower()
        score += SequenceMatcher(None, h, q).ratio() * 0.4
        for term in q.split():
            if len(term) > 2 and term in h:
                score += 0.15
        score += SequenceMatcher(None, t, q).ratio() * 0.2
        score += min(len(kvs) * 0.02, 0.2)
        return min(score, 1.0)

    def rank_and_filter(self, sections: list, query: str, max_sections: int = 8, max_chars: int = 6000) -> str:
        relevant = [s for s in sections if not self.is_boilerplate(s["heading"], s["text"])]
        scored = [(self.score_section(s["heading"], s["text"], s["kvs"], query), s) for s in relevant]
        scored.sort(key=lambda x: x[0], reverse=True)

        for score, s in scored:
            haystack = (s["heading"] + " " + s["text"]).lower()
            has_ts = self._has_ts_marker(haystack)
            has_xmax = "xmax" in s["text"].lower() or "5.65" in s["text"]
            logger.info(
                "[AUDIT SECTION] heading=%r score=%.3f kvs=%d text_len=%d ts_marker=%s has_xmax=%s",
                s["heading"][:60], score, len(s["kvs"]), len(s["text"]), has_ts, has_xmax,
            )

        output = []
        total_chars = 0
        all_kvs = {}
        for score, s in scored:
            if score < 0.05 and len(output) > 0: break
            haystack_full = (s["heading"] + " " + s["text"]).lower()
            has_ts = self._has_ts_marker(haystack_full)
            is_single_table = len(scored) == 1 and _has_markdown_table(s["text"])
            if is_single_table:
                # Single section with markdown table gets budget up to max_chars
                # (reserving headroom for specifications KVs, bounded by 5000 source cap)
                headroom = 400 if s["kvs"] else 50
                section_cap = min(max_chars - headroom, 5000)
            elif has_ts:
                # Section berisi marker Thiele-Small (Fs/Qts/Mms/Xmax/dst) dapat
                # cap lebih besar (2000)
                section_cap = 2000
            else:
                section_cap = 1000
            section_text = _truncate_preserving_table(s["text"], section_cap)
            output.append(f"## {s['heading']}\n{section_text}")
            all_kvs.update(s["kvs"])
            total_chars += len(section_text)
            if len(output) >= max_sections or total_chars >= max_chars: break
        if all_kvs:
            kv_text = "\n".join([f"{k}: {v}" for k, v in list(all_kvs.items())[:30]])
            output.insert(0, f"## Specifications\n{kv_text}")

        kept_headings = [s["heading"][:40] for _, s in scored[:len(output)]]
        final_text = "\n\n".join(output)
        logger.info(
            "[AUDIT SECTION SUMMARY] total=%d kept=%d kept_headings=%s all_kvs_keys=%s xmax_in_output=%s",
            len(scored), len(output), kept_headings, list(all_kvs.keys())[:20],
            ("xmax" in final_text.lower() or "5.65" in final_text),
        )
        return final_text
