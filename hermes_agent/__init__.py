"""ARAN research runtime exports with a legacy class alias."""

__all__ = ["AranAgent", "HermesAgent"]


def __getattr__(name):
    if name in __all__:
        from .orchestrator import AranAgent, HermesAgent

        globals().update(AranAgent=AranAgent, HermesAgent=HermesAgent)
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
