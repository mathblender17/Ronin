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

## Current limits

- The first version is a local single-user app; it has no account sync or cloud backup.
- Search grounding depends on Gemini model/account availability and may return no concept-specific citations.
- The graph currently uses parent-child tree branches. It records sources per concept but has no cross-links, media thumbnails, node regeneration UI, or automated export image; the recap can be printed or saved as PDF.
- Database schema creation is automatic for new installs; no migration framework is included yet.
