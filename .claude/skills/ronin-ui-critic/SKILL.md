---
name: ronin-ui-critic
description: Critique Ronin's frontend design and usability (typography, hierarchy, spacing, concept cards, React Flow graph composition, responsive layout, interaction feedback) before changing it. Use when the user asks for a UI/UX review, design feedback, visual polish, "does this look right", or before any substantial styling or layout change in src/. Do not use for pure logic bugs in the graph; use ronin-graph-debugger for those.
---

# Ronin UI Critic

Ronin is a premium editorial exploration tool, not a generic AI dashboard. Keep its existing visual identity: read `src/styles.css`, `tailwind.config.js`, and the components before proposing anything, and treat the existing typographic and color language as the baseline to refine rather than replace.

## Relevant code

- `src/App.tsx`: page states (start, archive, explorer, notes), selection, mobile nav and detail panels.
- `src/GraphCanvas.tsx`: `ConceptCard`, `CurvedEdge`, `positionGraph` (layout), `Canvas` (fit/focus/collapse), `ExplorerCanvas`.
- `src/views.tsx`: archive, notes, and other secondary views.
- `src/styles.css`: the design tokens and component styles.
- `index.html`: font loading and document metadata.

Read the relevant component before commenting on it. Do not critique from memory or from a screenshot you have not opened.

## Procedure

1. **Gather evidence.** Obtain screenshots from the running app. Use the `run` skill to start it if needed. The read-only showcase (`RONIN_READ_ONLY=1`, see README) lets you view trails without a Gemini key, and it does not write to the database. Capture at least desktop and phone widths.
2. **Check whether a browser tool exists in this session.** Look for a browser tool (for example Claude in Chrome or the built-in browser, when enabled). If none is available, say so plainly. You may still review the code, but the critique is then code-based and must be labelled that way. Never write "I looked at the screen" unless you actually did.
3. **Evaluate against these dimensions**, citing the file and selector or class for each finding:
   - typography: scale, weight contrast, line length, readability of titles and summaries
   - hierarchy: what a user sees first, and whether the question, selected concept, and actions are ordered correctly
   - spacing and rhythm: consistent gaps, padding inside cards, density of the side panels
   - card readability: truncation, overflow, contrast, and the visible state of selected, busy, and visited concepts
   - graph composition: node spacing, edge curvature, fit-to-view behavior, whether the trail reads left to right
   - responsive behavior: 16px gutters, no horizontal page scroll, mobile nav and detail panels
   - interaction feedback: hover, focus-visible, busy state during expansion, error messages
   - visual consistency: one accent system, one radius and shadow scale, no stray one-off values
4. **Rank the three highest-impact problems first.** Impact means effect on exploration and trust, not on decoration. Keep the list to three unless the user asks for more.
5. **Separate evidence from assumption.** Label each point as `Observed` (seen on screen or read in code with a line reference) or `Assumed` (inferred, with the reason). Do not present assumptions as facts.
6. **Propose measurable acceptance criteria before implementing.** Examples: "no text in a concept card is clipped at 375px width", "selected and busy states are distinguishable in grayscale", "the graph fits the viewport with all five first-layer branches visible at 1280×800". Get agreement on these before a substantial change.

## Rules

- Do not redesign toward generic dashboard patterns (stat tiles, sidebars of metrics, saturated gradients) unless the user asks for it.
- Keep recommendations small and reversible. Prefer token and class changes over new components.
- Do not modify application code during a critique. Implement only after the user accepts the criteria.
- Never read `.env`, and never print secrets.
