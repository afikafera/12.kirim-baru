import base64
import binascii
import io
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _data_url_bytes(value: str):
    if not isinstance(value, str) or not value.startswith("data:") or "," not in value:
        return None

    header, payload = value.split(",", 1)
    if ";base64" not in header:
        return None

    try:
        return base64.b64decode(payload, validate=True), header[5:].split(";", 1)[0]
    except (ValueError, binascii.Error):
        return None


def _image_to_ocr(image_bytes: bytes) -> str:
    try:
        from agent_reach.ocr_extractor import OCRExtractor

        result = OCRExtractor(lang="en").extract(image_bytes)
        return result.text or ""
    except Exception as exc:
        logger.warning("[ATTACHMENT OCR] failed: %s", exc)
        return ""


def _content_parts(content: Any):
    text_parts = []
    image_urls = []

    if isinstance(content, str):
        if content.strip():
            text_parts.append(content.strip())
        return text_parts, image_urls

    if not isinstance(content, list):
        return text_parts, image_urls

    for item in content:
        if not isinstance(item, dict):
            continue

        item_type = item.get("type")

        if item_type in ("text", "input_text"):
            value = item.get("text", "")
            if isinstance(value, str) and value.strip():
                text_parts.append(value.strip())
            continue

        if item_type in ("image_url", "input_image"):
            image_url = item.get("image_url", "")
            if isinstance(image_url, dict):
                image_url = image_url.get("url", "")
            if isinstance(image_url, str) and image_url.strip():
                image_urls.append(image_url.strip())
            continue

    return text_parts, image_urls


def collect_attachments(message: dict, context_messages: list | None = None) -> dict:
    """Normalize OpenAI/Open WebUI attachment shapes without changing the request."""
    # The user prompt itself is not attachment evidence. Only explicit file
    # fields, image parts, and Open WebUI source_context are eligible.
    content = message.get("content", "")
    _, image_urls = _content_parts(content)
    text_parts = []
    files = message.get("files") or []

    if isinstance(files, dict):
        files = [files]

    if isinstance(files, list):
        for item in files:
            if not isinstance(item, dict):
                continue

            file_type = str(item.get("type") or "").lower()
            content_type = str(item.get("content_type") or item.get("mime_type") or "").lower()

            for key in ("content", "text", "source_context"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    text_parts.append(value.strip())

            url = item.get("url") or item.get("file_url")
            if isinstance(url, str) and url.strip():
                if file_type == "image" or content_type.startswith("image/"):
                    image_urls.append(url.strip())

    # Open WebUI commonly places extracted attachment context in a system message.
    # Only the explicit source_context payload is imported; the surrounding
    # system prompt is never treated as attachment evidence.
    context_messages = context_messages or []
    context_candidates = [
        message for message in context_messages
        if isinstance(message, dict)
        and isinstance(message.get("content", ""), str)
        and "<source_context>" in message.get("content", "")
    ]
    if context_candidates:
        raw = context_candidates[-1]["content"]
        marker = "<source_context>"
        end_marker = "</source_context>"
        start = 0
        while True:
            pos = raw.find(marker, start)
            if pos < 0:
                break
            end = raw.find(end_marker, pos + len(marker))
            if end < 0:
                break
            value = raw[pos + len(marker):end].strip()
            if value:
                text_parts.append(value)
            start = end + len(end_marker)

    ocr_parts = []
    resolved_images = []

    for url in image_urls:
        parsed = _data_url_bytes(url)
        if parsed:
            image_bytes, content_type = parsed
            ocr = _image_to_ocr(image_bytes)
            resolved_images.append({
                "url": url,
                "content_type": content_type,
                "bytes_available": True,
            })
            if ocr:
                ocr_parts.append(ocr)
            continue

        resolved_images.append({
            "url": url,
            "content_type": "",
            "bytes_available": False,
        })

    evidence = []
    if text_parts:
        evidence.append({
            "url": "openwebui://attachment/context",
            "content": "\n\n".join(text_parts),
            "doc_type": "user_attachment",
            "evidence_type": "user_attachment",
            "source_type": "user_attachment",
        })

    if ocr_parts:
        evidence.append({
            "url": "openwebui://attachment/image-ocr",
            "content": "\n\n".join(ocr_parts),
            "doc_type": "image_ocr",
            "evidence_type": "user_attachment",
            "source_type": "user_attachment",
        })

    logger.info(
        "[ATTACHMENT AUDIT] text=%d images=%d resolved_images=%d evidence=%d",
        len(text_parts),
        len(image_urls),
        sum(1 for item in resolved_images if item["bytes_available"]),
        len(evidence),
    )

    return {
        "text": "\n\n".join(text_parts + ocr_parts),
        "images": resolved_images,
        "evidence": evidence,
    }
