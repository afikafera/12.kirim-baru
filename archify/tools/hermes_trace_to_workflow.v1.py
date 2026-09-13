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

nodes = []
edges = []

def add_node(node_id, label, kind="process", detail=None):
    node = {
        "id": node_id,
        "label": label,
        "kind": kind,
    }
    if detail:
        node["detail"] = detail
    nodes.append(node)

def add_edge(edge_id, source, target, label=None):
    edge = {
        "id": edge_id,
        "source": source,
        "target": target,
    }
    if label:
        edge["label"] = label
    edges.append(edge)

add_node("start", "Research Start", "start")
add_node("planner", "Planner", "process")

last_node = "planner"
iteration_nodes = {}

for event in events:
    kind = event.get("event")
    payload = event.get("payload", {})
    event_no = len(nodes)

    if kind == "planner_done":
        add_node(
            "planner_done",
            f"Planner Done",
            "process",
            f"confidence={payload.get('confidence')}, "
            f"requirements={payload.get('requirements')}",
        )
        add_edge("e_planner_done", "planner", "planner_done")
        last_node = "planner_done"

    elif kind == "iteration_start":
        iteration = payload.get("iteration")
        node_id = f"iteration_{iteration}"

        add_node(
            node_id,
            f"Iteration {iteration}",
            "group",
            f"ready_nodes={payload.get('ready_nodes')}",
        )

        add_edge(
            f"e_iteration_{iteration}",
            last_node,
            node_id,
        )

        iteration_nodes[iteration] = node_id
        last_node = node_id

    elif kind == "search_start":
        topic = payload.get("topic", "")
        node_id = f"search_{len([n for n in nodes if n['id'].startswith('search_')]) + 1}"

        add_node(
            node_id,
            "Search",
            "process",
            topic,
        )

        add_edge(
            f"e_{node_id}",
            last_node,
            node_id,
            topic[:60],
        )

        last_node = node_id

    elif kind == "search_done":
        node_id = f"search_done_{len([n for n in nodes if n['id'].startswith('search_done_')]) + 1}"

        add_node(
            node_id,
            "Search Done",
            "result",
            f"urls={payload.get('urls')}",
        )

        add_edge(
            f"e_{node_id}",
            last_node,
            node_id,
        )

        last_node = node_id

    elif kind == "fetch_done":
        node_id = f"fetch_{len([n for n in nodes if n['id'].startswith('fetch_')]) + 1}"

        add_node(
            node_id,
            "Fetch",
            "process",
            f"requested={payload.get('urls_requested')}, "
            f"new={payload.get('urls_new')}, "
            f"documents={payload.get('documents_fetched')}",
        )

        add_edge(
            f"e_{node_id}",
            last_node,
            node_id,
        )

        last_node = node_id

    elif kind == "extract_start":
        node_id = "extract"

        if not any(n["id"] == node_id for n in nodes):
            add_node(
                node_id,
                "Evidence Extract",
                "process",
                f"topic={payload.get('topic')}, "
                f"documents={payload.get('documents')}",
            )

        add_edge(
            f"e_extract_{len(edges)}",
            last_node,
            node_id,
        )

        last_node = node_id

    elif kind == "iteration_done":
        iteration_done = f"iteration_done_{len([n for n in nodes if n['id'].startswith('iteration_done_')]) + 1}"

        add_node(
            iteration_done,
            "Iteration Done",
            "result",
            f"facts={payload.get('facts')}, "
            f"coverage={payload.get('coverage')}",
        )

        add_edge(
            f"e_{iteration_done}",
            last_node,
            iteration_done,
        )

        last_node = iteration_done

    elif kind == "research_done":
        add_node(
            "research_done",
            "Research Done",
            "end",
            f"iterations={payload.get('iterations')}, "
            f"facts={payload.get('facts')}, "
            f"duration_ms={payload.get('duration_ms')}",
        )

        add_edge(
            "e_research_done",
            last_node,
            "research_done",
        )

        last_node = "research_done"

output = {
    "schema_version": 1,
    "diagram_type": "workflow",
    "meta": {
        "title": f"Hermes Research Trace {request_id}",
        "description": "Execution flow generated from Hermes JSONL trace",
        "quality_profile": "showcase",
    },
    "nodes": nodes,
    "edges": edges,
}

dst.parent.mkdir(parents=True, exist_ok=True)

with dst.open("w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"request_id: {request_id}")
print(f"source_events: {len(events)}")
print(f"nodes: {len(nodes)}")
print(f"edges: {len(edges)}")
print(f"output: {dst}")
