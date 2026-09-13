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

request_id = events[0].get("request_id", "unknown") if events else "unknown"

# ------------------------------------------------------------
# Hermes runtime lanes
# ------------------------------------------------------------

lanes = [
    {"id": "core", "label": "Hermes Core"},
    {"id": "tools", "label": "Search / Evidence"},
]

phases = [
    {
        "id": "planning",
        "label": "Planning",
        "fromCol": 0,
        "toCol": 1,
        "variant": "emphasis",
    },
    {
        "id": "execution",
        "label": "Search + Fetch",
        "fromCol": 2,
        "toCol": 4,
        "variant": "dashed",
    },
    {
        "id": "completion",
        "label": "Evaluation",
        "fromCol": 5,
        "toCol": 5,
        "variant": "default",
    },
]

groups = [
    {
        "id": "planner_loop",
        "label": "Planner / Iteration Loop",
        "lane": "core",
        "fromCol": 0,
        "toCol": 1,
        "variant": "emphasis",
    },
    {
        "id": "evidence_work",
        "label": "Evidence Acquisition",
        "lane": "tools",
        "fromCol": 2,
        "toCol": 4,
        "variant": "dashed",
    },
]

# ------------------------------------------------------------
# Fixed semantic nodes.
# Multiple trace events collapse into these runtime components.
# ------------------------------------------------------------

nodes = [
    {
        "id": "research_start",
        "lane": "core",
        "col": 0,
        "type": "external",
        "label": "Research Start",
        "sublabel": "incoming goal",
        "width": 132,
    },
    {
        "id": "planner",
        "lane": "core",
        "col": 1,
        "type": "backend",
        "label": "Planner",
        "sublabel": "requirements + iterations",
        "width": 132,
    },
    {
        "id": "search",
        "lane": "tools",
        "col": 2,
        "type": "cloud",
        "label": "Search",
        "sublabel": "web discovery",
        "width": 132,
    },
    {
        "id": "fetch",
        "lane": "tools",
        "col": 3,
        "type": "cloud",
        "label": "Fetch",
        "sublabel": "documents",
        "width": 132,
    },
    {
        "id": "extract",
        "lane": "tools",
        "col": 4,
        "type": "backend",
        "label": "Extract",
        "sublabel": "evidence extraction",
        "width": 132,
    },
    {
        "id": "iteration",
        "lane": "core",
        "col": 2,
        "type": "messagebus",
        "label": "Iteration Loop",
        "sublabel": "repeat until ready",
        "tag": "trace driven",
        "width": 132,
    },
    {
        "id": "evaluation",
        "lane": "core",
        "col": 5,
        "type": "backend",
        "label": "Evaluation",
        "sublabel": "facts + coverage",
        "width": 132,
    },
    {
        "id": "research_done",
        "lane": "core",
        "col": 4,
        "type": "messagebus",
        "label": "Research Done",
        "sublabel": "final pipeline result",
        "width": 132,
    },
]

# ------------------------------------------------------------
# Trace statistics
# ------------------------------------------------------------

iterations = []
for e in events:
    if e.get("event") == "iteration_start":
        iterations.append(e.get("payload", {}).get("iteration"))

iteration_done = next(
    (
        e for e in events
        if e.get("event") == "iteration_done"
    ),
    None,
)

research_done = next(
    (
        e for e in events
        if e.get("event") == "research_done"
    ),
    None,
)

search_count = sum(
    1 for e in events if e.get("event") == "search_start"
)

fetch_count = sum(
    1 for e in events if e.get("event") == "fetch_done"
)

extract_count = sum(
    1 for e in events if e.get("event") == "extract_start"
)

facts = (
    iteration_done.get("payload", {}).get("facts", 0)
    if iteration_done else 0
)

coverage = (
    iteration_done.get("payload", {}).get("coverage", 0)
    if iteration_done else 0
)

done_iterations = (
    research_done.get("payload", {}).get("iterations", len(iterations))
    if research_done else len(iterations)
)

# Add diagnostic information to labels without creating dozens of nodes.

nodes[2]["tag"] = f"{search_count} calls"
nodes[3]["tag"] = f"{fetch_count} batches"
nodes[4]["tag"] = f"{extract_count} start"

nodes[5]["sublabel"] = (
    f"{done_iterations} iterations"
)

nodes[6]["sublabel"] = (
    f"facts={facts}, coverage={coverage}"
)

# ------------------------------------------------------------
# Main execution path
# ------------------------------------------------------------

main_path = [
    "research_start",
    "planner",
    "search",
    "fetch",
    "extract",
    "iteration",
    "evaluation",
    "research_done",
]

edges = [
    {
        "id": "start-planner",
        "from": "research_start",
        "to": "planner",
        "label": "goal",
        "variant": "emphasis",
        "role": "main",
    },
    {
        "id": "planner-search",
        "from": "planner",
        "to": "search",
        "label": f"{len(iterations)} iterations",
        "variant": "default",
        "role": "main",
    },
    {
        "id": "search-fetch",
        "from": "search",
        "to": "fetch",
        "label": f"{search_count} searches",
        "variant": "default",
        "role": "main",
    },
    {
        "id": "fetch-extract",
        "from": "fetch",
        "to": "extract",
        "label": f"{fetch_count} fetch batches",
        "variant": "default",
        "role": "main",
    },
    {
        "id": "extract-iteration",
        "from": "extract",
        "to": "iteration",
        "label": "evidence",
        "variant": "dashed",
        "role": "return",
        "route": "auto",
    },
    {
        "id": "iteration-planner",
        "from": "iteration",
        "to": "planner",
        "label": "next iteration",
        "variant": "dashed",
        "role": "branch",
        "route": "auto",
    },
    {
        "id": "iteration-evaluation",
        "from": "iteration",
        "to": "evaluation",
        "label": f"facts={facts}, coverage={coverage}",
        "variant": "emphasis",
        "role": "main",
    },
    {
        "id": "evaluation-done",
        "from": "evaluation",
        "to": "research_done",
        "variant": "emphasis",
        "role": "main",
    },
]

# ------------------------------------------------------------
# Cards
# ------------------------------------------------------------

cards = [
    {
        "dot": "cyan",
        "title": "Trace Summary",
        "items": [
            f"request_id: {request_id}",
            f"iterations: {done_iterations}",
            f"search calls: {search_count}",
            f"fetch batches: {fetch_count}",
        ],
    },
    {
        "dot": "rose",
        "title": "Evidence Result",
        "items": [
            f"facts: {facts}",
            f"coverage: {coverage}",
            "Trace ended without extracted facts"
            if facts == 0
            else "Facts were extracted",
        ],
    },
]

output = {
    "schema_version": 2,
    "diagram_type": "workflow",
    "meta": {
        "title": f"Hermes Trace {request_id}",
        "animation": "trace",
        "visual_preset": "signal-flow",
        "quality_profile": "showcase",
    },
    "lanes": lanes,
    "phases": phases,
    "groups": groups,
    "mainPath": main_path,
    "semanticChecks": {"allowedRoots": ["research_start"], "allowedTerminals": ["research_done"]},
    "nodes": nodes,
    "edges": edges,
    "cards": cards,
}

dst.parent.mkdir(parents=True, exist_ok=True)

with dst.open("w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"request_id: {request_id}")
print(f"source_events: {len(events)}")
print(f"iterations: {done_iterations}")
print(f"search_calls: {search_count}")
print(f"fetch_batches: {fetch_count}")
print(f"facts: {facts}")
print(f"coverage: {coverage}")
print(f"output: {dst}")
