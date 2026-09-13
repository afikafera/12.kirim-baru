from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import sys
import uuid
sys.path.insert(0, "/home/arman/research-assistant")

from config import load_config

config = load_config()

from memory_manager.manager import MemoryManager
from calibration.calibrator import ConfidenceCalibrator
from llm_analyzer.analyzer import LLMAnalyzer
from outcome_logger.logger import OutcomeLogger
from lessons_engine.engine import LessonsEngine
from hermes_agent.orchestrator import HermesAgent

app = FastAPI(title="Technical Research Assistant")
mm = MemoryManager(config)
cal = ConfidenceCalibrator(mm)
llm = LLMAnalyzer(config)
outcome_logger = OutcomeLogger(mm, cal)
lessons_engine = LessonsEngine(mm, llm)
hermes = HermesAgent(mm, cal, llm, outcome_logger, lessons_engine)


class ResearchRequest(BaseModel):
    query: str
    model: str = None


class OutcomeRequest(BaseModel):
    research_id: str
    status: str
    raw_confidence: float = 0.85
    domain: str = "global"
    user_feedback: str = None
    execution_cost: float = None
    usefulness_rating: int = None
    api_cost: float = None


class ProjectCreate(BaseModel):
    name: str
    slug: str
    description: str = None
    tags: list = []


@app.get("/")
def root():
    return {"app": "Technical Research Assistant", "version": "2.0"}


@app.post("/research")
def research(req: ResearchRequest):
    with llm.use_model(req.model):
        result = hermes.research(req.query)
    return result


@app.get("/research/{research_id}")
def get_research(research_id: str):
    r = mm.get_research(research_id)
    if not r:
        raise HTTPException(404, "Research not found")
    return {"id": r["id"], "query": r["query_text"], "summary": r["summary"],
            "confidence_raw": r["confidence_score_raw"],
            "confidence_calibrated": r["confidence_score_calibrated"]}


@app.post("/outcome")
def log_outcome(req: OutcomeRequest):
    r = mm.get_research(req.research_id)
    if not r:
        raise HTTPException(404, "Research not found")
    api_cost = req.api_cost or r.get("api_cost", 0)
    result = outcome_logger.log_outcome(
        req.research_id, req.status, req.raw_confidence,
        req.domain, req.user_feedback, req.execution_cost,
        req.usefulness_rating, api_cost
    )
    return result


@app.post("/projects")
def create_project(req: ProjectCreate):
    p = mm.create_project(req.name, req.slug, req.description, req.tags)
    return p


@app.get("/projects")
def list_projects():
    return mm.list_projects()


@app.get("/projects/{slug}")
def get_project(slug: str):
    p = mm.get_project(slug)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


@app.post("/lessons/generate")
def generate_lessons(project_id: str = None):
    lessons = lessons_engine.generate_lessons(project_id)
    return {"lessons": lessons}


@app.get("/lessons")
def get_lessons(project_id: str = None):
    return lessons_engine.get_active_lessons(project_id)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/models")
@app.get("/models")
def list_models():
    model_ids = sorted(llm.providers.keys()) if hasattr(llm, "providers") and llm.providers else ["deepseek-chat"]
    return {
        "object": "list",
        "data": [
            {"id": model_id, "object": "model"}
            for model_id in model_ids
        ]
    }


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat_completions(request: dict):
    messages = request.get("messages", [])
    model = request.get("model")
    print(f"[MODEL] requested={model!r}", flush=True)

    req_id = uuid.uuid4().hex[:8]
    print(f"[REQ {req_id}] START", flush=True)

    import json

    print("=" * 80)
    print("RAW REQUEST MESSAGES")
    print(json.dumps(messages, indent=2, ensure_ascii=False))
    print("=" * 80)

    from hermes_agent.attachment_handler import collect_attachments

    last_message = messages[-1] if messages else {}
    raw_user_content = last_message.get("content", "") if isinstance(last_message, dict) else ""
    attachment_bundle = (
        collect_attachments(last_message, context_messages=messages)
        if isinstance(last_message, dict)
        else {"text": "", "images": [], "evidence": []}
    )

    if isinstance(raw_user_content, str):
        user_msg = raw_user_content
    elif isinstance(raw_user_content, list):
        user_msg = "\n".join(
            item.get("text", "")
            for item in raw_user_content
            if isinstance(item, dict) and item.get("type") in ("text", "input_text")
            and isinstance(item.get("text", ""), str)
        ).strip()
    else:
        user_msg = ""

    print("USER_MSG =", repr(user_msg))
    print(
        f"[ATTACHMENT INPUT] evidence={len(attachment_bundle['evidence'])} "
        f"images={len(attachment_bundle['images'])}",
        flush=True,
    )
    print("=" * 80)

    
    import json
    import logging

    logging.getLogger("api.debug").info(
        "RAW_MESSAGES=%s",
        json.dumps(messages, ensure_ascii=False)
    )
    logging.getLogger("api.debug").info(
        "USER_MSG=%r",
        user_msg
    )


    # ---- Open WebUI internal tasks ----
    # Open WebUI mengirim task internal seperti chat tagging.
    # Task ini bukan research request dan tidak boleh masuk Hermes pipeline.
    if (
        user_msg.startswith("### Task:")
        and "Generate 1-3 broad tags categorizing the main themes" in user_msg
        and "JSON format" in user_msg
        and "<chat_history>" in user_msg
    ):
        with llm.use_model(model):
            tag_result = hermes.llm.analyze(
                system_prompt=(
                    "You are an Open WebUI chat-tagging assistant. "
                    "Follow the user's task exactly. "
                    "Return ONLY the requested JSON object. "
                    "Do not search the web. "
                    "Do not perform research."
                ),
                user_query=user_msg,
                temperature=0.1,
            )

        return {
            "id": "chat-tags",
            "object": "chat.completion",
            "model": model or llm.default_model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": tag_result["content"],
                },
                "finish_reason": "stop",
            }],
        }

    # ---- Open WebUI Autocomplete ----
    if (
        user_msg.startswith("### Task:")
        and "autocompletion system" in user_msg.lower()
        and "<text>" in user_msg
        and "<type>" in user_msg
    ):
        print(f"[REQ {req_id}] END autocomplete", flush=True)
        return {
            "id": "autocomplete",
            "object": "chat.completion",
            "model": model or llm.default_model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": ""
                },
                "finish_reason": "stop"
            }]
        }

    # ---- Open WebUI Title Generation ----
    # Title generation is an internal UI task, not a research request.
    if (
        user_msg.startswith("### Task:")
        and "Generate a concise, 3-5 word title" in user_msg
        and "JSON format" in user_msg
        and "<chat_history>" in user_msg
    ):
        with llm.use_model(model):
            title_result = hermes.llm.analyze(
                system_prompt=(
                    "You are an Open WebUI chat-title assistant. "
                    "Follow the user's task exactly. "
                    "Return ONLY the requested JSON object. "
                    "Do not search the web. "
                    "Do not perform research."
                ),
                user_query=user_msg,
                temperature=0.1,
            )

        print(f"[REQ {req_id}] END title", flush=True)

        return {
            "id": "chat-title",
            "object": "chat.completion",
            "model": model or llm.default_model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": title_result["content"],
                },
                "finish_reason": "stop",
            }],
        }

    # ---- Open WebUI unknown internal tasks ----
    # Future Open WebUI tasks not covered by the explicit handlers above
    # must not enter the Hermes research pipeline.
    if user_msg.startswith("### Task:"):
        print(f"[REQ {req_id}] generic webui internal task", flush=True)

        with llm.use_model(model):
            task_result = hermes.llm.analyze(
                system_prompt=(
                    "You are an Open WebUI internal task assistant. "
                    "Follow the task exactly. "
                    "Return only the requested output. "
                    "Do not search the web. "
                    "Do not perform research."
                ),
                user_query=user_msg,
                temperature=0.1,
            )

        print(
            f"[REQ {req_id}] END webui internal task",
            flush=True,
        )

        return {
            "id": "webui-task",
            "object": "chat.completion",
            "model": model or llm.default_model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": task_result["content"],
                },
                "finish_reason": "stop",
            }],
        }

    # ---- Conversation Context ----
    # Open WebUI sends the full conversation in `messages`.
    # Internal tasks above must continue using only their own task payload.
    # Normal research requests receive the conversation history as context.
    conversation_parts = []

    for message in messages:
        role = message.get("role", "unknown")
        content = message.get("content", "")

        if isinstance(content, str) and content.strip():
            conversation_parts.append(
                f"{role.upper()}: {content}"
            )
            continue

        if isinstance(content, list):
            text_parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict)
                and item.get("type") in ("text", "input_text")
                and isinstance(item.get("text", ""), str)
                and item.get("text", "").strip()
            ]
            if text_parts:
                conversation_parts.append(
                    f"{role.upper()}: {' '.join(text_parts)}"
                )

    conversation_context = "\n\n".join(conversation_parts[:-1])

    if not conversation_context:
        conversation_context = ""

    print(
        f"[CONTEXT] messages={len(messages)} "
        f"research_chars={len(conversation_context)}",
        flush=True,
    )

    from langfuse import get_client

    langfuse = get_client()
    with langfuse.start_as_current_observation(
        as_type="span",
        name="hermes-research",
        input={"request_id": req_id},
    ):
        with llm.use_model(model):
            result = hermes.research(
                user_msg,
                context=conversation_context,
                attachments=attachment_bundle["evidence"],
            )

    if isinstance(result, str):
        result = {
            "goal": "chat",
            "answer": result,
        }
    elif result is None:
        print(
            f"[REQ {req_id}] WARNING: hermes.research returned None",
            flush=True,
        )
        result = {
            "goal": "chat",
            "answer": "",
        }

    print(f"[REQ {req_id}] END research", flush=True)
    return {
        "id": result.get("goal", "chat"),
        "object": "chat.completion",
        "model": model or llm.default_model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": result.get("answer", "")},
            "finish_reason": "stop"
        }]
    }
