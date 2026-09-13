"""
Isolated asynchronous adapter untuk agent-browser CLI.

Tidak menggantikan BrowserTool berbasis Playwright.
Tidak mengubah searcher.py atau fetch_url().
"""

import asyncio
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class AgentBrowserTool:
    """Async wrapper untuk interactive agent-browser CLI."""

    def __init__(self, default_session: str = "default"):
        self.default_session = default_session

    async def _run(
        self,
        *args: str,
        timeout: float = 30.0,
    ) -> Tuple[int, str, str]:
        cmd = ["npx", "agent-browser", *args]
        proc = None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )

            return (
                proc.returncode,
                stdout.decode().strip(),
                stderr.decode().strip(),
            )

        except asyncio.TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass

            return (
                -1,
                "",
                f"Timeout ({timeout}s) executing: {' '.join(cmd)}",
            )

        except Exception as exc:
            logger.exception("[AgentBrowserTool] command failed")
            return -1, "", str(exc)

    async def open(
        self,
        url: str,
        session: Optional[str] = None,
    ) -> Tuple[bool, str]:
        session_name = session or self.default_session

        rc, out, err = await self._run(
            "--session-name",
            session_name,
            "open",
            url,
            timeout=25.0,
        )

        if rc != 0:
            logger.warning(
                "[AgentBrowserTool] open failed url=%s err=%s",
                url,
                err,
            )
            return False, err

        return True, out

    async def snapshot(
        self,
        interactive: bool = True,
        compact: bool = True,
        session: Optional[str] = None,
    ) -> str:
        session_name = session or self.default_session

        args = [
            "--session-name",
            session_name,
            "snapshot",
        ]

        if interactive:
            args.append("-i")

        if compact:
            args.append("-c")

        rc, out, err = await self._run(
            *args,
            timeout=15.0,
        )

        if rc != 0:
            return f"Error snapshot: {err}"

        return out

    async def click(
        self,
        ref_or_selector: str,
        session: Optional[str] = None,
    ) -> Tuple[bool, str]:
        session_name = session or self.default_session

        rc, out, err = await self._run(
            "--session-name",
            session_name,
            "click",
            ref_or_selector,
            timeout=15.0,
        )

        return rc == 0, out if rc == 0 else err

    async def get_text(
        self,
        selector: str = "body",
        session: Optional[str] = None,
    ) -> str:
        session_name = session or self.default_session

        rc, out, err = await self._run(
            "--session-name",
            session_name,
            "get",
            "text",
            selector,
            timeout=15.0,
        )

        if rc != 0:
            return f"Error get text: {err}"

        return out

    async def back(
        self,
        session: Optional[str] = None,
    ) -> Tuple[bool, str]:
        session_name = session or self.default_session

        rc, out, err = await self._run(
            "--session-name",
            session_name,
            "back",
            timeout=15.0,
        )

        return rc == 0, out if rc == 0 else err

    async def close(
        self,
        session: Optional[str] = None,
        all_sessions: bool = False,
    ) -> None:
        if all_sessions:
            await self._run(
                "close",
                "--all",
                timeout=10.0,
            )
            return

        session_name = session or self.default_session

        await self._run(
            "--session-name",
            session_name,
            "close",
            timeout=10.0,
        )
