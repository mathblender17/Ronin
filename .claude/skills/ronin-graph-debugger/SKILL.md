---
name: ronin-graph-debugger
description: Diagnose and fix Ronin graph problems (missing or misplaced nodes, broken or invisible edges, wrong parent-child structure, layout overlap, fit/focus or collapse misbehaving, stale graph after expand or visit). Use when the user reports a graph bug, a React Flow symptom, or data that appears in the API but not on the canvas. Traces data from Gemini generation through backend validation, SQLite persistence, API, frontend state, and React Flow.
---

# Ronin Graph Debugger

Find the root cause before editing anything. A symptom on the canvas usually originates earlier in the pipeline.

## Data path to trace

1. **Generation** (`backend/ai.py`): `generate_initial`, `generate_expansion`, `unique_concepts`, `_structured`. Gemini output is parsed into `InitialLayer` / `ExpansionLayer` (`backend/schemas.py`, `GeneratedConcept`).
2. **Persistence** (`backend/main.py`): `create_rabbit_hole`, `expand_node`, `_save_concept`, `_load_hole`. Models are in `backend/models.py` (`RabbitHole`, `Node`, `Edge`). Schema creation is in `backend/database.py`.
3. **API shape**: `_graph` and `_node_out` produce `GraphOut`, with `nodes` and `edges` (`source`, `target`) plus `metrics`. Check `backend/schemas.py` for the exact fields.
4. **Frontend client and state**: `src/api.ts` (`api.get`, `api.expand`, `api.visit`), and `src/App.tsx` (`openHole`, `selectNode`, `expandSelected`, `setGraph`, `expandFocus`).
5. **Graph construction**: `src/GraphCanvas.tsx`. `positionGraph` builds the children map, sorts siblings by `created_at`, assigns Y positions by leaf span, and emits React Flow nodes and edges. `Canvas` owns `collapsed`, `fitFocus`, `initialFitComplete`, and the fit revision logic. `ExplorerCanvas` wraps it in a provider.
6. **Interaction**: `onSelect`, `onExpand`, `onToggleCollapse`, `busyNodeId`, and the `ConceptCard` click and hover handlers, including event propagation from the card into the node.

## Procedure

1. **Reproduce.** Describe the exact trigger: which action, which node, which order of clicks, and whether the page was reloaded. If you cannot reproduce it, say what you tried and stop before guessing.
   - Prefer a deterministic reproduction: a backend test with a monkeypatched `ai` function (see `backend/tests/test_api.py`), or a minimal `GraphOut` fixture fed into `positionGraph` in a scratch script.
   - Do not modify `data/ronin.db`. If you need a database, point `RONIN_DATABASE_URL` at a throwaway copy in the scratchpad directory.
2. **Locate the first point where data goes wrong.** Check in this order and stop at the first failure:
   - AI output: does the generated concept list contain the expected titles and parent relationships?
   - Backend: does the row exist in `nodes` and `edges`, and does `_graph` return it with the correct `parent_id`, `source`, and `target`?
   - Frontend state: after `setGraph`, is the new graph in state, and does `Canvas` re-run `positionGraph`?
   - React Flow: do node IDs match edge `source`/`target` exactly? Are sizes measured (`useNodesInitialized` should be true) before layout and fit run?
3. **Check the usual suspects**, in the layout and interaction code:
   - Node IDs: string vs number, or stale IDs after a refetch, so an edge points to a node that is not in the array.
   - Orphans: a node whose `parent_id` is missing from the set, which `positionGraph` silently drops (it only starts from the single root).
   - Dimensions: fit or layout calculated before the card has rendered, so the bounding box is zero.
   - Collapse: `collapsed` hides children, but edges or fit may still reference them.
   - Async: a response for an earlier graph arriving after a new one, or `busyNodeId` not cleared on error.
   - Viewport: a fit revision applied twice or never, and the `initialFitComplete` gate.
   - Event propagation: a click on the card's action button also selecting the node, or the canvas pane swallowing the click.
4. **Make the smallest coherent fix** in the layer where the root cause lives. Do not patch the symptom in a later layer.
5. **Add a regression test when practical.** Backend: a case in `backend/tests/test_api.py` in the style of the existing tests. Frontend: there is no frontend test runner in this repo (no test script in `package.json`), so do not invent one. Instead, state that the fix is verified by reproduction and the type check, and say which case should be covered if a test runner is added later.
6. **Verify the original failure is gone**, not just that the build passes. Re-run the exact reproduction from step 1 and report the before and after. Use the `ronin-verify` checks, and browser verification for visual symptoms.

## Rules

- Never claim the root cause without evidence from a specific line, log, or response.
- Keep the diff focused. Do not refactor `positionGraph` or the canvas while fixing a bug.
- Do not commit or stage changes.
