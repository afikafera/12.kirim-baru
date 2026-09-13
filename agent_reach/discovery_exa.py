"""
agent_reach/discovery_exa.py
Isolated Discovery Tool untuk Exa via CLI mcporter.
Menyediakan interface pencarian berkualitas tinggi tanpa blocking.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExaResult:
    title: str
    url: str
    published: Optional[str]
    author: Optional[str]
    highlights: str


class ExaDiscoveryTool:
    """Wrapper non-blocking untuk memanggil exa.web_search_exa via mcporter."""

    def __init__(self, timeout: float = 25.0):
        self.timeout = max(5.0, float(timeout))

    async def search(self, query: str, num_results: int = 5) -> list[ExaResult]:
        cmd = [
            "mcporter", "call", "exa.web_search_exa",
            f"query={query}",
            f"numResults={int(num_results)}"
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
            if proc.returncode != 0:
                logger.error(
                    "[ExaDiscovery] mcporter error (rc=%d): %s",
                    proc.returncode,
                    stderr.decode().strip()
                )
                return []
            return self._parse_output(stdout.decode())
        except asyncio.TimeoutError:
            logger.warning("[ExaDiscovery] Timeout (%ds) query=%r", self.timeout, query)
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return []
        except Exception as e:
            logger.error("[ExaDiscovery] Execution failed: %s", e)
            return []

    @staticmethod
    def _parse_output(raw_text: str) -> list[ExaResult]:
        results = []
        blocks = raw_text.split("\n---\n")
        for block in blocks:
            lines = block.strip().splitlines()
            if not lines:
                continue

            title = ""
            url = ""
            published = None
            author = None
            highlights_lines = []
            is_highlight = False

            for line in lines:
                if line.startswith("Title: "):
                    title = line[7:].strip()
                elif line.startswith("URL: "):
                    url = line[5:].strip()
                elif line.startswith("Published: "):
                    pub = line[11:].strip()
                    published = pub if pub != "N/A" else None
                elif line.startswith("Author: "):
                    auth = line[8:].strip()
                    author = auth if auth != "N/A" else None
                elif line.startswith("Highlights:"):
                    is_highlight = True
                elif is_highlight:
                    cleaned = line.strip()
                    if cleaned and cleaned != "...":
                        highlights_lines.append(cleaned)

            if url:
                results.append(ExaResult(
                    title=title or "Untitled",
                    url=url,
                    published=published,
                    author=author,
                    highlights="\n".join(highlights_lines)
                ))
        return results
