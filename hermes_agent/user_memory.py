import json
import os
import re
import tempfile
import shutil
from datetime import datetime


class UserMemory:
    MEMORY_FILE = os.path.expanduser(
        "~/research-assistant/data/user_memory.json"
    )

    QUERY_STOPWORDS = {
        # Indonesian
        "apa", "apakah", "siapa", "mana", "yang", "ini", "itu",
        "nama", "kode", "proyek", "project", "untuk", "dari",
        "dengan", "tentang", "adalah",

        # English
        "what", "which", "who", "is", "the", "name", "code",
        "project", "for", "of", "about", "this", "that",
    }

    def __init__(self):
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.MEMORY_FILE):
            with open(self.MEMORY_FILE, encoding="utf-8") as f:
                return json.load(f)
        return {"memories": []}

    def add(self, topic, field, value, source="user"):
        for m in self.data["memories"]:
            if (
                m["topic"] == topic
                and m["field"] == field
                and str(m["value"]) == str(value)
            ):
                return

        self.data["memories"].append({
            "topic": topic,
            "field": field,
            "value": value,
            "source": source,
            "created_at": datetime.now().isoformat(),
        })

        self.save()

    @staticmethod
    def _tokens(text):
        return [
            token.lower()
            for token in re.findall(r"[a-zA-Z0-9]+", str(text))
            if token
        ]

    def search(self, query):
        query_tokens = {
            token
            for token in self._tokens(query)
            if token not in self.QUERY_STOPWORDS
        }

        if not query_tokens:
            return []

        scored = []

        for m in self.data["memories"]:
            topic_tokens = set(self._tokens(m.get("topic", "")))
            value_tokens = set(self._tokens(m.get("value", "")))

            # Retrieval harus berdasarkan entity/value yang spesifik.
            # Field seperti "project_code" tidak dijadikan sinyal utama
            # karena kata "project/proyek/kode" terlalu generik.
            strong_tokens = topic_tokens | value_tokens

            matched = query_tokens & strong_tokens

            if not matched:
                continue

            # Topic match sedikit lebih kuat daripada value-only match.
            topic_matches = query_tokens & topic_tokens
            value_matches = query_tokens & value_tokens

            score = (
                len(topic_matches) * 3
                + len(value_matches) * 2
            )

            scored.append((score, m))

        scored.sort(key=lambda item: item[0], reverse=True)

        return [m for _, m in scored]

    def save(self):
        os.makedirs(os.path.dirname(self.MEMORY_FILE), exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(self.MEMORY_FILE),
            suffix=".json"
        )

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    self.data,
                    f,
                    indent=2,
                    ensure_ascii=False
                )
            shutil.move(tmp_path, self.MEMORY_FILE)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
