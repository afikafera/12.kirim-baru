import logging
import re

logger = logging.getLogger(__name__)


class SearchStrategy:

    INTENT_META = {
        "technical_spec": {
            "goal": "collect_official_specs",
            "keywords": ["specification", "datasheet", "parameters", "technical data"],
        },
        "diagnosis": {
            "goal": "find_root_cause_and_fix",
            "keywords": ["troubleshooting", "repair", "fix", "solution", "diagnostic"],
        },
        "tutorial": {
            "goal": "collect_step_by_step_guide",
            "keywords": ["guide", "tutorial", "setup", "configuration", "how to"],
        },
        "comparison": {
            "goal": "compare_products_or_methods",
            "keywords": ["comparison", "differences", "versus", "which is better"],
        },
        "general": {
            "goal": "collect_relevant_information",
            "keywords": ["documentation", "guide", "explanation", "overview"],
        },
    }

    DOMAIN_TERMS = {
        "otomotif": ["workshop manual", "tsb", "wis", "diagnostic", "repair procedure", "torque spec"],
        "audio": ["datasheet", "t/s parameters", "thiele small", "frequency response", "sensitivity"],
        "networking": ["documentation", "configuration", "rfc", "command reference", "setup guide"],
        "iot": ["datasheet", "pinout", "sdk", "technical reference", "programming guide"],
    }

    def __init__(self, llm_analyzer=None):
        self.llm = llm_analyzer

    def simplify_need(self, need: str) -> str:
        """Extract important keywords from requirement."""
        if not need:
            return ""

        tokens = re.findall(r"[A-Za-z0-9+/.-]+", need.lower())

        stopwords = {
            "with","and","or","the",
            "official","page","product",
            "technical","information",
            "details","about","for","of"
        }

        keywords = [
            t for t in tokens
            if len(t) > 2 and t not in stopwords
        ]

        return " ".join(dict.fromkeys(keywords[:3]))


    def generate(self, query: str, intent: str, domain: str, product: str) -> dict:
        meta = self.INTENT_META.get(intent, self.INTENT_META["general"])
        domain_terms = self.DOMAIN_TERMS.get(domain, [])

        keywords = self._extract_keywords(query, product)
        keywords = (keywords + domain_terms)[:6]

        intent_keywords = [
            self.simplify_need(k)
            for k in meta["keywords"]
        ]

        search_queries = self._generate_queries(
            product,
            keywords,
            intent_keywords,
        )

        logger.info(f"[strategy] intent={intent} domain={domain} goal={meta['goal']}")
        for i, q in enumerate(search_queries):
            logger.info(f"[strategy]   query[{i}]: {q}")

        return {
            "intent": intent,
            "domain": domain,
            "goal": meta["goal"],
            "search_queries": search_queries,
        }

    def score_url(self, url: str, strategy: dict) -> float:
        url_lower = url.lower()
        score = 0.5

        if any(p in url_lower for p in ["docs.", "help.", "wiki.", "/documentation"]):
            score += 0.4
        if url_lower.endswith(".pdf"):
            score += 0.3
        if "manual" in url_lower:
            score += 0.2
        if "github.com" in url_lower:
            score += 0.25
        if "forum." in url_lower or "reddit.com" in url_lower or "stackoverflow.com" in url_lower:
            score += 0.15
        if any(p in url_lower for p in ["youtube.com", "youtu.be"]):
            score -= 0.3
        if any(p in url_lower for p in ["tiktok.com", "instagram.com", "facebook.com", "linkedin.com"]):
            score -= 0.4

        return max(0.0, min(1.0, score))

    def _extract_keywords(self, query: str, product: str) -> list:
        product_words = set(product.lower().split())
        query_words = query.lower().split()
        stopwords = {
            "dan", "di", "ke", "dari", "untuk", "dengan", "yang", "ini", "itu",
            "ada", "juga", "saya", "bagaimana", "apakah", "dimana", "adalah",
            "pada", "sebuah", "bagi", "tentang", "the", "a", "an", "of", "in",
            "on", "at", "to", "for", "with", "by", "from", "or", "and", "not",
            "cara", "setting", "set", "up", "how", "does", "what", "why",
            "that", "this", "these", "those", "may", "might", "can", "could",
            "contains", "contain", "information", "identify", "confirm", "list",
            "details", "page",
        }
        keywords = []
        for word in query_words:
            if word not in stopwords and word not in product_words and len(word) > 2:
                keywords.append(word)
        return keywords[:4]

    def _generate_queries(self, product: str, keywords: list, intent_keywords: list) -> list:
        queries = []
        if keywords:
            queries.append(f"{product} {' '.join(keywords[:3])}")
        for kw in keywords[:3]:
            queries.append(f"{product} {kw}")
        if intent_keywords:
            queries.append(f"{product} {intent_keywords[0]}")
        seen = set()
        unique = []
        for q in queries:
            if q.lower() not in seen:
                seen.add(q.lower())
                unique.append(q)
        return unique[:5]
