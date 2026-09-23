"""Shared fetch-result classification for Aran Search and Agent-Reach."""
from __future__ import annotations

import json
import re
from enum import Enum


class FetchClass(str, Enum):
    SUCCESS = "SUCCESS"
    BLOCK = "BLOCK"
    JS_REQUIRED = "JS_REQUIRED"
    BROWSER_REQUIRED = "BROWSER_REQUIRED"
    HTTP_ERROR = "HTTP_ERROR"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    NOT_FOUND = "NOT_FOUND"
    NETWORK_ERROR = "NETWORK_ERROR"


_STATUS_MARKER = re.compile(r"\n__FETCH_HTTP_STATUS__:(\d{3})\s*$")
_CHALLENGE_MARKERS = (
    "cloudflare",
    "cf-chl-",
    "just a moment...",
    "verify you are human",
    "performing security verification",
    "anubis",
    "bot verification",
    "access denied",
)
_JS_MARKERS = (
    "enable javascript",
    "javascript is required",
    "javascript required",
    "please enable cookies",
)


def split_http_status(raw: str) -> tuple[str, int | None]:
    text = raw or ""
    match = _STATUS_MARKER.search(text)
    if not match:
        return text, None
    body = text[:match.start()]
    return body, int(match.group(1))


def classify_fetch_result(
    text: str,
    http_status: int | None = None,
) -> FetchClass:
    body = (text or "").strip()
    lowered = body.lower()

    if http_status == 404:
        return FetchClass.NOT_FOUND
    if http_status in (401, 407):
        return FetchClass.AUTH_REQUIRED
    if http_status is not None and http_status >= 400:
        if any(marker in lowered for marker in _CHALLENGE_MARKERS):
            return FetchClass.BLOCK
        return FetchClass.HTTP_ERROR

    if not body:
        return FetchClass.NETWORK_ERROR
    if lowered.startswith("error fetch:") or lowered.startswith("error:"):
        return FetchClass.NETWORK_ERROR
    if any(marker in lowered for marker in _CHALLENGE_MARKERS):
        return FetchClass.BLOCK
    if any(marker in lowered for marker in _JS_MARKERS):
        return FetchClass.JS_REQUIRED
    return FetchClass.SUCCESS


def validate_github_response(
    body: str,
    http_status: int | None,
) -> tuple[bool, str]:
    if http_status is not None and http_status >= 400:
        return False, f"HTTP_{http_status}"

    try:
        payload = json.loads(body or "")
    except json.JSONDecodeError:
        return False, "INVALID_JSON"

    if isinstance(payload, dict) and payload.get("message"):
        return False, str(payload["message"])
    return True, "OK"
