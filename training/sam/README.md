# Sam training loop

Runs Sam (the site-editing agent) against editing scenarios, verifies each
result (file checks → astro build → playwright DOM/screenshot → claude
judge), and on failure asks the headless claude CLI to diagnose and fix
Sam's prompt, tool descriptions, template, or validator — then re-verifies.
Design doc: ../../../docs/superpowers/specs/2026-06-11-sam-training-loop-design.md
(repo top level).

Nothing is ever committed by the loop; review `git diff` after a run.

## Prerequisites

- `LLM_API_KEY` exported (a Gemini key) — the model Sam (the agent under test)
  runs under, via the OSS LLMClient. Sam stays on Gemini because that is what
  production runs; override the model per run with `--model` (default
  `gemini-2.5-flash`, the corpus baseline). A dead/expired key shows up as
  consecutive `error` outcomes and the run aborts after 3.
- `claude` CLI on PATH (`claude --version`) — the *meta* model that judges runs,
  generates scenarios, and (with `--fix`) edits Sam's prompt/template/validator.
  Defaults to `claude-sonnet-5` (calibrated 2026-07-03, see calibration/); override via the `model=` arg in `claude_cli`.
- node/npm (the astro template's node_modules must exist:
  `cd templates/astro-basic && npm install` once)
- playwright chromium (`python -m playwright install chromium` once)

## Usage (always from the sam repo root)

    # pure eval, no self-modification (the default)
    python training/sam/run_loop.py

    # opt in to the self-modifying fixer (proposes edits for review, never commits)
    python training/sam/run_loop.py --scenarios contact_email_001 --fix

    # bound a big fixing run
    python training/sam/run_loop.py --fix --limit 10 --fix-budget 3

    # grow the corpus
    python training/sam/generate_scenarios.py --count 5

    # offline tests for the harness itself (from the sam repo root)
    pytest training/sam/tests -v

## How a run is judged

1. deterministic — tools called, files changed, text present, validator ok
   (negative scenarios: nothing changed, no editing tools)
2. build — `npm run build` in the throwaway workspace
3. playwright — DOM assertions + full-page screenshots of `dist/`
4. judge — `claude -p --permission-mode plan` reads the evidence and returns
   a JSON verdict ("does it make sense", only when layers 1–3 pass)

`fail` means Sam did the wrong thing; `error` means the harness/infra broke.
Only `fail` triggers the fixer.

## What the fixer may touch

src/agent/prompts.py, tool docstrings in src/agent/site_editor.py,
src/agent/content_validator.py, templates/astro-basic/**, templates/SECTIONS.md,
training/sam/registry.json. Anything else is auto-reverted and flagged in the
run report. A failed fix is fully reverted and the scenario is flagged
`needs_human` in registry.json.

Do not edit the repository while a fix-enabled run is active: the fixer
guard attributes changes by diffing dirty files before/after each fixer
call, so concurrent edits can be misattributed and auto-reverted. Reverted
content is never destroyed — it is quarantined under
runs/<ts>/<scenario>/rejected/ (and rejected_fix/ for reverted fixes).

## Outputs

- runs/<timestamp>/results.json + report.md — machine + human summary
- runs/<timestamp>/<scenario>/ — diff.patch, response.txt, tool_calls.json,
  verification.json, build.log, screenshots, judge.json, fix_report.md
- registry.json — per-scenario pass history, fixes, flaky/needs-human flags
