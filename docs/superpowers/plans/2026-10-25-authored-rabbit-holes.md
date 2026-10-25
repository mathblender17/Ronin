# Authored Rabbit Holes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An AI-drafted, human-edited markdown story per rabbit hole. It's drafted from web, YouTube, Wayback and Reddit finds with any of Gemini, OpenRouter, DeepSeek or Kimi, then compiled into Ronin's graph and published as an allowlisted read-only snapshot that readers follow, inspect and share.

**Architecture:** `backend/story.py` owns the story file format (parse and render, no I/O beyond strings). `backend/sources/` holds one search adapter per provider behind a common `Found` record. `backend/studio.py` is the local CLI: it runs draft, redraft, import and publish, compiling stories into the existing SQLAlchemy models. Publish builds a fresh SQLite snapshot from published stories only. The frontend reuses the explorer and recap, adding stage and evidence chips, source metadata, an authored Leap card and session-only visited state.

**Tech Stack:** FastAPI, SQLAlchemy 2, Pydantic 2, httpx, google-genai, pytest; React 19 + TypeScript. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-25-authored-rabbit-holes-design.md`

## Global Constraints

- No new Python or npm dependencies. Front-matter is simple `key: value` lines, parsed by hand (no YAML library).
- Evidence values: `fact`, `claim`, `interpretation`, `speculation`, `open`. Stages: `hook`, `entry`, `descent`, `leap`, `exit`. Source mediums: `video`, `page`, `archive`, `reddit`.
- Sections appear exactly once, in this order: Hook, Entry, Descent, Leap, Exit. Entry and Leap hold one `###` discovery each, and Descent holds 1–6. `fact` and `claim` need ≥1 source. URLs must be http(s). The slug matches `[a-z0-9-]+` and the filename.
- Reddit sources store only the permalink, title and author. Post text is never stored, copied or sent to a model.
- `check_note`, `drafted_by`, `prompt` and `stories/.research/` never reach `showcase/ronin.db` or any API response in read-only mode.
- Model providers: `deepseek` uses base `https://api.deepseek.com`, key `DEEPSEEK_API_KEY`, model env `DEEPSEEK_MODEL` (default `deepseek-flash`). `kimi` uses base `https://api.moonshot.ai/v1`, key `MOONSHOT_API_KEY`, model env `KIMI_MODEL` (default `kimi-k3.1-pro`). Both are called only when named in `RONIN_AI_PROVIDER_ORDER` or `--model`. Every JSON prompt includes the word "JSON" and the target shape, because DeepSeek's JSON mode requires it.
- Search keys: `YOUTUBE_API_KEY`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`. A missing key means the provider is skipped, not an error. The Reddit User-Agent is `ronin-studio/1.0 (local research tool)`.
- The draft prompt version string is `draft-v1`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Use `python -m pytest backend/tests -q` (system Python; the project `.venv` is blocked by Windows Application Control on this machine) and `npm run build`.

**Deviation from spec, decided here:** the Wayback adapter uses only the `available` API for URLs other providers found. The spec's extra "CDX query for the seed's domains" is dropped, because seeds are ideas, not domains, so there is nothing to query. Add CDX when a story starts from a known dead site.

## Review Focus

- A story file saved with Windows CRLF line endings or a UTF-8 BOM must parse the same as LF. Test this in Task 2.
- Two stories citing the same URL. `sources.url` is globally unique, so the import reuses the row, and re-importing one story must not delete a source the other still uses. Test this in Task 3.
- Gemini grounding returns `vertexaisearch.cloud.google.com` redirect URLs, which expire. The web adapter resolves each one to its final URL, and drops it if resolution fails. Test this in Task 6.
- A story whose `published:` date is in the future, or malformed: the first is excluded from publish, the second is a parse error with its line number. Test this in Tasks 2 and 4.
- Read-only readers opening nodes must never call `/visit` or any AI route, and the visited marks must reset on reload. This gets checked in the Task 9 browser step.

---

### Task 1: Model-agnostic providers (DeepSeek, Kimi, per-call model override)

**Files:**
- Modify: `backend/ai_providers.py` (`openrouter_generate_json` gets a `url` keyword)
- Modify: `backend/ai.py` (routing, policy, `any_provider_configured`, `_structured(..., only=)`)
- Test: `backend/tests/test_ai_reliability.py` (append)

**Interfaces:**
- Produces:
  - `openrouter_generate_json(*, model, prompt, api_key, timeout, max_tokens, temperature=0.85, transport=None, url: str = OPENROUTER_URL) -> str`. Only the URL becomes a parameter.
  - In `ai.py`: `OPENAI_COMPATIBLE: dict[str, tuple[str, str, str, str]]`, mapping a provider name to `(chat_completions_url, key_env, model_env, default_model)`, for `deepseek` and `kimi`. The URL is the base plus `/chat/completions`.
  - `_structured(prompt: str, schema: type[BaseModel], only: tuple[str, str] | None = None) -> Any`, where `only = (provider, model)` restricts the run to exactly that pair. The same goes for `_structured_with_provider(prompt, schema, only=None)`.
  - `last_provider_model() -> str`. It returns `"provider/model"` of the last success in this thread (from `_local`), or `""`.
- `_enforce_policy`: `deepseek` and `kimi` always pass, because being named in the order or `only` is the explicit choice. With `only`, OpenRouter's `named_explicitly` is True.
- A missing DeepSeek or Kimi key raises `AIConfigurationError` inside `_call`, so the router skips that provider, matching how a missing OpenRouter key is handled today.

- [ ] **Step 1: Write the failing tests:**
  - `test_deepseek_posts_to_its_own_base_url`: use the module's captured original adapter with an `httpx.MockTransport` that records `request.url` and the auth header and returns `{"choices":[{"message":{"content":"{}"}}]}`. Call it with `url=ai.OPENAI_COMPATIBLE["deepseek"][0]` and assert the URL is `https://api.deepseek.com/chat/completions` and the header is `Bearer k`.
  - `test_named_kimi_is_called_and_unnamed_is_not`: monkeypatch `ai.providers.openrouter_generate_json` to record its `url` and return a valid `ExpansionLayer` JSON. Set `MOONSHOT_API_KEY=k` and `RONIN_AI_PROVIDER_ORDER=kimi`. One `_structured(prompt, ExpansionLayer)` call records the URL `https://api.moonshot.ai/v1/chat/completions`. With the order `gemini` only (no Gemini key), the recorder is never called.
  - `test_only_override_restricts_to_one_model`: with `RONIN_AI_PROVIDER_ORDER=gemini,openrouter`, `_structured(p, ExpansionLayer, only=("deepseek", "deepseek-flash"))` with `DEEPSEEK_API_KEY` set calls the recorder exactly once, with model `deepseek-flash`. Then `ai.last_provider_model() == "deepseek/deepseek-flash"`.
  - `test_missing_deepseek_key_is_skipped`: with order `deepseek` and no key, it raises `ai.AIServiceError`, and the recorder is not called.
- [ ] **Step 2: Run them and confirm they fail.** Run: `python -m pytest backend/tests/test_ai_reliability.py -q -k "deepseek or kimi or only_override"`. Expected: failures (`OPENAI_COMPATIBLE` / `url` keyword missing).
- [ ] **Step 3: Implement** the interfaces above. In `_structured_with_provider`, the model list for a compatible provider is `[os.getenv(model_env) or default_model]`. `_call` dispatches compatible providers to `openrouter_generate_json(url=..., api_key=<env key>)`. `_local.model = model` is set beside `_local.provider` on success. `any_provider_configured` also returns True for `DEEPSEEK_API_KEY` or `MOONSHOT_API_KEY`. Add the two key names to `AI_ENVIRONMENT` in `backend/tests/conftest.py` so tests start clean.
- [ ] **Step 4: Run all backend tests and confirm they pass.** Run: `python -m pytest backend/tests -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -m "Add DeepSeek and Kimi as OpenAI-compatible providers with a per-call model override"`

### Task 2: Story file format

**Files:**
- Create: `backend/story.py`
- Test: `backend/tests/test_story.py`

**Interfaces:**
- Produces:
  - `EVIDENCE = ("fact", "claim", "interpretation", "speculation", "open")`, `MEDIUMS = ("video", "page", "archive", "reddit")`
  - `@dataclass class SourceRef: title: str; url: str; medium: str; creator: str | None = None; date: str | None = None`
  - `@dataclass class Discovery: title: str; evidence: str; why: str; body: str; sources: list[SourceRef]; check: str | None = None`
  - `@dataclass class Story: slug: str; title: str; hook: str; entry: Discovery; descent: list[Discovery]; leap: Discovery; known: str; open: str; published: date | None = None; territory: str | None = None; drafted_by: str | None = None; prompt: str | None = None; note: str | None = None`
  - `class StoryError(ValueError): def __init__(self, line: int, message: str)`, where `str(err) == f"line {line}: {message}"`
  - `def parse_story(text: str, slug: str) -> Story`. `slug` is the filename stem and must equal the front-matter slug.
  - `def render_story(story: Story) -> str`. Its output re-parses to an equal `Story`.

The file grammar matches the spec example:
- Front-matter sits between `---` lines.
- An optional `<!-- note -->` HTML comment after the front-matter becomes `Story.note`; other HTML comments are ignored.
- Within a `###` discovery, lines starting `evidence:`, `why:` and `check:` are fields. A `sources:` line starts the source list, made of `- [title](url) · medium · creator · date` lines (the creator and date parts are optional, separated by ` · `). Every other non-blank line joins `body` with `\n`.
- Hook is the non-blank text under `## Hook`. Exit holds `known:` and `open:` lines.
- Normalise `\r\n` to `\n` and strip a leading BOM before parsing.

- [ ] **Step 1: Write the failing tests.** Use one fixture string `VALID` (a full story: one Entry, two Descent discoveries, a Leap, an Exit, a note comment, `published: 2026-11-02`):
  - `test_valid_story_round_trips`: `parse_story(render_story(s), s.slug) == s`, where `s = parse_story(VALID, "early-japanese-web")`. Check the descent count is 2, the leap evidence is `interpretation`, and the first entry source has medium `archive` and date `2003-05-01`.
  - `test_crlf_and_bom_parse_the_same`: `parse_story("﻿" + VALID.replace("\n", "\r\n"), slug) == parse_story(VALID, slug)`
  - One parametrised test, `test_rule_violation_reports_line`. Each case mutates `VALID` and asserts that `StoryError` is raised, that `str(err)` contains the expected fragment, and that `err.line` equals the mutated line's number. The cases are:
    - Missing `## Leap` (`missing section: Leap`)
    - Sections out of order (`expected section`)
    - Two discoveries under Entry (`Entry holds exactly one discovery`)
    - Seven under Descent (`Descent holds 1-6`)
    - `evidence: rumour` (`unknown evidence`)
    - A `fact` with no sources (`needs a source`)
    - `- [x](ftp://a)` (`http(s)`)
    - The medium `tv` (`unknown medium`)
    - A slug mismatch (`slug must match`)
    - `published: 2026-13-40` (`invalid date`)
- [ ] **Step 2: Run them and confirm they fail.** Run: `python -m pytest backend/tests/test_story.py -q`. Expected: `ModuleNotFoundError: backend.story`
- [ ] **Step 3: Implement** `backend/story.py`: a line-by-line state machine that tracks the 1-based line numbers, then validates.
- [ ] **Step 4: Run them and confirm they pass.** Run the same command. Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -m "Add the story file format"`

### Task 3: Story fields in the DB, column backfill, and import

**Files:**
- Modify: `backend/models.py`, `backend/database.py`
- Create: `backend/studio.py` (functions plus the CLI `main()`; this task adds `import`)
- Modify: `.gitignore` (add `stories/.research/`)
- Create: `stories/.gitkeep`
- Test: `backend/tests/test_studio.py`

**Interfaces:**
- Consumes: Task 2's `parse_story`, `Story` and `Discovery`.
- Produces:
  - New nullable columns:
    - `RabbitHole.slug: str | None` (unique), `published_at: date | None`, `territory: str | None`
    - `Node.stage: str | None`, `evidence: str | None`, `check_note: str | None`
    - `Source.medium: str | None`, `creator: str | None`, `published: str | None`
  - In `database.py`: `def add_missing_columns(engine) -> None`. It's SQLite-only. For each mapped table, `PRAGMA table_info`, then `ALTER TABLE ... ADD COLUMN` for each missing nullable column. It's called in `main.py` right after `Base.metadata.create_all`. Its comment: `# shortcut: add-only, no renames or drops, use Alembic once the schema changes shape.` The unique slug is enforced by `CREATE UNIQUE INDEX IF NOT EXISTS uq_rabbit_holes_slug ON rabbit_holes(slug)`, because SQLite can't `ADD COLUMN ... UNIQUE`.
  - In `studio.py`:
    - `STORIES_DIR = ROOT_DIR / "stories"`
    - `def load_story(slug: str, stories_dir: Path = STORIES_DIR) -> Story`
    - `def import_story(db: Session, story: Story) -> RabbitHole`
    - `def main(argv: list[str] | None = None) -> int`, an argparse CLI with subcommand `import <slug>`, which prints `Imported <slug>: <n> discoveries`. A `StoryError` prints `stories/<slug>.md: line N: message` and returns 1.

**Compile mapping (`import_story`), in one transaction:**
- **Existing trail:** delete the `RabbitHole` with the same slug first. Its nodes and edges cascade, but `Source` rows stay.
- **`RabbitHole`:** `question = story.hook[:500]`, `title = story.title[:120]`, plus the slug, `published_at` and `territory`.
- **Root node:** `stage="hook"`, `title=story.title`, `summary=story.hook`, `connection_reason="Where the rabbit hole opens."`, `exploration_question=""`, `domain=story.territory or "Rabbit hole"`.
- **The chain:** each of Entry, the Descent discoveries in order, and the Leap is the child of the one before. For each: `stage`, `evidence`, `title`, `summary=body or why`, `connection_reason=why`, `check_note=check`, `exploration_question=""`, and `domain` as for the root.
- **Exit node:** child of the Leap, with `stage="exit"`, `evidence=None`, `title="What we know"`, `summary=known`, `connection_reason="Where the trail stands."`, `exploration_question=open`.
- **Edges:** an `Edge` per parent-child link, with `relationship_note` = the child's `connection_reason`.
- **Sources:** look up `Source` by URL. Create it if missing, otherwise update `title`, `medium`, `creator` and `published`. `publisher = creator or host`.

- [ ] **Step 1: Write the failing tests.** Use an in-memory engine fixture like `test_api.py`'s, and the `VALID` story from Task 2 (import it from `test_story`):
  - `test_import_builds_one_chain`: 6 nodes (root, entry, 2 descent, leap, exit) and 5 edges. The stages run in chain order. The root's `parent_id` is None, and each other node's parent is the previous one.
  - `test_reimport_replaces_not_duplicates`: importing twice leaves 1 `RabbitHole` with that slug and 6 nodes.
  - `test_shared_source_survives_other_story_reimport`: stories A and B cite the same URL. Re-importing A keeps the `Source` row, still linked to B's node.
  - `test_add_missing_columns_backfills_old_db`: a SQLite file DB created with a `CREATE TABLE nodes (...)` lacking `stage`. After `add_missing_columns`, `PRAGMA table_info(nodes)` lists `stage`, `evidence` and `check_note`.
  - `test_cli_reports_story_error`: `main(["import", "bad"])` with a tmp `stories_dir` holding a bad file returns 1. Its output includes `line` (use `capsys`; let `main` take an optional `stories_dir`).
- [ ] **Step 2: Run them and confirm they fail.** Run: `python -m pytest backend/tests/test_studio.py -q`. Expected: ImportError on `backend.studio`.
- [ ] **Step 3: Implement** the models, `add_missing_columns`, the call in `main.py`, `studio.py` import, the `.gitignore` line and `stories/.gitkeep`.
- [ ] **Step 4: Run all backend tests and confirm they pass.** Run: `python -m pytest backend/tests -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -m "Compile story files into trails with stage, evidence and source metadata"`

### Task 4: Publish an allowlisted snapshot

**Files:**
- Modify: `backend/studio.py` (`publish`)
- Modify: `README.md` (replace the "Refresh the snapshot" `VACUUM INTO` instructions with `python -m backend.studio publish`)
- Test: `backend/tests/test_studio.py` (append)

**Interfaces:**
- Consumes: Task 3's `import_story` and `load_story`.
- Produces: `def publish(stories_dir: Path, out_path: Path, today: date) -> list[str]`, which returns the published slugs, sorted. It's the CLI subcommand `publish`, printing `Published N stories to showcase/ronin.db`.

**How it works:**
- It parses every `*.md` in `stories_dir`. Any `StoryError` aborts with nothing written.
- It keeps the stories with `published` set and `<= today`, and copies each with `check=None` on every discovery, `drafted_by=None`, `prompt=None` and `note=None`. That's the allowlist.
- It imports them into a fresh SQLite file at `out_path + ".tmp"`, created with `Base.metadata.create_all`, then `os.replace`s it over `out_path`. The swap is atomic, so a failed publish leaves the old snapshot.

- [ ] **Step 1: Write the failing tests:**
  - `test_publish_excludes_drafts_and_future`: a tmp dir with three stories (published yesterday, no date, published tomorrow) returns only the first slug. The output DB holds exactly 1 `RabbitHole`.
  - `test_publish_strips_private_fields`: a story with `check:` lines, a note, `drafted_by` and `prompt`. After publish, a raw `sqlite3` scan of every TEXT column in every table contains neither the check text, the note text, the `drafted_by` value nor `draft-v1`. `nodes.check_note` is NULL everywhere.
  - `test_publish_failure_keeps_old_snapshot`: an existing `out_path` file, plus one malformed story, raises `StoryError`, and the old file's bytes are unchanged.
- [ ] **Step 2: Run them and confirm they fail.** Run: `python -m pytest backend/tests/test_studio.py -q -k publish`. Expected: AttributeError or ImportError for `publish`.
- [ ] **Step 3: Implement** `publish`, the CLI subcommand and the README update.
- [ ] **Step 4: Run all backend tests and confirm they pass.** Run: `python -m pytest backend/tests -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -m "Publish only allowlisted, published stories to the showcase snapshot"`

### Task 5: Search adapters for YouTube and Reddit

**Files:**
- Create: `backend/sources/__init__.py`, `backend/sources/youtube.py`, `backend/sources/reddit.py`
- Test: `backend/tests/test_sources.py`

**Interfaces:**
- Produces:
  - In `backend/sources/__init__.py`: `@dataclass(frozen=True) class Found: title: str; url: str; medium: str; creator: str | None; date: str | None; snippet: str` and `class SourceUnavailable(Exception)`, raised for a missing key.
  - `youtube.search(query: str, *, limit: int = 8, transport: httpx.BaseTransport | None = None) -> list[Found]`. It calls `GET https://www.googleapis.com/youtube/v3/search?part=snippet&type=video&maxResults=<limit>&q=<query>&key=<YOUTUBE_API_KEY>`. Each item becomes `Found(title=snippet.title, url="https://www.youtube.com/watch?v=<videoId>", medium="video", creator=snippet.channelTitle, date=snippet.publishedAt[:10], snippet=snippet.description[:300])`. HTML entities in the title are unescaped with `html.unescape`.
  - `reddit.search(query: str, *, limit: int = 8, transport=None) -> list[Found]`. It gets a token with `POST https://www.reddit.com/api/v1/access_token`, `grant_type=client_credentials`, basic auth from the two env keys. Then `GET https://oauth.reddit.com/search?q=<query>&limit=<limit>&sort=relevance&type=link`, with header `User-Agent: ronin-studio/1.0 (local research tool)`. Each post becomes `Found(title=data.title, url="https://www.reddit.com" + data.permalink, medium="reddit", creator="u/" + data.author, date=<created_utc as ISO date>, snippet="r/" + data.subreddit)`. **`selftext` is never read.**
  - Both raise `SourceUnavailable` when keys are missing, and `httpx.HTTPError` or `SourceUnavailable("...status...")` on a non-2xx response.

- [ ] **Step 1: Write the failing tests.** Use `httpx.MockTransport` handlers with canned JSON:
  - `test_youtube_parses_videos`: one item produces the expected `Found`. The API key is in the query string, and `&amp;` in the title is unescaped.
  - `test_youtube_without_key_is_unavailable`: `pytest.raises(SourceUnavailable)`
  - `test_reddit_keeps_permalink_and_drops_body`: the canned post has `selftext: "SECRET BODY"`. The result URL starts `https://www.reddit.com/r/`, and `"SECRET BODY"` appears in no field of the `Found` (check with `repr`). The User-Agent header is sent on both requests.
  - `test_reddit_without_keys_is_unavailable`
- [ ] **Step 2: Run them and confirm they fail.** Run: `python -m pytest backend/tests/test_sources.py -q`. Expected: ModuleNotFoundError.
- [ ] **Step 3: Implement** the three files. Add `YOUTUBE_API_KEY`, `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` to the conftest `AI_ENVIRONMENT` tuple.
- [ ] **Step 4: Run all backend tests and confirm they pass.** Run: `python -m pytest backend/tests -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -m "Add YouTube and Reddit search adapters"`

### Task 6: Web and Wayback adapters, and the fan-out search

**Files:**
- Create: `backend/sources/web.py`, `backend/sources/archive.py`
- Modify: `backend/sources/__init__.py` (add `search_all`)
- Test: `backend/tests/test_sources.py` (append)

**Interfaces:**
- Consumes: Task 5's `Found`, `SourceUnavailable`, `youtube` and `reddit`.
- Produces:
  - `web.search(query: str, *, limit: int = 8, transport=None, generate=None) -> list[Found]`. It runs a Gemini call with the `google_search` tool (same config as `ai._grounded_sources`; `generate` is an injectable callable returning the response, defaulting to the real client call). It reads `grounding_chunks[].web.{uri,title}`, then resolves each URI with `httpx` `HEAD`, following redirects (falling back to `GET` on a 405). The final URL is kept, and a URI that fails to resolve is dropped. The result is `medium="page"`, `creator=<final host without www.>`, `date=None`, `snippet=""`. A missing `GEMINI_API_KEY` raises `SourceUnavailable`.
  - `archive.snapshots(urls: list[str], *, transport=None) -> list[Found]`. For each URL, `GET https://archive.org/wayback/available?url=<url>`. When `archived_snapshots.closest.available` is set, it returns `Found(title="Archived: <url>", url=closest.url, medium="archive", creator="Internet Archive", date=<timestamp[:8] as YYYY-MM-DD>, snippet=url)`. It needs no key and caps at the first 20 URLs.
  - `def search_all(queries: list[str], *, providers: dict[str, Callable[[str], list[Found]]] | None = None, cap: int = 60) -> tuple[list[Found], list[str]]`. It returns the finds and the skipped-provider notes, such as `"youtube: no key"` or `"reddit: <error class name>"`. The default providers are `web`, `youtube` and `reddit`. It runs each provider over each query, catching `SourceUnavailable` and `httpx.HTTPError` per provider. A provider that's unavailable once is skipped for the remaining queries and noted once. It then calls `archive.snapshots` on the page URLs found, dedupes by URL keeping the first, and caps the total.

- [ ] **Step 1: Write the failing tests:**
  - `test_web_resolves_redirects_and_drops_dead`: a fake `generate` returns two chunks. A MockTransport redirects the first `vertexaisearch.cloud.google.com/...` URI with a 302 to `https://www.example.org/page`, and returns 500 for the second. The result is one `Found` with url `https://www.example.org/page` and creator `example.org`.
  - `test_archive_maps_closest_snapshot`: a canned response with timestamp `20030501123000` gives date `2003-05-01` and medium `archive`.
  - `test_search_all_dedupes_caps_and_notes_skips`: fake providers. `youtube` raises `SourceUnavailable` and is called only once across 3 queries. `web` returns the same URL twice. The result has unique URLs and the notes are `["youtube: no key"]`. With `cap=1`, there's 1 find. Patch `archive.snapshots` to return `[]`.
- [ ] **Step 2: Run them and confirm they fail.** Run: `python -m pytest backend/tests/test_sources.py -q`. Expected: AttributeError or ModuleNotFoundError.
- [ ] **Step 3: Implement** `web.py`, `archive.py` and `search_all`.
- [ ] **Step 4: Run all backend tests and confirm they pass.** Run: `python -m pytest backend/tests -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -m "Add web and Wayback adapters and fan-out search"`

### Task 7: Draft and redraft

**Files:**
- Modify: `backend/schemas.py` (draft schemas), `backend/ai.py` (two generation functions), `backend/studio.py` (`draft`, `redraft`, CLI subcommands)
- Test: `backend/tests/test_studio.py` (append)

**Interfaces:**
- Consumes: Task 1's `_structured(only=)` and `last_provider_model()`. Task 2's `Story`, `Discovery`, `SourceRef` and `render_story`. Task 6's `search_all` and `Found`.
- Produces (in `schemas.py`):
  - `PlannedQuery(text: str, angle: Literal["origin","stranger","counterpoint","old-web","japanese"])`, `QueryPlan(queries: list[PlannedQuery] = Field(min_length=4, max_length=8))`
  - `DraftDiscovery(title: str, evidence: Literal[...5 values], why: str, body: str, sources: list[int])`, `DraftStory(title: str, hook: str, entry: DraftDiscovery, descent: list[DraftDiscovery] = Field(min_length=1, max_length=6), leap: DraftDiscovery, known: str, open: str)`
- Produces (in `ai.py`):
  - `def plan_queries(seed: str, only: tuple[str, str] | None = None) -> QueryPlan`
  - `def write_draft(seed: str, finds: list[dict], only: tuple[str, str] | None = None) -> DraftStory`. The finds are numbered from 1 in the prompt as `[n] medium · title · creator · date · url · snippet`.
  - Both prompts contain the word "JSON" and the target shape. The `write_draft` prompt carries the editorial bar from the spec: intriguing over educational; every discovery changes understanding or opens a question; never manufacture mystery; investigate conspiracies, never invent them; keep facts, claims, interpretation and speculation apart; cite only by find number.
- Produces (in `studio.py`):
  - `RESEARCH_DIR = STORIES_DIR / ".research"`
  - `def draft(seed: str, slug: str, *, model: str | None = None, stories_dir: Path = STORIES_DIR, search=search_all) -> Path`
  - `def redraft(slug: str, *, model: str, out: Path, stories_dir: Path = STORIES_DIR) -> Path`
  - `def compile_draft(slug: str, draft: DraftStory, finds: list[dict], drafted_by: str, note: str | None) -> Story`. The mapping:
    - Each source number `n` maps to `finds[n-1]` as a `SourceRef`. An out-of-range number is dropped, and the count goes into the note as `"dropped N invented source numbers"`.
    - A `fact` or `claim` left with no sources becomes `speculation`, with check `"needs a source; verify before publishing"`.
    - Every other discovery gets check `"verify before publishing"`.
    - `prompt="draft-v1"`, `published=None`.
  - `model` / `--model` takes the form `provider/model`, split on the first `/`, and becomes `only`.

**`draft` flow:**
1. Refuse if `stories/<slug>.md` exists (raise `FileExistsError`).
2. `plan_queries`.
3. `search(query texts)` returns finds and notes.
4. Write `RESEARCH_DIR/<slug>.json` = `{"seed", "queries", "finds": [asdict(f)], "skipped": notes}`.
5. `write_draft`.
6. `compile_draft` with `drafted_by=last_provider_model()` and `note="skipped: " + "; ".join(notes)` when there are notes.
7. `render_story` to `stories/<slug>.md`.

**`redraft`** loads the research JSON, then runs steps 5–7, writing to `out` (refusing if `out` exists). It never searches.

The CLI subcommands are `draft "<seed>" --slug S [--model P/M]` and `redraft S --model P/M --out FILE`.

- [ ] **Step 1: Write the failing tests.** Monkeypatch `ai.plan_queries` and `ai.write_draft`, pass a fake `search`, and use a tmp `stories_dir`:
  - `test_draft_writes_story_and_research`: the story file parses with `parse_story`. The research JSON has `finds` and `skipped`. The story has `drafted_by` set (patch `ai.last_provider_model` to return `"deepseek/deepseek-flash"`) and `prompt == "draft-v1"`.
  - `test_invented_source_numbers_are_dropped_and_noted`: the draft cites `[1, 99]` with one find. The discovery keeps 1 source, and the note contains `dropped 1`.
  - `test_unsourced_fact_becomes_speculation`: a `fact` with `sources=[]` becomes `evidence == "speculation"`, and its check contains `needs a source`.
  - `test_draft_refuses_to_overwrite`: an existing `stories/<slug>.md` raises `FileExistsError`, and `ai.plan_queries` is not called.
  - `test_redraft_reuses_finds_without_search`: after a `draft`, `redraft(slug, model="kimi/kimi-k3.1-pro", out=tmp/"b.md")` with a `search` that raises `AssertionError`. `ai.write_draft` receives `only=("kimi", "kimi-k3.1-pro")`, and `b.md` parses.
- [ ] **Step 2: Run them and confirm they fail.** Run: `python -m pytest backend/tests/test_studio.py -q -k "draft"`. Expected: failures (missing functions).
- [ ] **Step 3: Implement** the schemas, `plan_queries`, `write_draft`, `compile_draft`, `draft`, `redraft` and the CLI subcommands. Set `_local.provider = None` before each `_structured` call, as the existing generators do.
- [ ] **Step 4: Run all backend tests and confirm they pass.** Run: `python -m pytest backend/tests -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -m "Add AI story drafting and same-finds redraft for model bake-offs"`

### Task 8: API exposes story fields, with no private ones

**Files:**
- Modify: `backend/schemas.py` (`NodeOut`, `SourceOut`, `GraphOut`), `backend/main.py` (`_node_out`, `_graph`)
- Test: `backend/tests/test_api.py` (append)

**Interfaces:**
- Consumes: Task 3's columns and `import_story`.
- Produces:
  - `NodeOut` gains `stage: str | None = None` and `evidence: str | None = None`.
  - `SourceOut` gains `medium`, `creator` and `published` (all `str | None = None`).
  - `GraphOut` gains `slug: str | None = None`, `territory: str | None = None` and `published_at: date | None = None`.
  - `check_note` is **not** added to any schema, so it never leaves the server.

- [ ] **Step 1: Write the failing tests:**
  - `test_authored_trail_exposes_stage_evidence_and_source_meta`: `import_story` into the test DB through the `client` fixture's session (add a small fixture yielding the `TestingSession`). `GET /api/rabbit-holes/{id}` shows the nodes' stages in chain order, the leap evidence `interpretation`, the first source's medium `archive`, and the slug.
  - `test_check_note_never_in_api`: `"verify before publishing"` (a check line in the story) does not appear in `response.text`.
- [ ] **Step 2: Run them and confirm they fail.** Run: `python -m pytest backend/tests/test_api.py -q -k "authored or check_note"`. Expected: KeyError or assertion failures.
- [ ] **Step 3: Implement** the schema fields and their population.
- [ ] **Step 4: Run all backend tests and confirm they pass.** Run: `python -m pytest backend/tests -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -m "Expose story stage, evidence and source metadata in the API"`

### Task 9: Reader view (chips, source metadata, session visits, authored Leap card)

**Files:**
- Modify: `src/types.ts`, `src/App.tsx` (detail panel and `selectNode`), `src/views.tsx` (`RecapView`), `src/leapCard.ts` (optional `footer`), `src/styles.css`
- Create: `src/AuthoredLeap.tsx`

**Interfaces:**
- Consumes: Task 8's API fields, plus the existing `drawLeapCard`, `downloadLeapCard` and `loadCardFonts`.
- Produces:
  - In `types.ts`: `Concept` gains `stage?: string | null; evidence?: string | null`. `Source` gains `medium?`, `creator?` and `published?: string | null`. `Graph` gains `slug?`, `territory?` and `published_at?: string | null`.
  - In `leapCard.ts`: `LeapCardData` gains an optional `footer?: string`. When it's set, it replaces the `N hops · M subjects crossed` footer text.
  - `export function authoredLeap(graph: Graph): LeapCardData | null`. It returns null unless the graph has a `stage === 'leap'` node. Otherwise:
    - `question` = `graph.question` (the hook)
    - `end` = the leap title
    - `hook` = `graph.question`
    - `reframe` = the leap's `connection_reason`
    - `waypoints` = the descent titles in chain order, up to 3
    - `hops` = the leap's depth, `domains` = 0
    - `footer` = `` `${descentCount + 2} discoveries · ${sourceCount} sources` ``
  - `export function AuthoredLeap({ graph }: { graph: Graph })`: a canvas preview plus a **Download PNG** button. No AI, no editing.
- `RecapView`: if `authoredLeap(graph)` is not null, render `<AuthoredLeap>` (in read-only mode too). Otherwise keep `{!readOnly && <LeapEditor/>}`.
- **Detail panel:** under the title, show a stage label (`HOOK` / `ENTRY` / `DESCENT` / `LEAP` / `EXIT`) and an evidence chip with the text `Verified fact` / `Attributed claim` / `Interpretation` / `Speculation` / `Open question`. Each source row shows its medium, creator and date as small mono text when present.
- **Session visits:** in `selectNode`, when `readOnly`, set `graph` locally with that node's `explored: true` and return without calling the API. A reload refetches, which clears it.

- [ ] **Step 1: Implement** the above, reusing the existing tokens for the chips (`--rust` for fact, `--indigo` for interpretation and speculation, `--muted` for open).
- [ ] **Step 2: Type-check and build.** Run: `npm run build`. Expected: the build succeeds.
- [ ] **Step 3: Write a sample story** at `stories/sample-lost-forum.md`, a clearly fictional placeholder titled "Sample: a forum that vanished", with `published:` set to yesterday and at least one source per medium (example.org URLs). Then run `python -m backend.studio import sample-lost-forum` and `python -m backend.studio publish`, and confirm it prints `Published 1 stories`.
- [ ] **Step 4: Browser verification** with the `ronin-verify` skill. Start the API with `RONIN_READ_ONLY=1` and `RONIN_DATABASE_URL` pointing at `showcase/ronin.db`, plus Vite. Then:
  - Open the sample trail. The stage and evidence chips show in the detail panel.
  - Sources show the medium, creator and date.
  - Opening nodes marks them visited, and the network panel shows no `/visit` and no `/leaps` request. A reload clears the marks.
  - The recap shows the authored Leap card with the right hook, reframe and footer, and `toBlob` yields 1080×1350.
  - Check at a 375px and a desktop width.
- [ ] **Step 5: Undo the verification snapshot.** Delete `stories/sample-lost-forum.md` and restore the committed snapshot with `git checkout -- showcase/ronin.db`. Don't commit a regenerated snapshot: with no real story yet, it would deploy an empty archive. The first real publish is the author's call. Commit the code only: `git commit -m "Show story stages, evidence and authored Leap card to readers"`
