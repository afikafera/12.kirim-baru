from typing import Any

from .extraction_router import ExtractionResult


class OCRExtractor:
    """
    Generic image OCR backend.

    Input:
        image bytes

    Output:
        ExtractionResult

    Tidak mengetahui domain/source tertentu.
    """

    def __init__(self, lang: str = "en"):
        from paddleocr import PaddleOCR

        self.ocr = PaddleOCR(
            lang=lang,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    def extract(self, image_bytes: bytes) -> ExtractionResult:
        import io
        import numpy as np
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        image = np.asarray(image)

        result = self.ocr.predict(image)

        texts = []
        scores = []

        for item in result:
            if not hasattr(item, "get"):
                continue

            rec_texts = item.get("rec_texts", [])
            rec_scores = item.get("rec_scores", [])

            texts.extend(rec_texts)
            scores.extend(rec_scores)

        text = "\n".join(
            str(t).strip()
            for t in texts
            if str(t).strip()
        )

        confidence = (
            sum(scores) / len(scores)
            if scores
            else 0.0
        )

        return ExtractionResult(
            source_type="DATASHEET",
            method="ocr_extract",
            text=text,
            data={
                "texts": texts,
                "scores": scores,
            },
            confidence=float(confidence),
        )
