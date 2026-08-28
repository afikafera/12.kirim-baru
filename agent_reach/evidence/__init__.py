import logging
from .normalizer import Normalizer
from .classifier import Classifier
from .section_engine import SectionEngine

logger = logging.getLogger(__name__)

# Trace marker sementara -- lihat instruksi audit "Xmax hilang di mana".
# Cari case-insensitive, hapus setelah root cause terbukti.
TRACE_MARKERS = ("xmax", "5.65")


class DocumentIntelligence:
    def __init__(self):
        self.normalizer = Normalizer()
        self.classifier = Classifier()
        self.sections = SectionEngine()

    def process(self, raw_content: str, query: str) -> dict:
        if not raw_content:
            return {"formatted": "", "doc_type": "unknown", "sections": 0}
        normalized = self.normalizer.normalize(raw_content)
        doc_type = self.classifier.classify(normalized)
        all_sections = self.sections.split_sections(normalized)
        formatted = self.sections.rank_and_filter(all_sections, query)

        low = raw_content.lower()
        for m in TRACE_MARKERS:
            if m in low:
                still_in = m in formatted.lower()
                logger.info(
                    "[TRACE XMAX] stage=docintel marker=%r in_raw=True in_formatted=%s doc_type=%s",
                    m, still_in, doc_type,
                )

        return {
            "formatted": formatted,
            "doc_type": doc_type,
            "sections_total": len(all_sections),
            "sections_kept": formatted.count("## "),
            "char_before": len(raw_content),
            "char_after": len(formatted),
        }
