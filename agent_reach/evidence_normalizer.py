from dataclasses import dataclass, field
from typing import Any


@dataclass
class Evidence:
    source_type: str
    method: str
    text: str = ""
    confidence: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class EvidenceNormalizer:
    """
    Normalisasi hasil extractor menjadi kontrak evidence generik.

    Tidak mengetahui domain:
    speaker, otomotif, networking, elektronika, dll.
    """

    def normalize(self, result) -> Evidence:
        source_type = (
            getattr(result, "source_type", "")
            or getattr(result, "source", "")
            or ""
        )
        method = getattr(result, "method", "") or ""
        confidence = float(getattr(result, "confidence", 0.0) or 0.0)

        data = getattr(result, "data", {}) or {}

        if not isinstance(data, dict):
            data = {"value": data}

        texts = data.get("texts", [])

        if isinstance(texts, list):
            text = "\n".join(
                str(x) for x in texts
                if x is not None
            )
        elif texts:
            text = str(texts)
        else:
            text = ""

        return Evidence(
            source_type=source_type,
            method=method,
            text=text,
            confidence=confidence,
            data=data,
        )
