import re
class Normalizer:
    def normalize(self, raw: str) -> str:
        if not raw: return ""
        if '<h' in raw[:500].lower() or '<table' in raw[:500].lower():
            return self._html_to_md(raw)
        return raw
    def _html_to_md(self, html: str) -> str:
        text = re.sub(r'<h1[^>]*>(.*?)</h1>', r'# \1\n', html, flags=re.I|re.DOTALL)
        text = re.sub(r'<h2[^>]*>(.*?)</h2>', r'## \1\n', text, flags=re.I|re.DOTALL)
        text = re.sub(r'<h3[^>]*>(.*?)</h3>', r'### \1\n', text, flags=re.I|re.DOTALL)
        text = re.sub(r'<tr[^>]*><t[dh][^>]*>(.*?)</t[dh]><t[dh][^>]*>(.*?)</t[dh]></tr>', r'\1: \2\n', text, flags=re.I|re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        return text.strip()
