from .discourse import DiscourseConnector
from .base import Document
CONNECTORS = [
    DiscourseConnector(),
]

def fetch_url(url: str) -> Document:
    for c in CONNECTORS:
        if c.detect(url):
            return c.fetch(url)
    return Document(title="Unknown", source_url=url, platform="generic")
