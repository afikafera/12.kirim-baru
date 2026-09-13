from dataclasses import dataclass
from typing import Optional
import re


@dataclass
class Fact:
    key: str
    value: str
    unit: Optional[str] = None
    confidence: float = 0.0
    source_type: str = ""
    method: str = ""


class FactExtractor:
    @staticmethod
    def _looks_like_unit(text: str) -> bool:
        text = text.strip()

        if not text or " " in text:
            return False

        if text.lower() in {
            "hz", "khz", "mhz",
            "v", "a", "w", "mw",
            "db", "ohm",
            "mm", "cm", "m",
            "kg", "g", "gr",
            "%",
            "mh", "h",
            "liters", "liter", "l",
        }:
            return True

        if "/" in text or "." in text:
            return bool(
                re.fullmatch(r"[A-Za-z0-9.%Ωµμ/.-]+", text)
            )

        # Compound units with exponent, e.g. m2, cm2, m3.
        if re.fullmatch(r"[A-Za-zµμΩ]+[0-9]+", text):
            return True

        return bool(re.fullmatch(r"[A-Za-zµμΩ]+", text))


    """
    Generic fact extraction.

    Tidak mengetahui domain tertentu.
    Hanya mencari pola label -> value -> optional unit
    dari evidence yang sudah dinormalisasi.
    """

    _NUMBER_RE = re.compile(
        r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$"
    )

    def extract(self, evidence) -> list[Fact]:
        texts = evidence.data.get("texts", [])
        scores = evidence.data.get("scores", [])

        facts = []

        for i, text in enumerate(texts):
            if not isinstance(text, str):
                continue

            label = text.strip()

            if not label:
                continue

            # Pola:
            # label
            # value
            # unit
            if i + 1 >= len(texts):
                continue

            value = str(texts[i + 1]).strip()

            if not self._NUMBER_RE.match(value):
                continue

            unit = None

            if i + 2 < len(texts):
                candidate = str(texts[i + 2]).strip()

                # Unit hanya jika bukan angka.
                if candidate and self._looks_like_unit(candidate):
                    unit = candidate

            score = 0.0

            if i < len(scores):
                try:
                    score = float(scores[i])
                except (TypeError, ValueError):
                    pass

            facts.append(
                Fact(
                    key=label,
                    value=value,
                    unit=unit,
                    confidence=score,
                    source_type=evidence.source_type,
                    method=evidence.method,
                )
            )

        return facts
