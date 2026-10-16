"""Recognize code creation/repair without treating an API name as a web request."""
import re

_ACTION = re.compile(
    r"\b(?:buat(?:kan)?|tulis(?:kan)?|perbaiki|benahi|implementasi(?:kan|nya)?|"
    r"refactor|fix|write|create|implement|generate|build|show\s+me)\b", re.I)
_CODE = re.compile(
    r"\b(?:kode|code|script|skrip|endpoint|html|css|python|javascript|typescript|"
    r"sql|bash|golang|java|rust|csharp|cpp)\b", re.I)
_NEGATED = re.compile(
    r"\b(?:jangan|tidak\s+perlu|do\s+not|don't)\s+"
    r"(?:buat(?:kan)?|tulis(?:kan)?|write|create|generate|build)\b", re.I)
_EXTERNAL = re.compile(
    r"https?://|\b(?:terbaru|terkini|hari\s+ini|latest|current|"
    r"dokumentasi|documentasi|documentation|docs|referensi|references?|"
    r"sitasi|citations?|riset|research|benchmark|sources?|sumber|"
    r"berita|news|rilis|release)\b|"
    r"^\s*(?:(?:please|tolong|coba)\s+)?(?:cari(?:kan)?|search|lookup|browse|telusuri)\b|"
    r"\b(?:dan|lalu|kemudian|and|then)\s+(?:cari(?:kan)?|search|lookup|browse|telusuri)\b", re.I)


def coding_request(query):
    """Return (is_code_creation_or_repair, needs_external_information).

    Fenced code is task data, not routing instructions. This intentionally
    does not infer a new task type from assistant history or attachments.
    """
    fence = re.escape(chr(96) * 3)
    text = re.sub(fence + r".*?" + fence, " ", query, flags=re.S)
    marker_text = re.sub(
        r"\b(?:kode\s+(?:pos|promo|voucher|otp|verifikasi)|"
        r"(?:postal|zip|promo|coupon|verification)\s+code)\b", "", text, flags=re.I)
    is_code = bool(_ACTION.search(text) and _CODE.search(marker_text)
                   and not _NEGATED.search(text))
    if not is_code:
        return False, False
    # Source code is an artifact, not a request for external sources.
    intent = re.sub(r"\b(?:source\s+code|kode\s+sumber)\b", "code", text, flags=re.I)
    return True, bool(_EXTERNAL.search(intent))
