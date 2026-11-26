---
name: explain-the-diff
description: Explain the current or recent code changes in Ronin so the user understands and owns them. Covers changed files, root cause addressed, implementation, important code paths, architectural trade-offs, possible regressions, and what to learn; separates essential changes from optional improvements. Use when the user asks what a diff does, wants to review generated code, or says they do not understand a change.
---

# Explain the Diff

The goal is understanding, not a summary for its own sake. The user should be able to defend each change in review and explain it without the assistant.

## Gather the change

1. Run `git status` and `git diff` (or `git diff --staged` if the user has staged changes, or `git show <commit>` if they name one). Note the branch.
2. Read the full changed functions, not just the hunks. A hunk without its surrounding function often hides the real behaviour.
3. Open the tests that cover the changed code, if any. Note whether the change adds a test.

## Structure of the explanation

Use these headings, in this order. Skip a heading only if it truly does not apply, and say so.

1. **Changed files**: each file, with one line on its role. Name real paths, for example `backend/main.py` or `src/GraphCanvas.tsx`.
2. **Root cause being addressed**: the observed problem and the point in the data path where it originates (generation, validation, persistence, API, state, React Flow, or interaction). If the change is a feature rather than a fix, say so.
3. **Implementation**: what the change does, in the order a request would flow through it. Reference `file:line` for each important step.
4. **Important code paths**: the functions a reader should trace, and what data enters and leaves each one.
5. **Architectural trade-offs**: what was chosen and what was given up. For example, separate Gemini calls for generation and grounding (see README) trade one request for validated structure, and the option of a single call that is not available on Gemini 2.5.
6. **Potential regressions**: specific behaviours that could break, and which existing test or manual check (README "Manual check") covers each one. Say plainly when nothing covers it.
7. **Essential versus optional**: list what is required for the change to work separately from polish, refactors, or extra cleanups that came along with it. Recommend dropping the optional items if they are not needed.
8. **What to learn**: two to four concepts the user should understand from this change, each with a short explanation and a pointer to where it appears in the code.

## Style

- Explain jargon the first time it appears, such as "React Flow node ID", "Pydantic validation", or "monkeypatch".
- Do not hide complexity. If a part is subtle (async state ordering, layout timing, grounded-citation matching), say so and explain it.
- Keep it readable: short paragraphs, code references in backticks, no filler.
- If the change is larger than a reader can absorb at once, offer to walk through it one file at a time.

## Rules

- Do not modify code while explaining. If you find a defect, report it under Potential regressions and offer to fix it separately.
- Base every claim on code you have read. If you have not verified a claim, label it as such.
- Do not commit, stage, or stash anything.
