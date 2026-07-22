# BucketAPI — AI-Powered API Generator

**Describe an API in plain English. Get a live, hosted, documented endpoint in minutes.**

BucketAPI is a full-stack SaaS platform that turns natural-language descriptions into working REST APIs. Users chat with an AI assistant about what they need, review a generated proposal, and the platform writes the code, tests it, documents it, and deploys it to a live URL — all automatically.

Built with **FastAPI**, **MongoDB**, **Redis**, and the **Claude** and **OpenAI** APIs, and deployed behind **Caddy** with automatic HTTPS.

---

## What It Does

### 1. Chat-driven API creation
- A conversational interface analyzes the user's request, classifies message intent, and produces a structured **API proposal** (endpoints, inputs, outputs, logic).
- Users can refine the proposal through follow-up messages before anything is generated.

### 2. Multi-step AI code generation
Code generation is broken into a configurable pipeline rather than a single LLM call:

1. **Analysis & Design** — requirements analysis and API structure design
2. **Implementation** — code generation (with optional database integration)
3. **Testing & Documentation** — test generation and human-readable docs

Each step streams real-time progress to the browser, tracks token usage, and has its own prompt template (versioned JSON prompts under `app/prompts/`). Claude handles code generation; OpenAI handles analysis, intent classification, and validation tasks.

### 3. Instant hosting & execution
Every generated API is immediately live at:

```
POST /api/{user_id}/{api_slug}
```

- Code runs in a **sandboxed virtual environment** with CPU, memory, and timeout limits.
- A **2-venv architecture** separates the platform's environment from generated-API dependencies; required packages are auto-detected and installed on the fly.
- APIs are **versioned** — every modification creates a restorable version.

### 4. Everything around the API
- **Auto-generated documentation** and OpenAPI specs for each API
- **AI test-data generation** and one-click endpoint testing
- **AI debugging** — failed executions can be analyzed and fixed automatically
- **External database connections** (users can wire generated APIs to their own PostgreSQL/other databases, with connection testing)
- **API keys** for programmatic access to generated endpoints
- **Custom domains** — users can point their own domain at their APIs, with DNS verification and automatic SSL certificates via Caddy

### 5. SaaS infrastructure
- **Auth**: email/password (JWT + bcrypt) and Google/GitHub OAuth, with Redis-backed sessions for multi-worker deployments
- **Billing**: LemonSqueezy subscriptions (Starter / Professional / Enterprise tiers) with webhook-driven subscription lifecycle
- **Usage metering**: token-based usage tracking, per-tier limits, and cost estimation for both API generation and API execution
- **Admin panel** and a **logs dashboard** with structured HTTP / LLM / chat logging
- SEO basics: generated `sitemap.xml` and `robots.txt`

---

## How It's Built

### Architecture

```
                        ┌─────────────────────────────┐
   User's browser ────► │  Caddy (reverse proxy,      │
   Custom domains ────► │  auto-HTTPS, on-demand TLS) │
                        └──────────────┬──────────────┘
                                       │
                        ┌──────────────▼──────────────┐
                        │  FastAPI app (Gunicorn +    │
                        │  Uvicorn workers)           │
                        │                             │
                        │  routes ─► services layer   │
                        │  (30+ single-purpose        │
                        │   service modules)          │
                        └───┬───────┬───────┬─────────┘
                            │       │       │
                 ┌──────────▼─┐ ┌───▼────┐ ┌▼──────────────────┐
                 │  MongoDB   │ │ Redis  │ │ Sandboxed venvs   │
                 │ (users,    │ │(sessions│ │ (generated API   │
                 │  APIs,     │ │ cache)  │ │  execution)      │
                 │  usage)    │ └────────┘ └───────────────────┘
                 └────────────┘      ┌─────────────────────────┐
                                     │ Claude API + OpenAI API │
                                     │ (generation pipeline)   │
                                     └─────────────────────────┘
```

### Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2, async throughout |
| AI | Anthropic Claude (code generation), OpenAI (analysis/validation), tiktoken for token accounting |
| Database | MongoDB (Motor async driver) |
| Cache / sessions | Redis |
| Frontend | Server-rendered Jinja2 templates + vanilla JavaScript, Tailwind-styled UI with streaming chat |
| Auth | JWT (python-jose), bcrypt, Authlib for Google/GitHub OAuth |
| Payments | LemonSqueezy |
| Web server | Caddy (automatic SSL, custom-domain routing) → Gunicorn + Uvicorn workers |
| Deployment | Docker (multi-stage build), deployable to DigitalOcean or Railway |

### Design decisions worth noting

- **Service-oriented backend** — the logic lives in ~30 focused service modules (`claude_service`, `sandbox_service`, `venv_manager`, `subscription_service`, `domain_verification_service`, …) rather than fat route handlers, which kept a large codebase maintainable as features grew.
- **Prompts as versioned config** — every LLM prompt is a JSON file loaded by a prompt loader, so prompt iteration doesn't require code changes.
- **Sandboxed execution** — generated (untrusted) code never runs in the main process: it executes in an isolated virtual environment with resource limits, monitored by `psutil`.
- **Streaming-first UX** — proposal generation and the multi-step pipeline stream results token-by-token, so users watch their API being designed and written live.
- **Security hardening** — secure error responses that don't leak internals, security scanning of generated code before execution, non-root container user, and rate/usage limits per subscription tier.
- **Runtime-tunable settings** — model choice, temperature, and token limits are read from a database-backed settings service, so the admin panel can retune the AI pipeline without redeploying.

---

## Project Structure

```
├── app/
│   ├── main.py                    # FastAPI app + ~110 routes
│   ├── config.py                  # Environment + DB-backed settings
│   ├── models.py                  # Pydantic request/response models
│   ├── routes/                    # Auth & OAuth routers
│   ├── services/                  # 30+ service modules (AI, sandbox, billing, domains…)
│   ├── prompts/                   # Versioned JSON prompt templates (claude/ & openai/)
│   ├── middleware/                # Logging + Redis session middleware
│   └── code_generation_config/    # Multi-step pipeline configuration
├── templates/                     # Jinja2 pages (landing, dashboard, docs, admin…)
├── static/                        # CSS/JS (streaming chat UI, API details, docs)
├── Caddyfile                      # Reverse proxy + on-demand TLS for custom domains
├── Dockerfile                     # Multi-stage build (Caddy + Python app)
├── docker-compose.production.yml
└── start.sh                       # Boots Caddy + Gunicorn together
```

---

## Running Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment (.env)
#    MONGODB_URL, MONGODB_DB_NAME, SECRET_KEY,
#    CLAUDE_API_KEY, OPENAI_API_KEY,
#    optional: REDIS_URL, Google/GitHub OAuth creds, LemonSqueezy creds

# 3. Start the app
python main.py            # dev server on http://127.0.0.1:8001
```

For production, the Docker image runs Caddy and the FastAPI app together — see `docker-compose.production.yml` and `DIGITALOCEAN_DEPLOYMENT_GUIDE.md`.

---

## Status

This project was built as a solo full-stack product — design, backend, frontend, AI pipeline, billing, and deployment. It's shared publicly as a portfolio piece demonstrating production-grade work with LLM orchestration, sandboxed code execution, and SaaS infrastructure.
