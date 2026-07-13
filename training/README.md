# SAM — the site-editing eval loop

This directory holds **SAM**, the evaluation harness that tests and improves
`sam`'s editing behavior against a corpus of scenarios.

## Structure

- `sam/` — the eval loop: scenario runner, a judge panel, an optional
  self-modifying fixer, and the scenario corpus (`sam/scenarios/`).
- `claude_driver.py` — a small, stdlib-only helper for driving the `claude` CLI
  as a subprocess (shared harness).

## Running

```bash
uv sync --group dev
uv run pytest training/sam/tests        # offline unit tests for the harness
```

The live eval loop drives the agent against each scenario and grades the result.
See `sam/` for the runner entry points and scenario format. A live run needs an
LLM API key (`LLM_API_KEY`, OpenAI-compatible) and, for browser verification,
Playwright browsers (`uv run playwright install chromium`).
