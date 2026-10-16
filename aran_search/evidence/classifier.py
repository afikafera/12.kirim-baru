import re


class Classifier:
    HEADING = re.compile(r'^#{1,4}\s+', re.MULTILINE)
    KV_LINE = re.compile(r'^([A-Za-z][\w\s/()-]{2,40})[:\s]{2,}(.+)$', re.MULTILINE)
    YOUTUBE_URL = re.compile(
        r'https?://(?:www\.)?(?:youtube\.com/watch\?[^\s]+|youtu\.be/[^\s]+)',
        re.IGNORECASE,
    )
    OFFICIAL_API = re.compile(
        r'^\s*\[[A-Z0-9_\s-]+OFFICIAL\s+API\]',
        re.MULTILINE | re.IGNORECASE,
    )
    CODE_URL_EXT = re.compile(
        r'\.(?:py|pyi|js|mjs|cjs|ts|tsx|jsx|go|rs|java|c|cc|cpp|cxx|h|hpp|cs|rb|php|sh|bash|zsh|kt|kts|swift|scala|lua|pl|r|sql|zig|ex|exs|erl|hs)(?:$|[?#])',
        re.IGNORECASE,
    )
    CODE_IMPORT = re.compile(
        r'^[ \t]*(?:'
        r'from\s+[A-Za-z_][\w.]*\s+import\s+[A-Za-z_*(]'
        r'|import\s+[A-Za-z_][\w.]*(?:\s+as\s+[A-Za-z_]\w*)?[ \t]*(?:#.*)?$'
        r'|import\s+(?:type\s+)?[\{*\"\']'
        r'|package\s+[a-zA-Z_][\w.]*\s*;?$'
        r'|using\s+[A-Za-z_][\w.]*\s*;$'
        r'|use\s+[a-zA-Z_][\w:{}*,\s]*;$'
        r'|#include\s+[<\"][^>\"]+[>\"]'
        r')',
        re.MULTILINE,
    )
    CODE_DECL = re.compile(
        r'^[ \t]{0,8}(?:'
        r'(?:async\s+)?def\s+[A-Za-z_]\w*\s*\('
        r'|class\s+[A-Za-z_]\w*\s*(?:\([^)]*\))?\s*:'
        r'|(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+[A-Za-z_]\w*\s*\('
        r'|(?:export\s+)?class\s+[A-Za-z_]\w*(?:\s+(?:extends|implements)\s+[A-Za-z_][\w.,\s<>]*)?\s*\{'
        r'|func\s+(?:\([^)]+\)\s*)?[A-Za-z_]\w*\s*\('
        r'|type\s+[A-Za-z_]\w*\s+(?:struct|interface)\s*\{'
        r'|(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+[A-Za-z_]\w*\s*[<\(]'
        r'|(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|impl)\b[^{;\n]*\{'
        r'|(?:(?:public|private|protected|internal|static|final|abstract|synchronized)\s+)+(?:class|interface|enum|struct|[A-Za-z_][\w<>\[\],?\s]*\s+[A-Za-z_]\w*\s*\()'
        r')',
        re.MULTILINE,
    )
    MD_SUBHEADING = re.compile(r'^#{2,4}\s+\S+', re.MULTILINE)
    MARKDOWN_LINK = re.compile(r'\[[^\]]+\]\([^)]+\)')

    def is_source_code(self, content: str, url: str = "") -> bool:
        if not content:
            return False
        stripped = content.lstrip()
        low_head = stripped[:200].lower()
        if low_head.startswith(("<!doctype html", "<html")):
            return False
        if stripped.startswith("{") and content.rstrip().endswith("}"):
            return False
        decls = len(self.CODE_DECL.findall(content))
        imports = len(self.CODE_IMPORT.findall(content))
        headings = len(self.HEADING.findall(content))
        markdown_links = len(self.MARKDOWN_LINK.findall(content))
        if decls == 0 and imports == 0 and headings >= 1 and markdown_links >= 3:
            return False
        if url and self.CODE_URL_EXT.search(url):
            return True
        if decls >= 2 or (decls >= 1 and imports >= 1):
            if "```" in content and len(self.MD_SUBHEADING.findall(content)) >= 2:
                return False
            return True
        return False

    def classify(self, content: str, url: str = "") -> str:
        if not content:
            return "general"
        if self.OFFICIAL_API.search(content):
            return "official_docs"
        if self.YOUTUBE_URL.search(content):
            return "video"
        if self.is_source_code(content, url=url):
            return "source_code"
        headings = len(self.HEADING.findall(content))
        kvs = len(self.KV_LINE.findall(content))
        if kvs >= 8:
            return "datasheet"
        if headings >= 4:
            return "documentation"
        if headings >= 1 and len(content) > 800:
            return "article"
        return "general"
