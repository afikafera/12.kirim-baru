import time


class LatencyProfiler:

    def __init__(self):
        self.timings = {}
        self._start = {}

    def start(self, module: str):
        self._start[module] = time.perf_counter()

    def stop(self, module: str):
        if module not in self._start:
            return 0
        elapsed = (time.perf_counter() - self._start.pop(module)) * 1000
        self.timings[module] = self.timings.get(module, 0) + elapsed
        return elapsed

    @property
    def total_ms(self) -> float:
        return sum(self.timings.values())

    def summary(self) -> dict:
        total = self.total_ms
        report = {}
        for k, v in sorted(self.timings.items(), key=lambda x: x[1], reverse=True):
            report[k] = {
                "duration_ms": round(v),
                "duration_s": round(v / 1000, 2),
                "percent": round(v / total * 100, 1) if total else 0,
            }
        return {
            "modules": report,
            "total_ms": round(total),
            "total_s": round(total / 1000, 1),
            "slowest": next(iter(report)) if report else None,
        }
