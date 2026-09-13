import json
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])

events = []
with src.open() as f:
    for line in f:
        line = line.strip()
        if line:
            events.append(json.loads(line))

participants = [
    {"id": "hermes", "type": "backend", "label": "Hermes"},
    {"id": "planner", "type": "backend", "label": "Planner"},
    {"id": "search", "type": "external", "label": "Search"},
    {"id": "fetch", "type": "external", "label": "Fetch"},
    {"id": "extract", "type": "backend", "label": "Extract"},
]

event_map = {
    "research_start": ("hermes", "planner"),
    "planner_done": ("planner", "hermes"),
    "iteration_start": ("hermes", "planner"),
    "search_start": ("hermes", "search"),
    "search_done": ("search", "hermes"),
    "fetch_done": ("fetch", "hermes"),
    "extract_start": ("hermes", "extract"),
    "iteration_done": ("planner", "hermes"),
    "research_done": ("planner", "hermes"),
}

messages = []
y = 180

for n, event in enumerate(events, 1):
    kind = event.get("event")
    mapping = event_map.get(kind)

    if not mapping:
        continue

    src_id, dst_id = mapping
    payload = event.get("payload", {})

    label = kind

    if kind == "search_start":
        topic = payload.get("topic", "")
        label = f"search: {topic[:45]}"
    elif kind == "search_done":
        label = f"search_done ({payload.get('urls', 0)} urls)"
    elif kind == "fetch_done":
        label = (
            f"fetch_done "
            f"({payload.get('documents_fetched', 0)} docs)"
        )
    elif kind == "iteration_start":
        label = f"iteration {payload.get('iteration')}"
    elif kind == "iteration_done":
        label = (
            f"iteration_done "
            f"facts={payload.get('facts', 0)} "
            f"coverage={payload.get('coverage', 0)}"
        )
    elif kind == "research_done":
        label = (
            f"research_done "
            f"{payload.get('iterations', '?')} iterations"
        )

    messages.append({
        "id": f"m{n}",
        "from": src_id,
        "to": dst_id,
        "y": y,
        "label": label
    })

    y += 70

request_id = (
    events[0].get("request_id", "unknown")
    if events else "unknown"
)

output = {
    "schema_version": 1,
    "diagram_type": "sequence",
    "meta": {
        "title": f"Hermes Trace {request_id}",
        "quality_profile": "showcase",
        "animation": "trace"
    },
    "participants": participants,
    "messages": messages
}

dst.parent.mkdir(parents=True, exist_ok=True)

with dst.open("w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"request_id: {request_id}")
print(f"source_events: {len(events)}")
print(f"sequence_messages: {len(messages)}")
print(f"output: {dst}")
