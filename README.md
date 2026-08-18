# DocGuard

AI-powered documentation consistency platform. DocGuard continuously scans
your documentation sources (GitHub repos, uploads, wiki exports) for
factual conflicts — endpoint verb mismatches, version number disagreements,
config value discrepancies — and surfaces them as actionable issues, with
an option to auto-create a GitHub pull request that applies a suggested fix.

## Architecture

```
Nginx
 ├─ /api/, /admin/, /webhooks/  →  Gunicorn (WSGI — Django REST Framework, Admin)
 └─ /ws/                        →  Daphne  (ASGI — Django Channels WebSockets)

Celery workers (two queues)
 ├─ ingestion  — sync_source, process_artifact, embed_chunks, webhook handlers
 └─ llm        — extract_claims, compare_claim, judge_contradiction, create_pull_request_from_fix

Redis (three isolated logical databases)
 ├─ db 0  — Celery broker + result backend
 ├─ db 1  — Django cache (SHA-256 embedding cache, 30-day TTL)
 └─ db 2  — Channels layer (WebSocket group messages)

PostgreSQL + pgvector  — relational data + 3072-dim embedding vectors
React (Vite) SPA       — Dashboard, Issues, Chat, Sources, Settings pages
```

For a step-by-step message path: a Celery worker finishes a pipeline step and
calls `channel_layer.group_send` for `workspace_<id>_dashboard`; Redis db2
carries the group event to Daphne; Daphne emits it on the workspace WebSocket;
the React dashboard renders it without a page refresh.

## What's implemented

**End-to-end pipeline (confirmed working)**
- Auth: JWT with 15-min access tokens, 7-day refresh, auto-rotate
- Ingestion: `sync_source → process_artifact → embed_chunks` with content-hash
  dedup (unchanged files skipped on re-sync) and SHA-256 embedding cache
- Multi-provider embedding cascade: OpenAI → Gemini → deterministic mock
- Agent pipeline: `extract_claims → compare_claim → judge_contradiction` with
  real Gemini calls and a heuristic regex fallback when quota is exhausted
- RAG chat: hybrid pgvector + Postgres full-text with RRF merge, low-confidence
  guardrail, streaming WebSocket response
- Real-time dashboard: live agent activity feed over WebSocket
- Inbound webhooks: GitHub push events, HMAC-verified, `X-GitHub-Delivery`
  idempotency via `WebhookDelivery.get_or_create`
- Outbound PR creation: `create_pull_request_from_fix` via PyGithub PAT auth —
  creates branch, commits `suggested_fix`, opens PR with reasoning + claims in body
- Weekly digest: Celery Beat task (email / Teams webhook)

**Recently fixed / verified**
- Login and JWT auth flow are implemented in the live UI (`Login.jsx`,
  `RequireAuth`, JWT token refresh, and WebSocket auth middleware).
- Sources, Settings, and the dashboard KPI panels are wired to real API data.
- Consistency scoring uses a proper severity-weighted formula; a single minor
  issue no longer collapses the score to `0.0` / "Critical" by mistake.
- ScanRun finalization is fixed, including the unchanged-artifact edge case
  that previously left runs stuck in `RUNNING` forever.
- Chat markdown rendering now keeps inline code spans like
  ``POST /api/v2/auth/login`` inside the sentence instead of splitting them
  into separate full-width blocks.
- Client-side routes no longer 404 on refresh; SPA fallback is configured in
  nginx for React Router URLs like `/chat`, `/issues`, and `/sources`.
- The Gemini configuration now points to a real available model instead of a
  nonexistent one.

**Known limitations**
- Single-artifact PR: `create_pull_request_from_fix` targets the first Claim's
  Artifact only. If an Inconsistency spans Claims from different files (e.g.
  README vs OpenAPI spec), only the first file is patched in the PR.
- Auth is PAT-based (`GITHUB_PAT`). The GitHub App flow (`GITHUB_APP_ID` /
  `GITHUB_APP_PRIVATE_KEY`) is wired into settings but not implemented.
- `apps/agents/definitions.py` contains Strands Agents SDK drafts; these are
  reference code only and are not called from the live pipeline.

## Layout

```
docguard/
├── backend/
│   ├── config/            # settings (base/dev/prod), celery.py, asgi.py, wsgi.py
│   └── apps/
│       ├── workspaces/    # Workspace, WorkspaceMembership, TriageRule
│       ├── sources/       # Source, Artifact + ingestion Celery tasks
│       ├── knowledge/     # Chunk (pgvector), Claim, Inconsistency, ScanRun
│       ├── agents/        # Extractor/Comparator/Judge/Fixer Celery tasks + heuristic fallback
│       ├── chat/          # ChatSession/ChatMessage + streaming RAG WebSocket consumer
│       ├── realtime/      # Dashboard + ReviewRoom Channels consumers, JWT WS auth
│       ├── automation/    # Celery Beat: weekly digest
│       └── webhooks/      # Inbound GitHub webhook (HMAC-verified, delivery-deduped)
├── frontend/              # Vite + React + Tailwind SPA
├── nginx/nginx.conf
├── docker-compose.yml
└── docker-compose.prod.yml
```

## Running locally

```bash
cp backend/.env.example backend/.env
# Edit backend/.env — required keys:
#   GEMINI_API_KEY      — for agent pipeline + embeddings
#   GITHUB_PAT          — for outbound PR creation
#   GITHUB_WEBHOOK_SECRET — for inbound webhook HMAC verification
#   DJANGO_SECRET_KEY   — any long random string

docker compose up --build
```

- App: http://localhost/
- Admin: http://localhost/admin/
- Flower (Celery monitoring): http://localhost:5555/

**First run:**
```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

**After editing backend Python files**, rebuild the image so changes are baked
in (do not rely on `docker compose cp` — it writes to the container's writable
layer and is lost on `--force-recreate`):
```bash
docker compose build web worker-llm worker-ingestion
docker compose up -d --force-recreate web worker-llm worker-ingestion
```

## Running tests + coverage

```bash
# Install coverage into the web container (once per container lifetime):
docker compose exec -u root web pip install coverage==7.6.1

# Run the full test suite with coverage:
docker compose exec web python -m coverage run --source=apps \
    manage.py test apps --keepdb --verbosity=2

# Print the coverage report:
docker compose exec web python -m coverage report

# Drop --keepdb on first run (or after schema changes) to recreate the test DB.
# Note: the TransactionTestCase storm test leaves connections open, so Django
# may fail to drop the test DB at teardown — this is cosmetic, not a test failure.
```

**Current results (August 2026):**
- 128 tests, all passing
- 87% line coverage
- Precision: 1.00 · Recall: 0.80 (heuristic pipeline, 8-case fixture)

See `docs/agent-iteration-log.md` for the full precision/recall breakdown and
the fixture test case descriptions.

## Environment variables

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Django secret key |
| `DJANGO_DEBUG` | Set `true` for development |
| `GEMINI_API_KEY` | Gemini embedding + chat models |
| `OPENAI_API_KEY` | Optional; falls back to Gemini if unset |
| `GITHUB_PAT` | Fine-grained PAT for outbound PR creation (Contents + Pull requests read/write) |
| `GITHUB_WEBHOOK_SECRET` | Shared secret for HMAC verification of inbound GitHub webhooks |
| `GITHUB_APP_ID` / `GITHUB_APP_PRIVATE_KEY` | Reserved for future GitHub App auth (not yet implemented) |
| `TEAMS_WEBHOOK_URL` | Optional; weekly digest Teams webhook |
| `POSTGRES_*` | Database connection |
| `REDIS_HOST` / `REDIS_PORT` | Redis connection |
