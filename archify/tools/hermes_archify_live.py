#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path("/home/arman/research-assistant")
TRACE = Path("/tmp/hermes_events.jsonl")

TRACE_TO_WORKFLOW = ROOT / "archify/tools/hermes_trace_to_workflow.py"
OUTPUT = ROOT / "archify/input/live.workflow.json"

POLL_SECONDS = 0.5


def read_events():
    if not TRACE.exists():
        return []

    events = []

    with TRACE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # Hermes mungkin sedang menulis line.
                continue

    return events


def latest_request(events):
    for event in reversed(events):
        request_id = event.get("request_id")

        if request_id:
            return request_id

    return None


def extract_request(events, request_id):
    return [
        e for e in events
        if e.get("request_id") == request_id
    ]


def atomic_write_jsonl(events):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=".hermes-live-",
        suffix=".jsonl",
        dir=str(OUTPUT.parent),
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for event in events:
                json.dump(
                    event,
                    f,
                    ensure_ascii=False,
                )
                f.write("\n")

            f.flush()
            os.fsync(f.fileno())

        return Path(tmp_name)

    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def generate(events, request_id):
    if not events:
        return

    tmp_jsonl = atomic_write_jsonl(events)

    try:
        tmp_output = OUTPUT.with_suffix(".tmp.workflow.json")

        cmd = [
            sys.executable,
            str(TRACE_TO_WORKFLOW),
            str(tmp_jsonl),
            str(tmp_output),
        ]

        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(
                f"[ARCHIFY LIVE] generator failed request={request_id}",
                flush=True,
            )

            if result.stderr:
                print(result.stderr[-2000:], flush=True)

            return

        if not tmp_output.exists():
            print(
                "[ARCHIFY LIVE] generator produced no workflow",
                flush=True,
            )
            return

        # Atomic publish.
        os.replace(tmp_output, OUTPUT)

        print(
            f"[ARCHIFY LIVE] updated request={request_id} "
            f"events={len(events)}",
            flush=True,
        )

        if result.stdout:
            print(
                result.stdout.strip(),
                flush=True,
            )

    finally:
        try:
            tmp_jsonl.unlink()
        except OSError:
            pass


def main():
    print("========================================")
    print(" Hermes → Archify Live Bridge")
    print("========================================")
    print(f"Trace   : {TRACE}")
    print(f"Output  : {OUTPUT}")
    print(f"Poll    : {POLL_SECONDS}s")
    print("")

    last_signature = None
    last_request = None

    while True:
        try:
            stat = TRACE.stat()
            signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)

            if signature != last_signature:
                events = read_events()
                request_id = latest_request(events)

                if request_id:
                    request_events = extract_request(
                        events,
                        request_id,
                    )

                    # Jangan regenerate kalau event belum berubah.
                    request_signature = (
                        request_id,
                        len(request_events),
                        request_events[-1].get("event")
                        if request_events
                        else None,
                        request_events[-1].get("ts")
                        if request_events
                        else None,
                    )

                    if request_signature != last_request:
                        generate(
                            request_events,
                            request_id,
                        )
                        last_request = request_signature

                last_signature = signature

            time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            print("\n[ARCHIFY LIVE] stopped")
            break

        except FileNotFoundError:
            time.sleep(POLL_SECONDS)

        except Exception as e:
            print(
                f"[ARCHIFY LIVE] error: {e}",
                flush=True,
            )
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
