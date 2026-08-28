from dataclasses import dataclass
from typing import Optional

from .fact_extractor import Fact


@dataclass
class SynthesizedFact:
    key: str
    value: str
    unit: Optional[str]
    confidence: float
    source_type: str
    method: str

    def as_text(self) -> str:
        value = self.value
        if self.unit:
            value = f"{value} {self.unit}"

        return (
            f"{self.key} = {value} "
            f"[source={self.source_type}, "
            f"method={self.method}, "
            f"confidence={self.confidence:.3f}]"
        )


class FactSynthesizer:
    """
    Mengubah generic Fact menjadi representasi yang siap
    dipakai layer research/answer.

    Tidak mengetahui domain tertentu.
    """

    def synthesize(self, facts: list[Fact]) -> list[SynthesizedFact]:
        return [
            SynthesizedFact(
                key=fact.key,
                value=fact.value,
                unit=fact.unit,
                confidence=fact.confidence,
                source_type=fact.source_type,
                method=fact.method,
            )
            for fact in facts
        ]

    def render(self, facts: list[Fact]) -> str:
        synthesized = self.synthesize(facts)

        return "\n".join(
            fact.as_text()
            for fact in synthesized
        )
