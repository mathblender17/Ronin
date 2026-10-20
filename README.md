# Ronin — The Rabbit Hole Explorer

Ronin turns a question into a small, expandable map of ideas. Choose a concept to read its context, follow a branch, and return to the trail later. Rabbit holes and their graphs are stored locally in SQLite.

The original command-line report generator is still available as `main.py`; the web application lives alongside it.

## Requirements

- Python 3.10 or newer
- Node.js 18 or newer
- A Gemini API key from Google AI Studio

## Setup

From the project root, create the backend environment and install the Python dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env`, then add your key:

```env
GEMINI_API_KEY=your_google_ai_studio_api_key
GEMINI_MODEL=gemini-2.5-flash
```

Install the frontend dependencies:

```powershell
pnpm install
```

`npm install` also works if npm is available.

## Run locally

Open two terminals at the project root. In the first:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

In the second:

```powershell
pnpm dev
```

Open the local address printed by Vite (normally `http://127.0.0.1:5173`). Vite forwards `/api` requests to FastAPI on port 8000. The SQLite database is created at `data/ronin.db` on first launch. Override its location with `RONIN_DATABASE_URL` if needed.

## Verify

Run backend tests with:

```powershell
python -m pytest
```

Check the production frontend build with:

```powershell
pnpm build
```

## How AI and sources work

The API keeps the Gemini key on the backend. Exploration questions and relevant graph context are sent to the configured Gemini service; successful graphs are stored in the local SQLite database. `GEMINI_MODEL` selects the model and defaults to `gemini-2.5-flash`. The model returns Pydantic-validated JSON for each layer. A separate Google Search grounded pass collects real citation metadata and attaches it only when the returned cited text can be associated with one of that layer's concepts. If grounding does not return a clear citation, the concept shows no verified source instead of a generated URL.

The generation and grounding calls are separate because Gemini's documented combination of tool grounding and structured output is limited to Gemini 3 models; this keeps the requested Gemini 2.5 default while preserving structured validation and real search citations. Source grounding is optional: a search failure does not discard otherwise valid generated concepts.

If the API key is missing, the landing page explains how to configure it. Ronin does not silently switch to canned/demo branches.

## AI providers and fallback

Ronin tries AI providers in the order set by `RONIN_AI_PROVIDER_ORDER` (default `gemini,openrouter`). A provider that is not configured is skipped. Gemini is the existing integration and needs only `GEMINI_API_KEY`. OpenRouter is an optional fallback that needs `OPENROUTER_API_KEY`.

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | none | Enables Gemini. Unchanged from before. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model. Must be on the approved list unless paid models are enabled. |
| `OPENROUTER_API_KEY` | none | Enables OpenRouter. |
| `RONIN_AI_PROVIDER_ORDER` | `gemini,openrouter` | Provider order. Use `openrouter,gemini` to try OpenRouter first. |
| `RONIN_AI_PRIMARY_MODEL` | `nvidia/nemotron-3-super-120b-a12b:free` | First OpenRouter model. |
| `RONIN_AI_FALLBACK_MODELS` | `google/gemma-4-26b-a4b-it:free,xingchen-agi/xing4.0-29b-a4b:free` | Comma-separated OpenRouter models, tried in order. |
| `RONIN_AI_TIMEOUT_SECONDS` | `45` | Timeout for each provider call. |
| `RONIN_AI_MAX_RETRIES` | `1` | Retries per model for rate limits, timeouts and server errors. |
| `RONIN_AI_MAX_OUTPUT_TOKENS` | `4096` | Output limit per call. |
| `RONIN_AI_ALLOW_PAID_MODELS` | `false` | Leave `false`. See below. |

**Failover rules.** Rate limits, timeouts, connection errors and server errors are retried with backoff (1 s doubling, capped at 8 s, with jitter). A `Retry-After` of up to 10 s is honoured. A longer one moves on to the next model. A daily free-tier limit, a billing response, or a rejected key is never retried. Instead that provider is paused for one hour. Malformed or schema-invalid output moves to the next model. A failed generation never writes to the saved graph.

**Free-only enforcement.** This is enforced in code, before any request is sent. An OpenRouter model is called only if it is on the approved list in `backend/ai_providers.py` (`FREE_OPENROUTER_MODELS`) and its ID ends in `:free`. A paid model is accepted only when `RONIN_AI_ALLOW_PAID_MODELS=true` and that exact model is named in the primary or fallback settings. Paid models are never chosen automatically. An unknown model returns a policy error and nothing is sent. Gemini models outside `GEMINI_MODELS` are treated the same way.

**Adding or removing a model.** Add the exact `:free` ID to `FREE_OPENROUTER_MODELS`, after checking `https://openrouter.ai/api/v1/models` for free pricing, JSON response format, and the context limit. Then list it in `RONIN_AI_PRIMARY_MODEL` or `RONIN_AI_FALLBACK_MODELS`. To remove a model, delete it from either setting, or from the allowlist to block it everywhere.

**Known free-tier limitations.** Free models can be slower, can be temporarily unavailable, and have daily limits that are shared across the whole free tier, so switching models does not avoid them. Free-tier status changes, so the approved list must be checked periodically. Source grounding uses Gemini's search feature. Layers produced by OpenRouter therefore carry no sources, and Ronin never invents one. The provider cooldown lives in process memory and resets when the API restarts. The model comparison in `backend/benchmark` has not been run yet, so the default model order reflects catalogue metadata, not measured quality.

**Diagnostics.** `GET /api/health` reports whether any provider is configured, each provider's eligible model IDs and cooldown, the last successful provider and model with its latency, and recent failure categories. It never reports keys.

**Deterministic tests** (no keys, no network, no quota):

```powershell
python -m pytest backend/tests -q
```

**Live smoke tests** (spend quota; opt-in):

```powershell
$env:RONIN_LIVE_TESTS = "1"; python -m pytest backend/live_tests -q
```

**Model comparison** (spends OpenRouter free quota; opt-in):

```powershell
$env:RONIN_LIVE_BENCHMARK = "1"; python -m backend.benchmark.run_benchmark --model nvidia/nemotron-3-super-120b-a12b:free --out benchmark-results.json
```

## API outline

- `GET /api/health` — service and AI configuration status
- `GET /api/rabbit-holes` — archive cards and graph metrics
- `POST /api/rabbit-holes` — create a question and its first layer
- `GET /api/rabbit-holes/{id}` — load a saved graph
- `POST /api/rabbit-holes/{id}/nodes/{node_id}/visit` — record a visited concept
- `POST /api/rabbit-holes/{id}/nodes/{node_id}/expand` — add children or reuse an existing layer
- `DELETE /api/rabbit-holes/{id}` — remove an exploration

The FastAPI schema is available at `http://127.0.0.1:8000/docs`.

## Manual check

1. Start the API and Vite, then create a new question.
2. Hover over a branch and confirm the stored preview appears without a request.
3. Select a branch, inspect its path and source links, then expand it.
4. Enter a short direction in the secondary input and add another layer.
5. Open Field Notes and compare counts, depth, branches, and subjects with the map.
6. Return to Archive, reopen the trail, and confirm the saved child relationships remain.
7. Delete a trail and confirm the browser asks before removing it.

## Deploy a read-only showcase

`RONIN_READ_ONLY=1` turns Ronin into a showcase: visitors can open trails, hover and select concepts, read sources, and view recaps, but cannot create, expand, or delete anything, and no Gemini calls are made. No API key is needed on the server.

The `Dockerfile` builds the frontend and serves it from FastAPI, so the whole app is one container. It ships the snapshot in `showcase/ronin.db`. Refresh the snapshot from your local data with:

```powershell
Remove-Item showcaseonin.db
py -3 -c "import sqlite3; sqlite3.connect('data/ronin.db').execute(\"VACUUM INTO 'showcase/ronin.db'\")"
```

Run the image locally:

```powershell
docker build -t ronin-showcase .
docker run --rm -p 10000:10000 ronin-showcase
```

On Render, create a **Blueprint** from this repository (it reads `render.yaml`) or a **Web Service** with the Docker runtime and `RONIN_READ_ONLY=1`. Render supplies `PORT`, and the free plan sleeps when idle.

## Current limits

- The first version is a local single-user app; it has no account sync or cloud backup.
- Search grounding depends on Gemini model/account availability and may return no concept-specific citations.
- The graph currently uses parent-child tree branches. It records sources per concept but has no cross-links, media thumbnails, node regeneration UI, or automated export image; the recap can be printed or saved as PDF.
- Database schema creation is automatic for new installs; no migration framework is included yet.
