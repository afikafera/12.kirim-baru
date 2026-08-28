import re
from difflib import SequenceMatcher


class FactRanker:

    METADATA_PATTERNS = [
        r'^(judul|title|uploader|penulis|author|durasi|duration|timestamp|tanggal|date|post_date|profile_name)_',
        r'^(instagram|tiktok|youtube|facebook|twitter|linkedin)_',
        r'_(hashtag|username|url|link|thumbnail|gambar|image|video_id|post_date)$',
        r'^(total_post|partisipan|status_forum|jumlah_)$',
        r'^(deskripsi_|link_|fokus_|topik_)',
        r'^(title|post_date|profile_name)$',
        r'^judul_video',
        r'^uploader_video',
        r'^durasi_video',
        r'^deskripsi_video',
        r'^deskripsi_lengkap',
    ]

    def __init__(self):
        self.metadata_re = [re.compile(p) for p in self.METADATA_PATTERNS]

    def is_metadata(self, field_id: str) -> bool:
        for pattern in self.metadata_re:
            if pattern.search(field_id):
                return True
        return False

    def score_relevance(self, field_id: str, field_value: str, query: str) -> float:
        score = 0.0
        q = query.lower()
        fid = field_id.lower()
        val = str(field_value).lower()[:200]

        if self.is_metadata(fid):
            return 0.0

        for term in q.split():
            if len(term) > 2 and term in fid:
                score += 0.3
        score += SequenceMatcher(None, fid, q).ratio() * 0.2
        for term in q.split():
            if len(term) > 2 and term in val:
                score += 0.1

        return min(score, 1.0)

    def rank(self, facts: dict, query: str, min_score: float = 0.05) -> dict:
        scored = []
        for field_id, v in facts.items():
            value = v.get("value", "") if isinstance(v, dict) else str(v)
            score = self.score_relevance(field_id, value, query)

            if self.is_metadata(field_id):
                continue

            scored.append((score, field_id, v))

        scored.sort(key=lambda x: x[0], reverse=True)
        ranked = {}
        for score, field_id, v in scored:
            ranked[field_id] = v
        return ranked
