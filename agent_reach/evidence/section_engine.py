import re
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class SectionEngine:
    TS_MARKERS = ("fs", "qts", "qes", "qms", "mms", "cms", " bl ", "vas", "xmax", "dcr", "thiele")

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
            haystack = (s["heading"] + " " + s["text"][:300]).lower()
            has_ts = any(m in haystack for m in self.TS_MARKERS)
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
            # PENTING: cek FULL text, bukan text[:300]. Terbukti dari log
            # nyata -- marker "xmax" bisa duduk di luar 300 karakter
            # pertama (persis di zona yang mau diselamatkan cap ini),
            # window sempit bikin has_ts salah False walau markernya ada.
            haystack_full = (s["heading"] + " " + s["text"]).lower()
            has_ts = any(m in haystack_full for m in self.TS_MARKERS)
            # Section berisi marker Thiele-Small (Fs/Qts/Mms/Xmax/dst) dapat
            # cap lebih besar -- terbukti dari [TRACE XMAX]: section yang
            # LOLOS ranking tetap kehilangan data karena isinya >1000 char.
            # Cap lain (max_sections, max_chars total) TIDAK diubah.
            section_cap = 2000 if has_ts else 1000
            section_text = s["text"][:section_cap]
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
