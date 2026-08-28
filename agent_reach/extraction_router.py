from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractionResult:
    source_type: str
    method: str
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


class ExtractionRouter:
    def __init__(self, ocr_extractor=None):
        self.ocr_extractor = ocr_extractor

    """
    Generic extraction dispatcher.

    Domain-independent:
      text/document -> text extraction
      image         -> OCR
      technical     -> visual geometry
      graph         -> graph analysis

    Backend implementation tetap terpisah.
    """

    ROUTES = {
        "TEXT": "text_extract",
        "HTML": "text_extract",
        "PDF": "document_extract",
        "DATASHEET": "ocr_extract",
        "TECHNICAL_DRAWING": "visual_geometry",
        "FREQUENCY_GRAPH": "graph_analysis",
        "IMPEDANCE_GRAPH": "graph_analysis",
        "UNKNOWN": "skip",
    }

    def route(self, source_type: str) -> str:
        return self.ROUTES.get(
            source_type.upper(),
            "skip",
        )

    def _resolve_payload(self, payload: Any) -> Any:
        if isinstance(payload, (bytes, bytearray)):
            return bytes(payload)

        if isinstance(payload, str) and payload.startswith(("http://", "https://")):
            from .agent_browser_asset_resolver import AgentBrowserAssetResolver

            from urllib.parse import urlparse

            resolver = AgentBrowserAssetResolver()

            parsed = urlparse(payload)
            page_url = f"{parsed.scheme}://{parsed.netloc}/"

            try:
                resolver._open_with_retry(page_url)
                return resolver.fetch_asset(payload)
            finally:
                try:
                    resolver._run("close")
                except Exception:
                    pass

        return payload

    def extract(
        self,
        source_type: str,
        payload: Any,
    ) -> ExtractionResult:

        method = self.route(source_type)

        if method == "skip":
            return ExtractionResult(
                source_type=source_type,
                method=method,
            )

        if method == "ocr_extract":
            if self.ocr_extractor is None:
                return ExtractionResult(
                    source_type=source_type,
                    method=method,
                )

            payload = self._resolve_payload(payload)
            return self.ocr_extractor.extract(payload)

        # Backend lain belum dipasang.
        return ExtractionResult(
            source_type=source_type,
            method=method,
        )
