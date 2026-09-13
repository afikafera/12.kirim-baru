"""
Apply the VERIFIED (9/9 PASS) url-aware entity scoring patch to
aran_search/searcher.py :: AgentReachSearcher._score_and_rank().

Non-interactive, scripted apply (per procedure): creates a timestamped
backup, then does an exact, whole-method string replace guarded by
assertions (pattern must exist, and must be unique) so it refuses to
touch the file if the source has drifted since this diff was verified.

Run from the project root (~/research-assistant):
    python3 apply_url_entity_scoring_patch.py
"""
import datetime
import shutil
import subprocess
import sys
from pathlib import Path

TARGET = Path("aran_search/searcher.py")

OLD = '''    def _score_and_rank(self, results: list, max_output: int, category_label: str = "") -> list:
        import re

        raw_query = getattr(self, "_active_query", "")
        query = raw_query.lower()

        stopwords = {
            "dan", "di", "ke", "dari", "untuk", "dengan", "yang",
            "ini", "itu", "the", "a", "an", "of", "in", "on", "at",
            "to", "for", "with", "by", "from", "and",
            "spesifikasi", "specification", "specifications",
            "review", "harga", "price", "beli", "buy"
        }

        query_tokens = [
            token.lower()
            for token in re.findall(
                r"[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)+|[a-zA-Z0-9]+",
                query,
            )
            if len(token) > 1 and token not in stopwords
        ]

        scored = []

        for r in results:
            url = r.get("url", "")
            netloc = urlparse(url).netloc.lower()

            if any(d in netloc for d in self.BLOCKED):
                continue

            title = r.get("title", "")
            content = r.get("content", "")
            haystack = f"{title} {content}".lower()

            def token_present(token: str) -> bool:
                return bool(
                    re.search(
                        rf"(?<![a-zA-Z0-9]){re.escape(token)}(?![a-zA-Z0-9])",
                        haystack,
                    )
                )

            matches = sum(token_present(token) for token in query_tokens)

            entity_match = (
                bool(query_tokens)
                and all(token_present(token) for token in query_tokens)
            )

            raw_tokens = re.findall(
                r"[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)+|[a-zA-Z0-9]+",
                raw_query,
            )
            anchor_tokens = [
                token.lower()
                for token in raw_tokens
                if (
                    any(char.isdigit() for char in token)
                    or token.isupper()
                    or (
                        any(char.isupper() for char in token[1:])
                        and any(char.islower() for char in token)
                    )
                )
                and token.lower() in query_tokens
            ]

            if anchor_tokens:
                if not all(token_present(token) for token in anchor_tokens):
                    continue
            elif query_tokens:
                if matches < min(2, len(query_tokens)):
                    continue

            matched_tokens = [t for t in query_tokens if token_present(t)]
            logger.info(
                "[AUDIT SEARCH GATE] category=%s url=%s matches=%d matched=%s entity_match=%s",
                category_label, url, matches, matched_tokens, entity_match,
            )

            base_score = float(r.get("score", 0) or 0)
            relevance_bonus = matches * 2.0
            entity_bonus = 5.0 if entity_match else 0.0

            official_bonus = (
                3.0
                if netloc == "acrspeaker.com"
                or netloc.endswith(".acrspeaker.com")
                else 0.0
            )

            domain_bonus = self._score_url(url) * 0.1

            engine = r.get("engine", "")
            engine_bonus = (
                0.1
                if engine in ["google cse", "brave"]
                else 0.0
            )

            score = (
                base_score
                + relevance_bonus
                + entity_bonus
                + official_bonus
                + domain_bonus
                + engine_bonus
            )

            scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)

        seen = set()
        top = []

        for score, r in scored:
            netloc = urlparse(r.get("url", "")).netloc.lower()

            if netloc in seen:
                continue

            seen.add(netloc)
            top.append((score, r))

            if len(top) >= max_output:
                break

        return top
'''

NEW = '''    def _score_and_rank(self, results: list, max_output: int, category_label: str = "") -> list:
        import re

        raw_query = getattr(self, "_active_query", "")
        query = raw_query.lower()

        stopwords = {
            "dan", "di", "ke", "dari", "untuk", "dengan", "yang",
            "ini", "itu", "the", "a", "an", "of", "in", "on", "at",
            "to", "for", "with", "by", "from", "and",
            "spesifikasi", "specification", "specifications",
            "review", "harga", "price", "beli", "buy"
        }

        query_tokens = [
            token.lower()
            for token in re.findall(
                r"[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)+|[a-zA-Z0-9]+",
                query,
            )
            if len(token) > 1 and token not in stopwords
        ]

        # PATCH (url-entity-scoring): entity-path tokens = capitalized
        # mid-sentence tokens from the RAW query (proper-noun-like),
        # excluding the sentence-initial token to avoid false positives
        # (e.g. "What"). Used only for path_bonus below; generic
        # descriptive words never qualify.
        raw_tokens_all = re.findall(
            r"[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)+|[a-zA-Z0-9]+",
            raw_query,
        )
        path_entity_tokens = [
            tok.lower()
            for i, tok in enumerate(raw_tokens_all)
            if i > 0
            and tok[:1].isupper()
            and tok.lower() in query_tokens
        ]

        scored = []

        for r in results:
            url = r.get("url", "")
            netloc = urlparse(url).netloc.lower()

            if any(d in netloc for d in self.BLOCKED):
                continue

            title = r.get("title", "")
            content = r.get("content", "")
            # PATCH (url-entity-scoring): URL now included so entity
            # mentions that only exist in the URL (not title/content)
            # count toward matches AND can satisfy the anchor-token gate
            # below.
            haystack = f"{title} {content} {url}".lower()

            def token_present(token: str) -> bool:
                return bool(
                    re.search(
                        rf"(?<![a-zA-Z0-9]){re.escape(token)}(?![a-zA-Z0-9])",
                        haystack,
                    )
                )

            matches = sum(token_present(token) for token in query_tokens)

            entity_match = (
                bool(query_tokens)
                and all(token_present(token) for token in query_tokens)
            )

            raw_tokens = re.findall(
                r"[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)+|[a-zA-Z0-9]+",
                raw_query,
            )
            anchor_tokens = [
                token.lower()
                for token in raw_tokens
                if (
                    any(char.isdigit() for char in token)
                    or token.isupper()
                    or (
                        any(char.isupper() for char in token[1:])
                        and any(char.islower() for char in token)
                    )
                )
                and token.lower() in query_tokens
            ]

            if anchor_tokens:
                if not all(token_present(token) for token in anchor_tokens):
                    continue
            elif query_tokens:
                if matches < min(2, len(query_tokens)):
                    continue

            matched_tokens = [t for t in query_tokens if token_present(t)]
            logger.info(
                "[AUDIT SEARCH GATE] category=%s url=%s matches=%d matched=%s entity_match=%s",
                category_label, url, matches, matched_tokens, entity_match,
            )

            base_score = float(r.get("score", 0) or 0)
            relevance_bonus = matches * 2.0
            entity_bonus = 5.0 if entity_match else 0.0

            official_bonus = (
                3.0
                if netloc == "acrspeaker.com"
                or netloc.endswith(".acrspeaker.com")
                else 0.0
            )

            domain_bonus = self._score_url(url) * 0.1

            engine = r.get("engine", "")
            engine_bonus = (
                0.1
                if engine in ["google cse", "brave"]
                else 0.0
            )

            # PATCH (url-entity-scoring): deterministic path-specific
            # bonus. Restricted to path_entity_tokens only (proper-noun-
            # like, never generic descriptive words such as
            # current/updated/last/price), applied only against the URL
            # PATH; rewards canonical entity pages over generic pages
            # sharing the same domain. Implemented independently of
            # token_present (which is bound to `haystack`) so that
            # function's signature is left unchanged.
            path_text = urlparse(url).path.lower()
            path_bonus = 3.0 * sum(
                bool(re.search(
                    rf"(?<![a-zA-Z0-9]){re.escape(tok)}(?![a-zA-Z0-9])",
                    path_text,
                ))
                for tok in path_entity_tokens
            )

            score = (
                base_score
                + relevance_bonus
                + entity_bonus
                + official_bonus
                + domain_bonus
                + engine_bonus
                + path_bonus
            )

            scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)

        seen = set()
        top = []

        for score, r in scored:
            netloc = urlparse(r.get("url", "")).netloc.lower()

            if netloc in seen:
                continue

            seen.add(netloc)
            top.append((score, r))

            if len(top) >= max_output:
                break

        return top
'''


def main():
    if not TARGET.exists():
        print(f"ABORT: {TARGET} not found. Run this from the project root.")
        sys.exit(1)

    src = TARGET.read_text()

    if OLD not in src:
        print("ABORT: exact OLD pattern not found in current source.")
        print("Source has drifted since this diff was verified; do not")
        print("proceed. Re-audit aran_search/searcher.py::_score_and_rank()")
        print("and reconcile before retrying.")
        sys.exit(1)

    if src.count(OLD) != 1:
        print(f"ABORT: OLD pattern matched {src.count(OLD)} times, expected exactly 1.")
        sys.exit(1)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = TARGET.with_name(f"{TARGET.name}.bak_before_url_entity_scoring_{ts}")
    shutil.copy2(TARGET, backup_path)
    print(f"BACKUP CREATED: {backup_path}")

    TARGET.write_text(src.replace(OLD, NEW))
    print(f"PATCHED: {TARGET}")

    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(TARGET)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("SYNTAX CHECK FAILED:")
        print(result.stdout)
        print(result.stderr)
        print("Restoring from backup...")
        shutil.copy2(backup_path, TARGET)
        print("RESTORED. Do not proceed further; re-audit before retrying.")
        sys.exit(1)

    print("SYNTAX CHECK PASS")
    print(f"\nBackup filename: {backup_path}")
    print(f"Timestamp: {ts}")


if __name__ == "__main__":
    main()
