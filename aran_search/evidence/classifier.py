import re


class Classifier:
    HEADING = re.compile(r'^#{1,4}\s+', re.MULTILINE)
    KV_LINE = re.compile(r'^([A-Za-z][\w\s/()-]{2,40})[:\s]{2,}(.+)$', re.MULTILINE)
    YOUTUBE_URL = re.compile(
        r'https?://(?:www\.)?(?:youtube\.com/watch\?[^\s]+|youtu\.be/[^\s]+)',
        re.IGNORECASE,
    )

    def classify(self, content: str) -> str:
        if not content:
            return "general"
        if self.YOUTUBE_URL.search(content):
            return "video"
        headings = len(self.HEADING.findall(content))
        kvs = len(self.KV_LINE.findall(content))
        if kvs >= 8:
            return "datasheet"
        if headings >= 4:
            return "documentation"
        if headings >= 1 and len(content) > 800:
            return "article"
        return "general"
