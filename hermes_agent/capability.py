"""
Capability Registry and Capability-Aware Scheduler for Hermes Agent.

Fase 3: Deterministic, zero-LLM, minimal capability routing:
Requirement(topic + need) -> Capability -> Provider/Skill
"""

import logging
from typing import Dict, List, Optional, Set, Any

logger = logging.getLogger(__name__)


class Capability:
    WEB_SEARCH = "web_search"
    WEB_FETCH = "web_fetch"
    WEATHER = "weather"
    FINANCIAL = "financial"
    CODE_SEARCH = "code_search"
    UNKNOWN = "unknown"


class CapabilityRegistry:
    """
    Source of truth for provider/skill -> capabilities mapping.
    """
    DEFAULT_PROVIDERS: Dict[str, Dict[str, Any]] = {
        "agent-reach": {
            "name": "agent-reach",
            "description": "Agent Reach internet search and capability router",
            "category": "search",
            "capabilities": {Capability.WEB_SEARCH, Capability.WEB_FETCH},
        },
        "agent-reach-fetch": {
            "name": "agent-reach-fetch",
            "description": "Agent Reach direct URL fetch capability",
            "category": "fetch",
            "capabilities": {Capability.WEB_FETCH},
        },
        "weather": {
            "name": "weather",
            "description": "Weather forecast and current conditions provider",
            "category": "weather",
            "capabilities": {Capability.WEATHER},
        },
    }

    def __init__(self, providers: Optional[Dict[str, Dict[str, Any]]] = None):
        if providers is not None:
            self._providers = {k: dict(v) for k, v in providers.items()}
            for p in self._providers.values():
                if "capabilities" in p and not isinstance(p["capabilities"], set):
                    p["capabilities"] = set(p["capabilities"])
        else:
            self._providers = {
                k: {
                    **v,
                    "capabilities": set(v["capabilities"]),
                }
                for k, v in self.DEFAULT_PROVIDERS.items()
            }

    def get_providers_for_capability(self, capability: str) -> List[Dict[str, Any]]:
        """Returns all registered providers that declare the given capability."""
        matches = []
        for p in self._providers.values():
            caps = p.get("capabilities", set())
            if capability in caps:
                matches.append(p)
        return matches

    def get_provider(self, name: str) -> Optional[Dict[str, Any]]:
        return self._providers.get(name)

    def register_provider(self, name: str, info: Dict[str, Any]) -> None:
        info_copy = dict(info)
        if "capabilities" in info_copy and not isinstance(info_copy["capabilities"], set):
            info_copy["capabilities"] = set(info_copy["capabilities"])
        self._providers[name] = info_copy

    def unregister_provider(self, name: str) -> Optional[Dict[str, Any]]:
        return self._providers.pop(name, None)


class CapabilityResolver:
    """
    Deterministic (topic, need) -> required Capability mapper. Zero-LLM.
    """
    WEATHER_KEYWORDS = (
        "weather", "cuaca", "suhu", "temperature", "forecast", "prakiraan",
        "hujan", "rain", "angin", "kelembapan",
    )
    FETCH_KEYWORDS = (
        "http://", "https://", "www.", "url", "download", "fetch", "crawl", "baca url",
    )
    FINANCIAL_KEYWORDS = (
        "stock", "saham", "crypto", "bitcoin", "btc", "ihsg", "nasdaq",
        "forex", "kurs", "valuation", "market cap", "dividen",
    )
    CODE_KEYWORDS = (
        "github", "gitlab", "commit", "pull request", "repository", "repo",
        "source code", "diff", "codebase",
    )

    @classmethod
    def resolve(cls, topic: str, need: str = "") -> str:
        text = f"{topic} {need}".lower()

        # 1. Weather
        for kw in cls.WEATHER_KEYWORDS:
            if kw in text:
                return Capability.WEATHER

        # 2. Direct fetch / URL
        for kw in cls.FETCH_KEYWORDS:
            if kw in text:
                return Capability.WEB_FETCH

        # 3. Financial
        for kw in cls.FINANCIAL_KEYWORDS:
            if kw in text:
                return Capability.FINANCIAL

        # 4. Code Search
        for kw in cls.CODE_KEYWORDS:
            if kw in text:
                return Capability.CODE_SEARCH

        # 5. Default: Web Search
        return Capability.WEB_SEARCH


class CapabilityScheduler:
    """
    Matches required capability with registered providers.
    Deterministic preferences:
    - WEB_SEARCH -> agent-reach
    - WEB_FETCH -> agent-reach-fetch preferred, agent-reach fallback if registered with WEB_FETCH
    - WEATHER -> weather
    - FINANCIAL / CODE_SEARCH -> None (if no provider registered)
    """

    def __init__(self, registry: Optional[CapabilityRegistry] = None):
        self.registry = registry if registry is not None else CapabilityRegistry()

    def schedule(self, topic: str, need: str = "") -> Optional[Dict[str, Any]]:
        required_cap = CapabilityResolver.resolve(topic, need)
        return self.schedule_capability(required_cap)

    def schedule_capability(self, capability: str) -> Optional[Dict[str, Any]]:
        candidates = self.registry.get_providers_for_capability(capability)
        if not candidates:
            return None

        # Deterministic preference ordering
        if capability == Capability.WEB_FETCH:
            # Prefer agent-reach-fetch
            fetch_pref = [c for c in candidates if c.get("name") == "agent-reach-fetch"]
            if fetch_pref:
                return fetch_pref[0]
            # Fallback to agent-reach if it has WEB_FETCH
            reach_fallback = [c for c in candidates if c.get("name") == "agent-reach"]
            if reach_fallback:
                return reach_fallback[0]
            return candidates[0]

        if capability == Capability.WEB_SEARCH:
            reach_pref = [c for c in candidates if c.get("name") == "agent-reach"]
            if reach_pref:
                return reach_pref[0]
            return candidates[0]

        if capability == Capability.WEATHER:
            weather_pref = [c for c in candidates if c.get("name") == "weather"]
            if weather_pref:
                return weather_pref[0]
            return candidates[0]

        return candidates[0]
