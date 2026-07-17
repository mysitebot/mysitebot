# sam

A standalone, MIT-licensed agent that builds and edits [Astro](https://astro.build)
websites from natural-language prompts. Runs locally on nothing but an LLM API key —
no account, no limits.

## Quickstart

```bash
uv sync
export LLM_API_KEY="your-google-ai-studio-key"   # required; Gemini by default
uv run python cli.py --dir ./my-site --prompt "Create a landing page for a bakery"
```

`--dir` is your local Astro workspace; if it doesn't exist, sam scaffolds the
sealed template into it.

### Using another provider

sam talks to any OpenAI-compatible endpoint. The defaults target Gemini, so out
of the box `LLM_API_KEY` should be a [Google AI Studio](https://aistudio.google.com/)
key. For any other provider, also override the endpoint and models:

```bash
export LLM_BASE_URL="https://api.openai.com/v1"   # default: https://generativelanguage.googleapis.com/v1beta/openai/
export LLM_MODEL="gpt-4.1-mini"                   # default: gemini-2.5-flash-lite
export LLM_MODEL_THINKING="o4-mini"               # default: gemini-2.5-flash (used on retry/escalation)
```

## Image search (optional)

Set `WAGMI_KEY` to enable image search/generation via
[wagmi.photos](https://wagmi.photos) (OpenAI-compatible, semantically cached):

```bash
export WAGMI_KEY="your-wagmi-key"
```

Unset, sam simply leaves images alone.

## What's inside

- `src/agent/` — the editing engine, prompts, MDX validators, the `GitProvider`
  and `MediaSearch` interfaces, and the wagmi client.
- `templates/` — the sealed Astro template and its section library.
- `training/sam/` — the SAM evaluation loop and scenario corpus used to test and
  improve the agent's editing behavior.
- `cli.py` — the local entry point.

## Development

```bash
uv sync
uv run pytest        # unit + seam + SAM eval-loop tests
uv run ruff check src tests cli.py
```

## License

MIT — see `LICENSE`. Template provenance is documented in `NOTICE`.
