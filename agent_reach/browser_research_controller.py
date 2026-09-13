"""
Isolated browser research controller.

Scope:
- candidate URL exploration
- browser navigation
- LLM action selection
- observation collection

Does NOT replace:
- search
- fetch_url
- DocumentIntelligence
- fact extraction
- evidence validation
- SkillBridge
- SkillRouter
"""

import asyncio
import json
import logging
from typing import Any

from agent_reach.agent_browser_tool import AgentBrowserTool

logger = logging.getLogger(__name__)


class BrowserResearchController:
    """Synchronous research controller over the async agent-browser adapter."""

    ALLOWED_ACTIONS = {
        "open",
        "click",
        "back",
        "read",
        "stop",
    }

    def __init__(
        self,
        llm_analyzer,
        max_steps: int = 6,
    ):
        self.llm = llm_analyzer
        self.max_steps = max(1, int(max_steps))

    @staticmethod
    def _parse_action(content: str) -> dict:
        """Parse and strictly validate one browser action."""
        text = (content or "").strip()

        try:
            action = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("browser action is not valid JSON")
            action = json.loads(text[start:end + 1])

        if not isinstance(action, dict):
            raise ValueError("browser action must be an object")

        name = action.get("action")
        if name not in BrowserResearchController.ALLOWED_ACTIONS:
            raise ValueError(f"unsupported browser action: {name!r}")

        return action

    @staticmethod
    def _run(coro):
        """Run one browser coroutine from the synchronous Hermes boundary."""
        return asyncio.run(coro)

    def _decide(
        self,
        topic: str,
        need: str,
        candidates: list[str],
        snapshot: str,
        history: list[dict[str, Any]],
    ) -> dict:
        candidate_text = "\n".join(
            f"{idx}: {url}"
            for idx, url in enumerate(candidates)
        )

        history_text = json.dumps(
            history[-6:],
            ensure_ascii=False,
        )

        system_prompt = """You are the browser navigation controller for a research assistant.

Choose exactly ONE next browser action.

Allowed JSON actions:
{"action":"open","candidate":0}
{"action":"click","target":"e2"}
{"action":"back"}
{"action":"read"}
{"action":"stop","reason":"..."}

Rules:
- Use only the supplied candidates and snapshot.
- Prefer authoritative/relevant pages.
- Do not invent URLs or element references.
- Use click only with a visible snapshot reference.
- Use open only with a candidate index.
- Use read when the current page already appears relevant and its body should be collected.
- Use back when the current page is not useful and another candidate should be inspected.
- Stop when the available evidence is sufficient or no useful navigation remains.
- Return JSON only.
"""

        user_prompt = f"""Research topic:
{topic}

Research need:
{need}

Candidate URLs:
{candidate_text or "(none)"}

Current browser snapshot:
{snapshot or "(empty)"}

Recent browser history:
{history_text}

Return exactly one JSON action."""

        result = self.llm.analyze(
            system_prompt,
            user_prompt,
            temperature=0.0,
        )

        return self._parse_action(result.get("content", ""))

    def explore(
        self,
        topic: str,
        need: str,
        candidates: list[str],
        session: str,
    ) -> dict:
        """Explore candidates and return observations without altering evidence."""
        browser = AgentBrowserTool(default_session=session)
        history: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        current_snapshot = ""

        try:
            for step in range(1, self.max_steps + 1):
                action = self._decide(
                    topic=topic,
                    need=need,
                    candidates=candidates,
                    snapshot=current_snapshot,
                    history=history,
                )

                action_name = action["action"]

                if action_name == "open":
                    candidate_index = action.get("candidate")

                    if (
                        not isinstance(candidate_index, int)
                        or isinstance(candidate_index, bool)
                        or candidate_index < 0
                        or candidate_index >= len(candidates)
                    ):
                        raise ValueError(
                            f"invalid candidate index: {candidate_index!r}"
                        )

                    url = candidates[candidate_index]
                    ok, output = self._run(browser.open(url))

                    history.append({
                        "step": step,
                        "action": "open",
                        "candidate": candidate_index,
                        "url": url,
                        "ok": ok,
                    })

                    if not ok:
                        observations.append({
                            "step": step,
                            "type": "open_error",
                            "url": url,
                            "content": output,
                        })
                        current_snapshot = ""
                        continue

                    current_snapshot = self._run(
                        browser.snapshot(
                            interactive=True,
                            compact=True,
                        )
                    )

                    observations.append({
                        "step": step,
                        "type": "snapshot",
                        "url": url,
                        "content": current_snapshot,
                    })

                elif action_name == "click":
                    target = action.get("target")

                    if not isinstance(target, str) or not target.strip():
                        raise ValueError(
                            f"invalid click target: {target!r}"
                        )

                    ok, output = self._run(browser.click(target))

                    history.append({
                        "step": step,
                        "action": "click",
                        "target": target,
                        "ok": ok,
                    })

                    if ok:
                        current_snapshot = self._run(
                            browser.snapshot(
                                interactive=True,
                                compact=True,
                            )
                        )
                    else:
                        current_snapshot = ""

                    observations.append({
                        "step": step,
                        "type": "click",
                        "target": target,
                        "ok": ok,
                        "content": current_snapshot or output,
                    })

                elif action_name == "back":
                    ok, output = self._run(browser.back())

                    history.append({
                        "step": step,
                        "action": "back",
                        "ok": ok,
                    })

                    if ok:
                        current_snapshot = self._run(
                            browser.snapshot(
                                interactive=True,
                                compact=True,
                            )
                        )
                    else:
                        current_snapshot = ""

                    observations.append({
                        "step": step,
                        "type": "back",
                        "ok": ok,
                        "content": current_snapshot or output,
                    })

                elif action_name == "read":
                    text = self._run(browser.get_text("body"))

                    history.append({
                        "step": step,
                        "action": "read",
                    })

                    observations.append({
                        "step": step,
                        "type": "read",
                        "content": text,
                    })

                    current_snapshot = text

                elif action_name == "stop":
                    history.append({
                        "step": step,
                        "action": "stop",
                        "reason": action.get("reason", ""),
                    })
                    break

        finally:
            self._run(browser.close())

        return {
            "topic": topic,
            "need": need,
            "session": session,
            "steps": len(history),
            "history": history,
            "observations": observations,
        }
