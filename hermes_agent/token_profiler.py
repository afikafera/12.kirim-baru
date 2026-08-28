import time
from hermes_agent.jsonl_logger import get_request_id
import json
import os
import csv


class TokenProfiler:

    PRICING_FILE = os.path.expanduser("~/research-assistant/config/pricing.json")
    DEFAULT_MODEL = "deepseek-chat"
    CSV_FILE = os.path.expanduser("~/research-assistant/data/runs/history.csv")

    def __init__(self, model: str = None, budget: float = None):
        self.model = model or self.DEFAULT_MODEL
        self.budget = budget
        self.prices = self._load_prices()
        self.modules = {}
        self.start_time = time.perf_counter()
        self.request_id = get_request_id()
        self.metadata = {
            "request_id": self.request_id,
            "timestamp": int(time.time()),
            "model": self.model,
            "provider": self._detect_provider(),
            "pricing_snapshot": self._get_price(),
            "iterations": 0,
            "nodes": 0,
            "facts_total": 0,
        }

    def _load_prices(self) -> dict:
        try:
            if os.path.exists(self.PRICING_FILE):
                with open(self.PRICING_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _detect_provider(self) -> str:
        if "gpt" in self.model: return "openai"
        if "claude" in self.model: return "anthropic"
        if "gemini" in self.model: return "google"
        if "deepseek" in self.model: return "deepseek"
        return "unknown"

    def _get_price(self) -> dict:
        return self.prices.get(self.model) or self.prices.get(self.DEFAULT_MODEL) or {"input": 0.0, "output": 0.0}

    def start(self, module: str):
        self._ensure_module(module)
        self.modules[module]["_timer"] = time.perf_counter()

    def stop(self, module: str, result: dict = None):
        m = self.modules.get(module)
        if not m or "_timer" not in m: return 0
        duration_ms = (time.perf_counter() - m.pop("_timer")) * 1000
        if result: self._record(module, result, duration_ms)
        return duration_ms

    def add(self, module: str, result: dict, duration_ms: float = 0):
        self._ensure_module(module)
        self._record(module, result, duration_ms)

    def add_facts(self, module: str, count: int):
        self._ensure_module(module)
        self.modules[module]["facts_generated"] += count

    def set_metadata(self, **kwargs):
        self.metadata.update(kwargs)

    def _ensure_module(self, module: str):
        if module not in self.modules:
            self.modules[module] = {
                "calls": 0, "tokens_in": 0, "tokens_out": 0,
                "cost": 0.0, "duration_ms": 0.0, "facts_generated": 0,
            }

    def _record(self, module: str, result: dict, duration_ms: float):
        m = self.modules[module]
        m["calls"] += 1
        m["tokens_in"] += result.get("tokens_input", 0)
        m["tokens_out"] += result.get("tokens_output", 0)
        m["duration_ms"] += duration_ms
        price = self._get_price()
        cost = (result.get("tokens_input", 0) * price["input"] +
                result.get("tokens_output", 0) * price["output"]) / 1_000_000
        m["cost"] += round(cost, 8)

    @property
    def total_tokens(self) -> int:
        return sum(m["tokens_in"] + m["tokens_out"] for m in self.modules.values())

    @property
    def total_cost(self) -> float:
        return round(sum(m["cost"] for m in self.modules.values()), 6)

    @property
    def is_over_budget(self) -> bool:
        return self.budget is not None and self.total_cost >= self.budget

    @property
    def total_duration_ms(self) -> float:
        return (time.perf_counter() - self.start_time) * 1000

    @property
    def throughput(self):
        secs = self.total_duration_ms / 1000
        if secs < 0.1: return None
        return round(self.total_tokens / secs)

    def summary(self) -> dict:
        mods = {}
        for name, m in self.modules.items():
            total_tok = m["tokens_in"] + m["tokens_out"]
            pct = round(total_tok / self.total_tokens * 100, 1) if self.total_tokens else 0
            mods[name] = {
                **{k: v for k, v in m.items() if k != "_timer"},
                "total_tokens": total_tok, "pct_of_total": pct,
                "avg_tokens_per_call": round(total_tok / m["calls"]) if m["calls"] else 0,
                "avg_duration_ms": round(m["duration_ms"] / m["calls"]) if m["calls"] else 0,
            }

        ranked = sorted(mods.items(), key=lambda x: x[1]["total_tokens"], reverse=True)
        top = ranked[0] if ranked else None
        price = self._get_price()
        total_facts = sum(m["facts_generated"] for _, m in mods.items())
        self.metadata["facts_total"] = total_facts

        total = {
            "calls": sum(m["calls"] for _, m in mods.items()),
            "tokens_in": sum(m["tokens_in"] for _, m in mods.items()),
            "tokens_out": sum(m["tokens_out"] for _, m in mods.items()),
            "total_tokens": self.total_tokens,
            "cost": self.total_cost,
            "duration_ms": round(self.total_duration_ms),
            "throughput_tps": self.throughput,
            "budget": self.budget,
            "over_budget": self.is_over_budget,
        }

        efficiency = {
            "facts_per_1k_tokens": round(total_facts / (self.total_tokens / 1000), 2) if self.total_tokens else 0,
            "tokens_per_node": round(self.total_tokens / self.metadata["nodes"]) if self.metadata["nodes"] else 0,
            "facts_per_iteration": round(total_facts / self.metadata["iterations"]) if self.metadata["iterations"] else 0,
        }

        return {
            "request_id": self.request_id,
            "model": self.model, "provider": self.metadata["provider"],
            "pricing": {"input_per_1M": price["input"], "output_per_1M": price["output"]},
            "timestamp": self.metadata["timestamp"],
            "modules": dict(ranked),
            "top_consumer": {"module": top[0], "tokens": top[1]["total_tokens"], "pct": top[1]["pct_of_total"], "cost": top[1]["cost"]} if top else None,
            "total": total, "efficiency": efficiency, "metadata": self.metadata,
        }

    def save(self, path: str = None):
        s = self.summary()
        if not path:
            path = os.path.expanduser(f"~/research-assistant/data/runs/run_{int(time.time())}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(s, f, indent=2, default=str)
        self._append_csv(s)

    def _append_csv(self, s: dict):
        try:
            os.makedirs(os.path.dirname(self.CSV_FILE), exist_ok=True)
            exists = os.path.exists(self.CSV_FILE)
            with open(self.CSV_FILE, "a", newline="") as f:
                w = csv.writer(f)
                if not exists:
                    w.writerow(["timestamp", "request_id", "model", "provider", "tokens", "cost", "duration_ms", "facts", "iterations", "nodes", "throughput_tps"])
                t = s["total"]; m = s["metadata"]
                tp = t.get("throughput_tps")
                if tp is None: tp = "NA"
                w.writerow([m["timestamp"], s["request_id"], s["model"], s["provider"], t["total_tokens"], t["cost"], t["duration_ms"], m["facts_total"], m["iterations"], m["nodes"], tp])
        except Exception:
            pass

    def print_report(self):
        s = self.summary()
        print("=" * 50)
        print("HERMES RESEARCH REPORT")
        print("=" * 50)
        print(f"Request    : {s['request_id']}")
        print(f"Model      : {s['model']} ({s['provider']})")
        print(f"Duration   : {s['total']['duration_ms']/1000:.1f}s")
        tp = s['total'].get('throughput_tps')
        print(f"Throughput : {tp:,} tok/s" if tp else "Throughput : N/A")
        print(f"LLM Calls  : {s['total']['calls']}")
        print(f"Tokens     : {s['total']['total_tokens']:,}")
        print(f"Cost       : \${s['total']['cost']:.6f}", end="")
        print(" ⚠️ OVER BUDGET" if s['total']['over_budget'] else "")
        print(f"Facts      : {s['metadata']['facts_total']}")
        print(f"Iterations : {s['metadata']['iterations']}")
        print(f"Nodes      : {s['metadata']['nodes']}")
        print("\nTop Consumer:")
        for name, m in list(s['modules'].items())[:3]:
            print(f"  {name}: {m['total_tokens']:,} tokens ({m['pct_of_total']}%), \${m['cost']:.6f}")
        print("\nEfficiency:")
        for k, v in s['efficiency'].items():
            print(f"  {k}: {v}")
        print("=" * 50)
