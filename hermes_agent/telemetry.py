import json
import time


class LLMUsage:
    def __init__(self):
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost = 0.0
        self.breakdown = []
        self.total_duration_ms = 0

    def add(self, result: dict, label: str = "", duration_ms: float = 0):
        self.calls += 1
        self.tokens_in += result.get("tokens_input", 0)
        self.tokens_out += result.get("tokens_output", 0)
        self.cost += result.get("api_cost", 0)
        self.total_duration_ms += duration_ms
        self.breakdown.append({
            "label": label,
            "tokens_in": result.get("tokens_input", 0),
            "tokens_out": result.get("tokens_output", 0),
            "cost": result.get("api_cost", 0),
            "duration_ms": round(duration_ms, 1),
        })

    def summary(self) -> dict:
        return {
            "calls": self.calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost": self.cost,
            "total_duration_ms": round(self.total_duration_ms, 1),
            "breakdown": self.breakdown,
        }


class TelemetryManager:
    def __init__(self):
        self.llm = LLMUsage()
        self.search_count = 0
        self.fetch_count = 0
        self.unique_urls = set()
        self.break_reason = "unknown"
        self.iterations = []
        self.started_at = time.time()

    def add_search(self):
        self.search_count += 1

    def add_fetch(self, url: str, success: bool):
        self.fetch_count += 1
        if success:
            self.unique_urls.add(url)

    def add_llm(self, result: dict, label: str, duration_ms: float = 0):
        self.llm.add(result, label, duration_ms)

    def add_iteration(self, data: dict):
        self.iterations.append(data)

    def summary(self) -> dict:
        duration_ms = (time.time() - self.started_at) * 1000
        return {
            "llm": self.llm.summary(),
            "searches": self.search_count,
            "fetches": self.fetch_count,
            "unique_sources": len(self.unique_urls),
            "break_reason": self.break_reason,
            "iterations": self.iterations,
            "total_duration_ms": round(duration_ms, 1),
        }
