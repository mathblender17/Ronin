# Leap Card — design

Date: 2026-10-25 · Status: awaiting review · Sub-project A of the rabbit-hole roadmap

## Why

Ronin should be a machine for discovering rabbit holes, not a curiosity engine. The first thing to test is whether
people find something in a trail they genuinely want to show someone else. The Leap Card is that test: a
shareable image of the most surprising, still-defensible connection in a user's own trail.

Out of this sub-project, by decision: typed expansion paths (sub-project B) and real YouTube/web source discovery
(sub-project C).

## Decisions

| Question | Decision |
|---|---|
| Emotional payoff | "Wait, WHAT?" — lead with an unexpected connection, not a summary of what the user did. |
| Kind of surprise | Impossible-looking link (two distant endpoints) as the hook, explained by a reframing line. Hidden-discovery cards wait for real sources. |
| Allowed endpoints | Root question → a node the user actually visited, along the real tree path. |
| Selection | Embedding drift shortlists, the LLM writes copy, the user picks and edits. |
| Output | PNG download only. No public links, no hosting, no new privacy surface. |
| Layouts | Leap only. Insight and Trail layouts are deferred. |

## User flow

1. In the recap view, the user clicks **Find my leap**.
2. Ronin returns up to three candidates. Each shows the start question, the end node, 2–3 real waypoints, a hook line and a reframing line.
3. The user picks one, edits the hook and reframe, optionally hides waypoints, and clicks **Download PNG**.
4. **Pick a node instead** lets the user tap any eligible visited node; Ronin writes copy for that path.

Eligibility: at least one visited node at depth ≥ 2. Otherwise the button is disabled with "Go one layer deeper to find a leap."
The button is hidden in read-only showcase mode.

## Scoring (backend)

Adapted from `spike/drift.py`.

- Candidates: every visited node at depth ≥ 2; its path is root → … → node via `parent_id`.
- Text embedded per node: `title + ". " + summary`, one `gemini-embedding-001` batch per request.
- Subtract the trail's mean vector from every vector, so the shared topic does not dominate distances.
- `end_distance = 1 − cos(root, node)`
- `weakest_hop = min(cos(parent, child))` over the path's hops
- `score = end_distance × weakest_hop` — one incoherent hop sinks the leap. No depth term: depth is not surprise.
- Shortlist: greedily take the highest scores, skipping a candidate whose first-level branch is already taken while
  other branches remain; at most 3.
- Embeddings are not stored. `shortcut: re-embeds every request, add a node_embeddings cache if latency hurts.`

## Copy generation (backend)

One structured call through the existing `_structured` provider layer, new schema `LeapCopy` with one entry per candidate:

- `hook` ≤ 12 words: the "Wait, WHAT?" line about the two endpoints.
- `reframe` ≤ 25 words: why the leap makes sense, phrased as an interpretation.
- `waypoints`: 2–3 titles copied from the path's interior nodes.

The prompt receives each path's titles and stored `connection_reason`s and may only use those facts. The backend
drops any waypoint that is not an exact interior title of that path; if fewer than one valid waypoint remains it uses
the path's middle node.

## API

`POST /api/rabbit-holes/{hole_id}/leaps` — body optional: `{"node_id": "<id>"}` to score/write only that path.

Response:

```json
{
  "ranked": true,
  "candidates": [
    {"node_id": "…", "path": ["root title", "…", "end title"], "waypoints": ["…"],
     "hook": "…", "reframe": "…", "score": 0.41, "hops": 4, "domains": 3}
  ]
}
```

- `ranked: false` when embeddings fail or no Gemini key exists: candidates are empty unless `node_id` was given.
- 400 when the trail has no eligible node, or `node_id` is not eligible.
- 403 in read-only mode (`_require_writable`).
- Copy-generation provider errors use the existing error mapping.

## The card (frontend)

1080×1350 PNG (4:5), top to bottom:

1. `RONIN · A LEAP` masthead
2. "Started with:" + root question (small, max 2 lines)
3. Hook (large, max 3 lines)
4. "Ended at:" + end node title
5. Chain: start → waypoints → end, vertical line with dots
6. Reframe, labelled "interpretation"
7. Footer: `N hops · M subjects crossed` + wordmark

It must read without any knowledge of Ronin.

Rendering: one `drawLeapCard(ctx, card)` using Canvas 2D (`fillText` + word wrap), called after `document.fonts.ready`.
It draws both the live preview and the export, then `canvas.toBlob` downloads `ronin-leap-<slug>.png`. No new dependency.

Editor: candidate tabs plus "Pick a node instead" on the left; preview with editable hook/reframe fields on the right.
Waypoints can be toggled off, not rewritten.

## Evaluation gate

Before the button ships, `backend/benchmark/leaps.py` runs the scorer over every saved trail in `data/ronin.db` and writes a
markdown table: top 3 per trail with `end_distance`, `weakest_hop`, score, path and an empty WHAT / ok / nonsense column.

Bar: at least half of the #1 picks are labelled WHAT or ok, and none are nonsense. If missed, tune the formula, or ship
with "Pick a node" as the default and ranking hidden.

## Tests

- Scorer (synthetic vectors): a path with one incoherent hop ranks below a smooth one; a deeper path does not win on
  depth alone; the shortlist spreads across first-level branches.
- Endpoint: invented waypoints are dropped; read-only → 403; embedding failure → `ranked: false`; `node_id` override;
  no eligible node → 400.
- Frontend: type-check, build, browser check of the editor and a downloaded PNG (`ronin-verify`).

## Success signal

You and early users download a Leap card from a real trail and would post it without heavy editing. v1 adds no
analytics code; observe this by hand in early sessions (which candidate was picked, how much the hook was edited).

`domains` in the response is the number of distinct `domain` values along the path ("subjects crossed").
