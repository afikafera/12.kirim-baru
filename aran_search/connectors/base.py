from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import hashlib
import json
import os


@dataclass
class Document:
    title: str
    source_url: str
    platform: str
    author: str = ""
    created_at: str = ""
    messages: list = field(default_factory=list)
    participants: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class BaseConnector(ABC):
    CACHE_DIR = os.path.expanduser("~/research-assistant/cache/connectors")

    def __init__(self):
        os.makedirs(self.CACHE_DIR, exist_ok=True)

    @abstractmethod
    def detect(self, url: str) -> bool:
        pass

    @abstractmethod
    def fetch(self, url: str) -> Document:
        pass

    def _cache_key(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _cache_get(self, url: str) -> Optional[Document]:
        key = self._cache_key(url)
        path = os.path.join(self.CACHE_DIR, f"{key}.json")
        if os.path.exists(path):
            # Cek apakah masih valid (24 jam)
            import time
            if time.time() - os.path.getmtime(path) < 86400:
                with open(path) as f:
                    data = json.load(f)
                    return Document(**data)
        return None

    def _cache_set(self, url: str, doc: Document):
        key = self._cache_key(url)
        path = os.path.join(self.CACHE_DIR, f"{key}.json")
        with open(path, "w") as f:
            json.dump(doc.__dict__, f, default=str)
