# DocGuard — Project Scaffold

AI-powered documentation consistency & knowledge platform. This is the initial
architecture scaffold from the project brief: Django (WSGI+ASGI) + Celery +
Channels + Strands Agents + RAG + React, fully Dockerized.

## Layout

```
docguard/
├── backend/
│   ├── config/                # settings (base/dev/prod), celery.py, asgi.py, wsgi.py, routing.py
│   └── apps/
│       ├── workspaces/        # Workspace, WorkspaceMembership, TriageRule
│       ├── sources/           # Source, Artifact + ingestion pipeline (Celery)
│       ├── knowledge/         # Chunk (pgvector), Claim, Inconsistency, ScanRun
│       ├── agents/            # Strands Agents SDK: Extractor/Comparator/Judge/Fixer/Orchestrator
│       ├── chat/               # ChatSession/ChatMessage + streaming RAG consumer
│       ├── realtime/           # Dashboard + ReviewRoom Channels consumers, JWT ws auth
│       ├── automation/         # Celery Beat: weekly digest (email + Teams)
│       └── webhooks/           # Inbound GitHub webhook (HMAC verified, delivery-deduped)
├── frontend/                   # Vite + React + Tailwind SPA
├── nginx/nginx.conf            # /api,/webhooks -> Gunicorn, /ws -> Daphne, / -> React
├── docker-compose.yml
└── docker-compose.prod.yml
```

## What's implemented vs. stubbed

**Fully wired (logic + models + routing):**
- Django app structure, settings split, URL routing
- Data models for every entity in the spec
- Celery task graph: `sync_source → process_artifact → embed_chunks → extract_claims →
  compare_claim → judge_contradiction → create_pull_request_from_fix`
- Idempotency: `content_hash` dedup on artifacts, `WebhookDelivery` dedup on GitHub deliveries
- Redis 3-way role separation (broker / cache / channel layer), embedding cache, rate limiter
- Channels consumers (Dashboard, ReviewRoom, Chat) with JWT auth middleware
- Hybrid RAG retrieval (pgvector + Postgres full-text, RRF merge) with low-confidence guardrail
- Docker Compose: healthchecks, `depends_on` conditions, dedicated Celery queues, non-root containers

**Intentionally left as `NotImplementedError` placeholders** (the actual intern work):
- `_list_source_files` — GitHub API / upload storage / wiki export client
- `_call_openai_embeddings` — OpenAI embeddings API call
- `ChatConsumer._stream_answer` — OpenAI streaming chat completion
- `github_pr_creator` tool — GitHub PR creation via PyGithub
- Agent `structured_output` schemas will need to match whatever the Strands SDK's
  JSON-mode / tool-call response shape actually is — check the SDK docs when you start.

## Running locally

```bash
cp backend/.env.example backend/.env   # fill in OPENAI_API_KEY, GITHUB_* etc.
docker compose up --build
```

- App: http://localhost/
- Admin: http://localhost/admin/
- Flower (Celery monitoring): http://localhost:5555/

First run:
```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

## Architecture

Nginx routes ordinary HTTP requests (`/api/`, `/admin/`, and `/webhooks/`) to
Gunicorn, which serves Django's WSGI application. It routes `/ws/` to Daphne,
which serves the ASGI application required by Django Channels. Keeping both
processes is intentional: Gunicorn handles conventional request/response work,
while Daphne keeps WebSocket connections open and delivers asynchronous events.

One Redis server has three isolated logical roles: database 0 is the Celery
broker, database 1 is Django's cache (including the SHA-256 embedding cache),
and database 2 is the Channels layer for WebSocket groups. The split prevents
queue traffic, cache keys, and live-channel messages from colliding.

For dashboard updates, a Celery worker finishes a pipeline step and calls
`channel_layer.group_send` for `workspace_<workspace_id>_dashboard`. Redis
database 2 carries that group event to Daphne, Daphne emits it on the
workspace WebSocket, and the React dashboard receives and renders it without a
page refresh.

## Suggested next steps (day 1-2)

1. `pip install -r backend/requirements.txt` locally (or in the `web` container) and run
   `makemigrations` — models haven't been migrated yet.
2. Wire up `_call_openai_embeddings` first; nearly everything downstream depends on it.
3. Get one Source type end-to-end (recommend starting with `upload` — simplest,
   no GitHub API needed) before tackling GitHub sync.
4. Confirm the Strands Agents SDK's actual API surface (`Agent()`, `@tool`,
   `.as_tool()`, structured output) against its docs — the agent definitions here
   are written to the spec's described pattern but the SDK's exact interface
   should be verified against current docs before relying on it.
