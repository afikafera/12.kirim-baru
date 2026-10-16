import re
import math
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

    CODE_DECL_BLOCK = re.compile(
        r'^[ \t]{0,8}(?:(?:@\w+|#\[)[^\n]*\n[ \t]{0,8})*'
        r'(?:(?:public|private|protected|internal|static|final|abstract|synchronized|async|export|default|pub(?:\([^)]*\))?)\s+)*'
        r'(?:(?:def|class|function|fn|struct|interface|trait|enum|impl)\s+[A-Za-z_]\w*'
        r'|func\s+(?:\([^)]+\)\s*)?[A-Za-z_]\w*'
        r'|type\s+[A-Za-z_]\w*\s+(?:struct|interface))[^\n]*',
        re.MULTILINE,
    )
    CODE_STOPWORDS = {
        "the", "and", "for", "from", "with", "within", "into", "that", "this",
        "what", "how", "why", "determine", "extract", "explain", "specific",
        "details", "function", "method", "file", "code", "source", "implementation",
        "specified", "exact", "sequence", "order", "logic", "handling", "paths",
        "ambil", "dari", "dan", "yang", "pada", "untuk", "dalam", "fungsi",
        "bagaimana", "jelaskan", "berdasarkan", "isi", "hanya", "fokus", "buka",
        "langsung", "ini", "tersebut", "benar", "terbaca", "fakta", "terverifikasi",
        "urutan", "jalur", "serta", "diproses", "oleh", "cari",
        "self", "return", "import", "none", "true", "false", "str", "int", "dict", "list",
        "https", "http", "com", "blob", "master", "main",
    }

    @classmethod
    def _extract_code_tokens(cls, text: str) -> set:
        raw_tokens = re.findall(r'[A-Za-z0-9_]{3,}', text)
        tokens = set()
        for tok in raw_tokens:
            low = tok.lower()
            if low not in cls.CODE_STOPWORDS:
                tokens.add(low)
            parts = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', tok).lower().split('_')
            for p in parts:
                if len(p) >= 3 and p not in cls.CODE_STOPWORDS:
                    tokens.add(p)
        return tokens

    def _split_code_sections(self, content: str, cap: int = 1000) -> list:
        matches = list(self.CODE_DECL_BLOCK.finditer(content))
        if not matches:
            raw_blocks = [("module_body", content.strip())]
        else:
            raw_blocks = []
            if matches[0].start() > 0:
                pre = content[:matches[0].start()].strip()
                if pre:
                    raw_blocks.append(("module_header", pre))
            for i, m in enumerate(matches):
                start = m.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
                block = content[start:end].strip()
                heading = m.group(0).strip().splitlines()[-1].strip()
                raw_blocks.append((heading, block))

        sections = []
        for heading, block in raw_blocks:
            if len(block) <= cap:
                sections.append({
                    "heading": heading,
                    "text": block,
                    "kvs": {},
                    "parent_heading": heading,
                    "part_index": 1,
                    "part_total": 1,
                })
            else:
                paragraphs = re.split(r'\n\s*\n', block)
                chunks = []
                cur = []
                cur_len = 0
                for p in paragraphs:
                    p = p.strip("\n")
                    if not p:
                        continue
                    paragraph_parts = []
                    if len(p) <= cap:
                        paragraph_parts.append(p)
                    else:
                        part = ""
                        for line in p.splitlines(keepends=True):
                            remaining = line
                            while remaining:
                                room = cap - len(part)
                                part += remaining[:room]
                                remaining = remaining[room:]
                                if len(part) == cap:
                                    paragraph_parts.append(part)
                                    part = ""
                        if part:
                            paragraph_parts.append(part)

                    for paragraph_part in paragraph_parts:
                        separator_len = 2 if cur else 0
                        if cur and cur_len + separator_len + len(paragraph_part) > cap:
                            chunks.append("\n\n".join(cur))
                            cur = []
                            cur_len = 0
                            separator_len = 0
                        cur.append(paragraph_part)
                        cur_len += separator_len + len(paragraph_part)
                        if cur_len == cap:
                            chunks.append("\n\n".join(cur))
                            cur = []
                            cur_len = 0
                if cur:
                    chunks.append("\n\n".join(cur))
                total_parts = len(chunks)
                for idx, chunk_text in enumerate(chunks, 1):
                    first_line = chunk_text.splitlines()[0].strip()[:60]
                    sec_heading = heading if idx == 1 else f"{heading} :: {first_line}"
                    sections.append({
                        "heading": sec_heading,
                        "text": chunk_text,
                        "kvs": {},
                        "parent_heading": heading,
                        "part_index": idx,
                        "part_total": total_parts,
                    })
        return sections

    def split_sections(self, content: str, doc_type: str = "general") -> list:
        if doc_type == "source_code":
            return self._split_code_sections(content)
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

    def _rank_and_filter_code(self, sections: list, query: str, max_sections: int = 8, max_chars: int = 4950) -> str:
        q_clean = re.sub(r'https?://\S+', ' ', query)
        q_clean = re.sub(
            r'\b[\w./-]+\.(?:py|pyi|js|mjs|cjs|ts|tsx|jsx|go|rs|java|c|cc|cpp|cxx|h|hpp|cs|rb|php|sh|bash|zsh|kt|kts|swift|scala|lua|pl|r|sql|zig|ex|exs|erl|hs)\b',
            ' ',
            q_clean,
        )
        q_tokens = self._extract_code_tokens(q_clean)
        if not q_tokens:
            q_tokens = self._extract_code_tokens(query)

        n_secs = max(1, len(sections))
        sec_h_tokens = []
        sec_t_tokens = []
        df = {}
        for s in sections:
            ht = self._extract_code_tokens(s.get("parent_heading", s["heading"]))
            tt = self._extract_code_tokens(s["heading"] + "\n" + s["text"])
            sec_h_tokens.append(ht)
            sec_t_tokens.append(tt)
            for tok in (ht | tt):
                df[tok] = df.get(tok, 0) + 1

        scored = []
        for idx, s in enumerate(sections):
            ht = sec_h_tokens[idx]
            tt = sec_t_tokens[idx]
            score = 0.0
            matched_in_parent = False
            for tok in q_tokens:
                idf = math.log(1.0 + n_secs / (1.0 + df.get(tok, 0)))
                weight = 1.4 if "_" in tok else 1.0
                if tok in ht:
                    score += 0.30 * idf * weight
                    if "_" in tok or idf > 1.5:
                        matched_in_parent = True
                if tok in tt:
                    score += 0.20 * idf * weight

            part_idx = s.get("part_index", 1)
            part_total = s.get("part_total", 1)
            if matched_in_parent:
                if part_idx == 1:
                    score += 1.50
                elif part_total > 2 and part_idx >= part_total - 1:
                    score += 0.35
            scored.append((score, idx, s))

        scored.sort(key=lambda x: x[0], reverse=True)

        for score, _, s in scored:
            logger.info(
                "[AUDIT SECTION] heading=%r score=%.3f kvs=0 text_len=%d ts_marker=False has_xmax=False",
                s["heading"][:60], score, len(s["text"]),
            )

        chosen = []
        total_chars = 0
        for score, idx, s in scored:
            if score < 0.05 and chosen:
                break
            sec_text = _truncate_preserving_table(s["text"], 1100)
            entry = f"## {s['heading']}\n{sec_text}"
            if total_chars + len(entry) > max_chars and chosen:
                break
            chosen.append((idx, score, s["heading"], entry))
            total_chars += len(entry) + 2
            if len(chosen) >= max_sections:
                break

        chosen.sort(key=lambda x: x[0])
        kept_headings = [h[:40] for _, _, h, _ in chosen]
        final_text = "\n\n".join(entry for _, _, _, entry in chosen)
        logger.info(
            "[AUDIT SECTION SUMMARY] total=%d kept=%d kept_headings=%s all_kvs_keys=[] xmax_in_output=%s",
            len(scored), len(chosen), kept_headings,
            ("xmax" in final_text.lower() or "5.65" in final_text),
        )
        return final_text

    def rank_and_filter(self, sections: list, query: str, max_sections: int = 8, max_chars: int = 6000, doc_type: str = "general") -> str:
        if doc_type == "source_code":
            return self._rank_and_filter_code(
                sections,
                query,
                max_sections=max_sections,
                max_chars=min(max_chars, 4950),
            )
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
