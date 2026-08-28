from dataclasses import dataclass
import re


@dataclass
class RouteResult:
    mode: str
    reason: str
    confidence: float


class SemanticRouter:

    def route(self, query: str, has_context: bool = False) -> RouteResult:
        q = query.strip()

        # Simple execution commands that do not request external knowledge
        # must stay on the direct LLM path.
        # Research is selected only when the query actually requires
        # external/current/source-backed information.
        if re.match(
            r"^(reply|respond|answer|balas|jawab)\s+"
            r"(exactly|only|hanya|tepat|dengan|dengan tepat)\b",
            q,
            re.IGNORECASE,
        ):
            return RouteResult(
                mode="direct",
                reason="simple_execution_command",
                confidence=0.99,
            )

        if self._is_math(q):
            return RouteResult(
                mode="direct",
                reason="basic_math",
                confidence=0.99,
            )

        if self._is_greeting(q):
            return RouteResult(
                mode="direct",
                reason="greeting",
                confidence=0.99,
            )

        if self._is_translation(q):
            return RouteResult(
                mode="direct",
                reason="translation",
                confidence=0.95,
            )

        if self._looks_like_external_lookup(q.lower()):
            return RouteResult(
                mode="research",
                reason="research_required",
                confidence=0.90,
            )

        if self._looks_like_external_media(q):
            return RouteResult(
                mode="research",
                reason="external_media",
                confidence=0.98,
            )

        if self._is_logic_reasoning(q):
            return RouteResult(
                mode="direct",
                reason="logic_reasoning",
                confidence=0.90,
            )

        if self._is_self_contained_reasoning(q):
            return RouteResult(
                mode="direct",
                reason="self_contained_reasoning",
                confidence=0.88,
            )

        if self._is_short_llm(q):
            if self._looks_like_entity_lookup(q):
                return RouteResult(
                    mode="research",
                    reason="entity_lookup",
                    confidence=0.92,
                )

            if has_context:
                return RouteResult(
                    mode="research",
                    reason="contextual_followup",
                    confidence=0.90,
                )

            return RouteResult(
                mode="direct",
                reason="general_llm",
                confidence=0.85,
            )

        return RouteResult(
            mode="research",
            reason="research_required",
            confidence=0.90,
        )

    def _is_math(self, q: str):
        s = q.lower().strip()

        # Allow natural-language math prompts such as:
        # "hitung 25 x 4"
        if s.startswith("hitung "):
            s = s[7:].strip()

        return re.fullmatch(
            r"[0-9\.\+\-\*/\(\)\sxX×÷=]+",
            s,
        ) is not None

    def _is_greeting(self, q: str):
        s = q.lower().strip()
        greetings = (
            "halo",
            "hai",
            "hi",
            "hello",
            "selamat pagi",
            "selamat siang",
            "selamat malam",
        )

        return any(
            s == g or s.startswith(g + " ")
            for g in greetings
        )

    def _is_translation(self, q: str):
        s = q.lower()
        prefixes = (
            "translate",
            "terjemahkan",
            "translate:",
            "translate ",
        )
        return any(s.startswith(p) for p in prefixes)

    def _looks_like_external_media(self, q: str):
        s = q.lower()

        if re.search(r"https?://\\S+", s):
            return True

        media_terms = (
            "youtube",
            "youtu.be",
            "video",
            "video youtube",
        )

        return any(term in s for term in media_terms)

    def _is_logic_reasoning(self, q: str):
        s = q.lower()

        logic_patterns = (
            "apakah",
            "boleh menyimpulkan",
            "pasti",
            "siapa yang paling",
            "mana yang",
            "benarkah",
            "jika",
            "maka",
        )

        return (
            len(q.split()) >= 8
            and any(pattern in s for pattern in logic_patterns)
            and not self._looks_like_external_lookup(s)
        )

    def _is_self_contained_reasoning(self, q: str):
        s = q.lower()

        reasoning_terms = (
            "tentukan",
            "jelaskan",
            "hitung",
            "buktikan",
            "mengapa",
            "kenapa",
            "bagaimana",
            "langkah penalaran",
            "secara logis",
        )

        return (
            len(q.split()) >= 6
            and any(term in s for term in reasoning_terms)
            and not self._looks_like_external_lookup(s)
        )

    def _looks_like_external_lookup(self, q: str):
        external_terms = (
            "harga",
            "price",
            "terbaru",
            "terkini",
            "hari ini",
            "sekarang",
            "spesifikasi",
            "specification",
            "review",
            "berita",
            "release",
            "rilis",
            "documentation",
            "documentasi",
            "docs",
            "api",
        )

        return any(term in q for term in external_terms)

    def _is_short_llm(self, q: str):
        if len(q.split()) > 5:
            return False

        s = q.lower()

        # Short entity/product/model lookups need research.
        lookup_terms = (
            "speaker", "acoustic", "acr", "jbl", "mikrotik",
            "router", "switch", "model", "spec", "specification",
            "harga", "price", "review", "produk", "product",
        )

        if any(term in s.split() for term in lookup_terms):
            return False

        return True

    def _looks_like_entity_lookup(self, q: str):
        # Short query yang mengandung model/part number/entity identifier
        # diarahkan ke research agar tidak dijawab dari general knowledge.
        tokens = q.split()
        return any(
            any(c.isdigit() for c in token)
            and any(c.isalpha() for c in token)
            for token in tokens
        )
