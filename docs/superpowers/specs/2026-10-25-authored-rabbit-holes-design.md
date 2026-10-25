# Authored Rabbit Holes: design

Date: 2026-10-25 · Status: awaiting review · Pivot piece 2 of 4

## Why

Ronin is pivoting from a tool you open with a question to **a rabbit-hole publication whose stories you can explore**.
One flagship rabbit hole a week: intriguing, not educational. It should make the familiar feel unfamiliar.
The first audience is internet archaeologists (lost media, dead sites, meme origins, old forums).

The publication is the front door. The explorable trail is the product.

### Pivot pieces

| # | Piece | Code | Order |
|---|---|---|---|
| 1 | Research sprint: 10 candidates, pick one flagship | no | in parallel |
| 2 | **This spec**: AI-drafted, human-edited stories, published as explorable trails | yes | first |
| 3 | Website: archive front door, "this week's rabbit hole" | yes | after 2, own spec |
| 4 | Social hooks (Reels / Shorts / X) | no | after 1 |

### Decisions

| Question | Decision |
|---|---|
| How a story enters Ronin | The AI drafts it from real search results. The author edits it, then publishes. |
| Sources in v1 | Web (Gemini Google grounding), YouTube Data API, Wayback Machine, Reddit (approved OAuth app, read-only) |
| Where editing happens | Local studio on the author's machine. The public site stays the existing read-only showcase. No login or admin is built. |
| Editing tool | A markdown story file in the author's own editor. No editor screen. |
| Reader v1 | Follow the route, open each discovery (sources plus evidence label), see why steps connect, download the Leap card. No branching, saving or accounts. |
| AI models | Model-agnostic. Gemini and OpenRouter stay. DeepSeek and Kimi are added through one generic OpenAI-compatible adapter. A bake-off on one real story decides which model drafts. |
| Layers | Models draft, sources supply evidence, the author decides. Search never depends on which model drafts, except web search, which uses Gemini grounding in v1. |
| Old question trails | Not published. The public site holds published stories only. Old trails stay in the local DB. |
| Out of scope | Homepage redesign (piece 3), social content, reader branching or saving, scheduling, local uncensored model, daily cadence, structured competing interpretations (write them in the body for now), release tooling beyond git and Render (rollback = `git revert` + redeploy) |

## Story file

One file per rabbit hole, at `stories/<slug>.md`. A file with no `published:` date is a draft.

```markdown
---
title: The forgotten worlds of the early Japanese internet
slug: early-japanese-web
published: 2026-11-02
territory: Internet archaeology
drafted_by: deepseek/deepseek-chat
prompt: draft-v1
---
## Hook
How can a whole digital world vanish while pieces of it survive?

## Entry
### A Geocities Japan homepage, still mirrored
evidence: fact
why: Where the trail starts.
A short body paragraph.
sources:
- [Wayback capture](https://web.archive.org/web/2003/...) · archive · Internet Archive · 2003-05-01

## Descent
### <discovery title>
evidence: claim
why: <how it follows from the step before>
<body>
sources:
- [title](url) · video · <creator> · <YYYY-MM-DD>

## Leap
### <the connection>
evidence: interpretation
why: <the reframe line for the Leap card>
<body>
sources: ...

## Exit
known: <what is established>
open: <what remains unresolved>
```

Rules, enforced by the parser:
- The sections appear exactly once, in this order: Hook, Entry, Descent, Leap, Exit. Entry and Leap each hold exactly one `###` discovery. Descent holds 1–6.
- `evidence` is one of `fact` (verified), `claim` (attributed to its source), `interpretation` (Ronin's reading), `speculation` (a theory, labelled as one), `open` (unresolved).
- A `fact` or a `claim` needs at least one source.
- A source is `- [title](url) · medium · creator · date`. `medium` is one of `video`, `page`, `archive`, `reddit`. The URL must be http(s). Creator and date are optional, and the date is ISO.
- A `reddit` source is the permalink, title and author only. Post text is never copied into the story, and Reddit content is never used to train or tune models. An anecdote from Reddit can be a `claim`, never a `fact`.
- An optional `check:` line is a note to the author. It never leaves the local studio.
- Frontmatter has `title`, `slug` (`[a-z0-9-]+`, matching the filename), optional `published` (ISO date), optional `territory`, and the draft metadata `drafted_by` (`provider/model`) and `prompt` (prompt version). The draft metadata is kept for reproducibility and never shown to readers.

Errors name the file, line number and rule. A bad file writes nothing.

## Draft step

`python -m backend.studio draft "<seed idea>" --slug <slug> [--model provider/model]`. It refuses to overwrite an existing file.
`python -m backend.studio redraft <slug> --model provider/model --out <file>` skips steps 1–2 and rewrites from the saved finds. That makes a model bake-off: the same finds and brief, a different model, side-by-side files.

1. **Fan out.** One LLM call through the existing provider layer returns 4–8 search queries from the seed, each tagged with an angle: `origin`, `stranger`, `counterpoint`, `old-web`, `japanese`.
2. **Search.** Each query goes to every configured provider in `backend/sources/`. Every provider returns `list[Found]`, where `Found(title, url, medium, creator, date, snippet)`.
   - `web`: Gemini Google-grounded search, reusing the grounding pattern in `ai.py`. Needs `GEMINI_API_KEY`.
   - `youtube`: YouTube Data API v3 `search.list`. Needs `YOUTUBE_API_KEY`.
   - `archive`: Wayback `available` and CDX for URLs from the other providers, plus a CDX query for the seed's domains where given. No key.
   - `reddit`: OAuth client-credentials, read-only search. Needs `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` and a descriptive User-Agent. No scraping of reddit.com HTML.
   - A provider with no key is skipped. One that fails is logged and skipped. The draft lists the skipped providers in a top comment.
   - Duplicates by URL are dropped. The list is capped at 60 finds.
   - The seed, queries and finds are saved to `stories/.research/<slug>.json`. That's the research dossier: local only and git-ignored, never published.
3. **Write.** One LLM call gets the seed and the numbered finds, and returns structured sections whose sources are find numbers only. Code renders the markdown:
   - An unknown find number is dropped.
   - A `fact` or `claim` left with no source becomes `speculation`, with `check: needs a source`.
   - Every discovery gets `check: verify before publishing`. The author deletes these as they go.
4. **Save.** Writes `stories/<slug>.md` with no `published:` field, and with `drafted_by` and `prompt` filled in.

### Model providers

`backend/ai_providers.py` gains one generic OpenAI-compatible call: the existing `openrouter_generate_json` with the base URL as a parameter. Named providers:

| Provider | Base URL | Key |
|---|---|---|
| `openrouter` | existing | `OPENROUTER_API_KEY` (free-only policy unchanged) |
| `deepseek` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |
| `kimi` | `https://api.moonshot.ai/v1` | `MOONSHOT_API_KEY` |

DeepSeek and Kimi are paid APIs. They're only called when named in `RONIN_AI_PROVIDER_ORDER` or `--model`, which counts as an explicit choice. The existing retries, cooldowns and error mapping apply to every provider. A model-provider fallback never changes which search providers run.

The prompt states the editorial bar: intriguing over educational, every discovery must change the reader's understanding or open a new question, and never manufacture mystery. Conspiracies are investigated, not invented, with facts, allegations and theories kept apart.

## Import and publish

- `python -m backend.studio import <slug>` parses the file and writes one trail into the local DB (`data/ronin.db`). If a trail with that slug already exists, it is replaced. The trail is a single chain: Hook = root → Entry → Descent… → Leap → Exit. Each node has a `stage` and `evidence`. `why` becomes the node's `connection_reason`. The Exit node's summary is `known`, and its `exploration_question` is `open`.
- `python -m backend.studio publish` deletes and rebuilds `showcase/ronin.db` from every story file that has a `published:` date on or before today, and prints the count. Drafts never ship. Committing and deploying stay manual.
- Publish writes an **allowlist** only: story title, slug, territory, published date, the nodes' reader-facing text, stage and evidence, and the sources' title, URL, medium, creator and date. `check_note`, `drafted_by`, `prompt` and the research dossier are never written. The local DB is never copied.
- Preview before deploy: run Ronin with `RONIN_READ_ONLY=1` against the rebuilt `showcase/ronin.db`.

## Data model

These are nullable additions, so existing trails keep working:

- `rabbit_holes`: `slug` (unique when set), `published_at`, `territory`
- `nodes`: `stage`, `evidence`, `check_note`
- `sources`: `medium`, `creator`, `published`

Ronin has no migrations. At startup, a SQLite-only helper adds any missing nullable columns with `ALTER TABLE ... ADD COLUMN`. It's marked `shortcut: add-only, no renames or drops, use Alembic once the schema changes shape`.

`check_note` exists only in the local DB, and publish never writes it.

## Reader view (v1)

This keeps the existing explorer and recap.
- Each node shows its stage label (Hook, Entry, Descent, Leap, Exit) and an evidence chip (`fact` / `claim` / `interpretation` / `speculation` / `open`).
- On the read-only site, the nodes a reader has opened are marked as visited for this browser session only, held in client state. No tracking, no server write.
- Sources show a medium icon, creator and date.
- For authored trails, the Leap card is filled from the story: hook = the Hook text, reframe = the Leap's `why`, end = the Leap title, waypoints = the Descent titles (up to 3). It needs no AI call, so it also works on the read-only site. The download button is shown in read-only mode for authored trails only.

## Testing

- Parser: one valid file round-trips. Each rule has a failing-file test that asserts the line number in the error.
- Draft: providers and LLM mocked. An unknown find number is dropped, an unsourced fact or claim is downgraded to speculation, an existing file is not overwritten, skipped providers are listed, the finds are saved, and `redraft` reuses them without searching.
- Search providers: one test each with an httpx mock transport, as in the existing OpenRouter tests, covering parsing and the missing-key skip. Reddit stores no post body.
- Model providers: DeepSeek and Kimi hit their own base URLs with their own keys, and are skipped when not named.
- Import: a re-import replaces rather than duplicates. Stages and evidence are stored.
- Publish: drafts, future-dated stories and old question trails are excluded. The output DB holds exactly the published slugs, and contains no `check_note`, `drafted_by` or `prompt` value anywhere.
- Read-only: the authored Leap card works without AI, and visited state never calls the server.
- Frontend: type-check, build, browser check of the stage and evidence chips and the authored Leap card.

## Model bake-off (before adding more providers)

Run on the first real story. Same finds, same brief, each of Gemini, DeepSeek and Kimi via `redraft`. The author compares:
1. Unexpected but defensible connections.
2. Claim accuracy against the finds.
3. Narrative intrigue and pacing.
4. Citation fidelity (dropped or invented find numbers are counted by the draft step).
5. Cost, latency and whether the structured output came back valid.

The winner becomes the `RONIN_AI_PROVIDER_ORDER` default for drafting. No provider is added beyond these three until the bake-off is done.

## Success signal

One flagship story goes from seed to published trail in one week, with the author's editing time spent on judgment rather than formatting. Readers who arrive from a social post open at least one discovery's sources.
