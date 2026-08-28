import json
import uuid
import contextvars
from pathlib import Path
from datetime import datetime
from threading import Lock

_LOG = Path("/tmp/hermes_events.jsonl")
_LOCK = Lock()

_REQUEST_ID = contextvars.ContextVar(
    "request_id",
    default=None,
)


def init_request_id(req_id=None):
    if req_id is None:
        req_id = uuid.uuid4().hex[:12]
    _REQUEST_ID.set(req_id)
    return req_id


def log_event(event: str, payload=None, request_id=None):
    active_request_id = request_id or _REQUEST_ID.get()

    if payload is None:
        payload = {}

    row = {
        "ts": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        "event": event,
        "request_id": active_request_id,
        "payload": payload,
    }

    with _LOCK:
        print("[JSONL] lock", flush=True)
        with _LOG.open("a", encoding="utf-8") as f:
            print(f"[JSONL] open {_LOG}", flush=True)
            json.dump(row, f, ensure_ascii=False)
            print("[JSONL] dumped", flush=True)
            f.write("\n")
            print("[JSONL] newline", flush=True)
            f.flush()
            print("[JSONL] flushed", flush=True)


def get_request_id():
    rid = _REQUEST_ID.get()
    if rid is None:
        rid = init_request_id()
    return rid
