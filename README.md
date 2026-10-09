# ARAN

## Overview

ARAN is the user-facing name of this research and chat service. Its current implementation is a FastAPI application backed by the `hermes_agent` runtime. The custom UI is branded ARAN; API metadata, service names, logs, and internal packages still use Hermes/Technical Research Assistant terminology. The rename is transitional.

## Architecture

```text
ARAN UI / OpenAI-compatible chat API
                  |
          FastAPI: api.main:app
                  |
          HermesAgent core
                  |
          SkillRouter -> SkillBridge
                  |
   Current search executor: AgentReachSearcher
                  |
       Exa discovery -> SearXNG fallback
                  |
    fetch/connectors -> DocumentIntelligence
       -> evidence checks -> FactChecker
       -> answer synthesis
```

**Current:** the active search executor calls `AgentReachSearcher` in
`aran_search/searcher.py`. `SearchGateway` exists in the repository but is not
wired into the active executor. Qdrant is configured as a backend, but vector
retrieval is not part of the active research request path.

**Target:** the search migration proposes routing the active executor through
`SearchGateway`. Treat that as unfinished until the runtime wiring and relevant
regression tests pass. The target does not establish active RAG or vector search.

## Main Components

- `api/` — FastAPI app, session authentication, model-list response, and UI routes.
- `hermes_agent/` — research orchestration, planner, skill bridge, evidence/fact handling, and section continuation.
- `aran_search/` — search/fetch adapters, connectors, evidence classification and normalization.
- `memory_manager/` — PostgreSQL and Qdrant adapters.
- `ui/` — ARAN login and chat pages plus browser assets.
- `migrations/` — SQL migrations; the chat migration is applied manually.
- `deploy/` — systemd and Caddy configuration.
- `tests/` — unit and integration tests; additional regression harnesses live at the repository root.

## Request / Research Flow

The main entry point is `api.main:app`. `/v1/chat/completions` and `/chat/completions` accept OpenAI-compatible chat requests. The chat handler collects supported attachment context, builds conversation context, selects the requested provider, and calls `HermesAgent.research()`. A successful user exchange is persisted with its conversation.

`POST /research` is a synchronous research route. `GET /research/{research_id}` retrieves a stored result; there is no separate asynchronous research-status endpoint in the current API.

## Search Flow

**Current:** `SkillRouter` selects the search capability and `SkillBridge`
executes it through `AgentReachSearcher`. Search tries Exa discovery and can
fall back to local SearXNG. URL fetching is separate and uses connectors and
fetch validation, with Jina/browser fallback paths where applicable. Retrieved
material passes through `DocumentIntelligence`, evidence checks, and fact
extraction before synthesis.

**Target:** `SearchGateway` is present but not connected to the active skill
executor. Do not treat it as the current search path. Vector retrieval/RAG is
also not wired into the active research path.

## Models / Providers

The model list is built from configured provider IDs and exposed by `/models` and `/v1/models`; credentials and provider configuration are not returned. The current deployment configuration resolves these IDs to upstream models:

| Provider ID | Configured upstream model |
|---|---|
| `9routerpc` (default) | `opencode_free` |
| `omniroute` | `combo-free` |
| `poolside` | `poolside/laguna-s-2.1` |
| `deepseek-chat` | `deepseek-chat` |

Configuration is dynamic through `LLM_PROVIDER_<NAME>_*`. These values show what is configured, not that every provider has a successful live request. The 9Router combo / `mimo-auto` behavior is not verified by the active tests or configuration inspected here.

## Web UI

The custom UI is served by the FastAPI app: `/login`, `/app`, and `/static/*`. Its visible name is ARAN. The implementation is present, but full browser end-to-end behavior is not verified; UI status is PARTIAL. An Open WebUI container is also defined in `docker-compose.yml`; the API includes Open WebUI-compatible chat routes and handles its internal chat tasks.

## Authentication

`api/auth.py` implements single-account login using a configured scrypt password hash and opaque, process-local sessions. The active `api/auth.py` source sets session cookies with `httponly=True` and `samesite="strict"` (SameSite=Strict). With `HERMES_SESSION_COOKIE_SECURE=true`, requests require HTTPS. Sessions are held in memory and are invalidated when the API process restarts. The production unit reads authentication settings from `/etc/hermes/auth.env`.

## Conversation Persistence

Conversations and messages are owner-scoped in PostgreSQL. Message content is stored as JSONB. `migrations/001_create_chat_persistence.sql` defines the chat tables and indexes; its comment explicitly says to apply it manually, not during app startup.

Qdrant is initialized as a vector backend, but the active research orchestrator does not call the `MemoryManager.semantic_search()` or `upsert_embedding()` methods. RAG retrieval should therefore be treated as open, not as an active request-flow capability.

## Setup

The current host uses an existing Python environment at `./venv` (Python 3.10). The repository has no root `requirements.txt`, `pyproject.toml`, or other complete dependency-install manifest, so a fresh-clone installation procedure is not established.

For the existing environment:

```bash
cd ~/research-assistant
source venv/bin/activate
```

## Environment

`config.py` loads the repository `.env`. Do not put secret values in this README. Source/configuration names include:

- Providers: `LLM_DEFAULT_MODEL`, `LLM_MODEL`, `LLM_PROVIDER_<NAME>_API_KEY`, `LLM_PROVIDER_<NAME>_BASE_URL`, `LLM_PROVIDER_<NAME>_MODEL`, `LLM_PROVIDER_<NAME>_ALIASES`; legacy `LLM_API_KEY`, `LLM_BASE_URL`, and `DEEPSEEK_API_KEY` are also supported.
- Persistence: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `QDRANT_HOST`, `QDRANT_PORT`.
- Authentication: `HERMES_LOGIN_USERNAME`, `HERMES_LOGIN_USER_ID`, `HERMES_LOGIN_PASSWORD_HASH`, `HERMES_SESSION_COOKIE_SECURE`, `HERMES_SESSION_TTL_SECONDS`.
- Tracing: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`.

The active systemd unit reads auth settings from a protected environment file rather than documenting their values in the repository.

## Running the Service

The inspected host has `hermes.service` and `hermes-caddy.service` enabled and active. Uvicorn listens on `127.0.0.1:8000`; Caddy binds `192.168.68.103:443`, uses its internal TLS CA, and reverse-proxies to Uvicorn. The HTTPS certificate therefore depends on trusting that internal CA in the client.

`start.sh` is a manual startup script, not the production service definition. It starts selected Docker Compose services and runs `sudo pkill uvicorn` before launching Uvicorn; review that behavior before using it on a host with other Uvicorn processes.

## Testing

Tests are split between `tests/` and root-level regression harnesses. The suite mixes `unittest` classes and pytest-style functions. The existing venv does not currently contain pytest; there is no root test-dependency manifest.

A targeted unittest command verified in the current venv is:

```bash
./venv/bin/python -m unittest tests.test_coverage_evaluator
```

`tests/test_chat_persistence_api.py` requires `ARAN_CHAT_TEST_PGPORT` to point to a disposable PostgreSQL instance and refuses collection otherwise. Do not point it at a production database. The changelog records a historical `python3 -m unittest discover tests` pass; that result is not a current full-suite guarantee.

## Observability / Logs

The API creates Langfuse traces for research requests. The systemd unit sends stdout/stderr to the journal. Structured request events are appended to `/tmp/hermes_events.jsonl` by `hermes_agent/jsonl_logger.py`.

## Status Matrix

| Feature / behavior | Status | Current evidence |
|---|---|---|
| ARAN UI | PARTIAL | ARAN login/chat pages are served; full browser E2E is not proven. |
| Login/session auth | PARTIAL | Auth implementation and targeted tests exist; a complete browser login/chat flow was not verified. |
| Conversation persistence | PARTIAL | PostgreSQL code and manual migration exist; integration test was not run against a disposable database. |
| Model picker | PARTIAL | Provider registry exists; picker JS test currently fails in its DOM harness. |
| Search architecture | PARTIAL | Current executor uses AgentReachSearcher; SearchGateway wiring is a target, not active. |
| RAG/vector retrieval | OPEN | Qdrant backend exists, but active research does not call vector retrieval. |
| Coverage fenced JSON parsing | PARTIAL | Targeted coverage tests pass; direct runtime proof of the fenced branch remains open. |
| FactExtractor table alignment | VERIFIED | Targeted regression and runtime acceptance pass for the tested facts. |

## Current Verified Fixes

At `4d1310a` (`fix: handle fenced coverage JSON and align extracted facts`):

- Coverage parsing accepts JSON wrapped in Markdown code fences and preserves the malformed-JSON fallback. Targeted tests pass; direct runtime proof of the fenced branch remains open.
- Fact extraction prompts require one-to-one alignment with labeled table fields and preserve subsection context. The ACR datasheet alignment regression test passes.

These are verified for their targeted test cases; they do not establish general correctness for every provider or document layout.

## Known Limitations / Open Issues

- Search architecture is transitional: CURRENT uses `AgentReachSearcher`; TARGET proposes `SearchGateway`, which is not wired into the active executor. Three search-architecture tests fail while expecting the target wiring and removal of legacy `agent_reach` imports.
- Qdrant is available as a backend, but vector retrieval/RAG is not active in the current research path.
- The continuation unit tests pass, but one `ContinuationEngineIntegration` case currently expects `CONTINUE` and receives `DEGRADE`; continuation is therefore only partially verified.
- The API has no asynchronous research-status contract. `/research` is synchronous and `/research/{id}` retrieves a stored result.
- Provider resolution is tested, but the historical DeepSeek 502 remediation and 9Router combo / `mimo-auto` behavior are not established by current evidence.
- Attachment handling supports explicit Open WebUI file/source context and OCR for base64 images. Broad browser/RAG/file coverage is not verified; full-file preservation has targeted evidence with additional scenarios still open.
- The model-picker JavaScript test currently stops in its DOM harness because `newChatButton` is undefined. The live login page responds, but a complete browser chat flow was not verified in this audit.
- Conversation persistence has a PostgreSQL migration and owner-scoped code, but its integration test was not run because no disposable test database was configured.
- Branding is transitional: ARAN is user-facing, while service, auth, telemetry, and internal runtime names remain Hermes.

## Repository Structure

```text
api/                 FastAPI entry point, auth, model registry, UI routes
hermes_agent/        Hermes research runtime and orchestration
aran_search/         ARAN search/fetch/evidence implementation
memory_manager/      PostgreSQL and Qdrant backends
ui/                  ARAN login/chat frontend
migrations/          Manual SQL migrations
deploy/              systemd and Caddy configuration
tests/               Unit and integration tests
agent-reach/         Vendored/adjacent Agent Reach project and docs
```

## Development / Debugging Protocol

1. Inspect `git status --short` before work and preserve existing local changes.
2. Trace behavior through the active source path; do not treat backups or proposed tests as proof that a feature is wired.
3. Run focused tests in the repository venv. Use a disposable database for persistence tests.
4. Keep `VERIFIED`, `PARTIAL`, and `OPEN` behavior distinct in notes and changelog entries.
5. Run `git diff --check` on documentation and code changes before review.

## Status

As audited on 2026-10-09, `master` is at `4d1310a`. The working tree contains other uncommitted changes. `CHANGELOG.md.txt` now records `4d1310a`; the entry distinguishes verified behavior from the open direct runtime proof of the fenced-parser branch.
