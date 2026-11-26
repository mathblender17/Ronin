---
name: ronin-verify
description: Run the real verification checks for Ronin (backend pytest, frontend type-check, production build, browser check for UI changes) and report results honestly as Passed, Failed, Not Run, and Browser Verification. Use after any code change, before saying work is done, or when the user asks to verify, test, check, or build the project.
---

# Ronin Verify

Run the checks, then report what actually ran. Never list an unexecuted check as passing.

## Checks available in this repository

Confirmed in `README.md`, `package.json`, and `backend/tests/`:

| Area | Command | Notes |
|---|---|---|
| Backend tests | `.\.venv\Scripts\python.exe -m pytest` (from the project root) | Uses `backend/tests/test_api.py`. Requires the venv from the README. |
| Frontend type-check | `pnpm exec tsc --noEmit -p tsconfig.json` | Same check `pnpm build` runs first. |
| Production build | `pnpm build` | Runs the type-check, then `vite build`. |
| Lint | none configured | No ESLint config or lint script exists. Report as Not Run. |
| Frontend tests | none configured | No test runner or test script. Report as Not Run. |

If the `.venv` is missing, do not install dependencies without asking. Report backend tests as Not Run and say why.

## Mocked versus live AI

- Every backend test currently monkeypatches `backend.ai` (`generate_initial`, `generate_expansion`, `_structured`, `_grounded_sources`, `_client`). These tests prove our parsing, validation, persistence, and error handling. They do not prove that Gemini returns usable output or real citations.
- There are no live-provider tests in the repository. Before claiming that AI or source behavior is verified, grep `backend/tests` for `GEMINI_API_KEY` or real `genai` calls to confirm this has not changed.
- A genuine live check requires a real `GEMINI_API_KEY` in the environment and a manual or scripted request to the running API. Only run one if the user asks, because it spends quota and sends the question to the external service. Report it separately, labelled "live", and state the model used (`GEMINI_MODEL`, default `gemini-2.5-flash`).
- Never print or log the key, and never read `.env` to get it.

## Procedure

1. **Identify what changed.** Use `git status` and `git diff --stat`. Pick the checks that cover the changed areas. Backend changes need pytest. Any `src/` change needs the type-check and build. Visual or layout changes need browser verification.
2. **Run the checks** in this order, and do not skip one because an earlier one passed:
   - backend pytest
   - frontend type-check
   - `pnpm build`
3. **Browser verification (UI changes only).** Check whether a browser tool is available in this session (Claude in Chrome or the built-in browser, if enabled). If one is, start the app with the `run` skill or with `pnpm dev` and `uvicorn backend.main:app --port 8000`, open the page, and exercise the changed behaviour. For a read-only check without a Gemini key, use the showcase (`RONIN_READ_ONLY=1` with `RONIN_DATABASE_URL` pointing to a copy of `showcase/ronin.db`). Do not write to the showcase database. If no browser tool is available, write "Browser Verification: Not Run, no browser tool available in this session" and do not describe any screen as seen.
4. **Report** using exactly these four headings:

```
## Passed
- <check>: <command>, <summary line from the output>

## Failed
- <check>: <command>, <the failing test name or error, verbatim>

## Not Run
- <check>: <reason>

## Browser Verification
- <what was opened, at what width, what was observed>, or "Not Run: <reason>"
```

Include the actual failure text for anything in Failed. If a check was skipped or did not run, say so in Not Run, with the reason.

## Rules

- Do not commit, deploy, push, or change unrelated files to make a check pass. If a check fails, report it and fix only the cause if that is in scope.
- Do not weaken or delete tests to get a green result.
- If the user asks for verification without a code change, run the same checks anyway.
