You are improving "Sam", the Gemini-powered website-editing agent in this
repository (see src/agent/). Sam just FAILED a training scenario.

FAILED SCENARIO:
id: {{scenario_id}}
user request: {{user_request}}

FAILURE EVIDENCE — read these files first:

- {{run_dir}}/scenario.json — the scenario definition and its checks
- {{run_dir}}/response.txt — Sam's reply to the user
- {{run_dir}}/error.txt — the error Sam raised instead of replying (only
  present when Sam crashed)
- {{run_dir}}/tool_calls.json — the tools Sam called, in order
- {{run_dir}}/diff.patch — what Sam changed in the site workspace
- {{run_dir}}/verification.json — which checks failed and why
- {{run_dir}}/build.log — Astro build output (if a build ran)

SUMMARY OF FAILED CHECKS:
{{failure_summary}}

YOUR TASK:

1. Diagnose the root cause. Typical causes: Sam misunderstood the request,
   called the wrong tool, produced invalid content, lacked a section
   component or property, or valid output was wrongly rejected by validation.
2. Apply the SMALLEST fix that addresses the root cause. You may ONLY modify:
   - src/agent/prompts.py (system prompt wording)
   - src/agent/site_editor.py (tool docstrings and parameter descriptions only)
   - src/agent/content_validator.py (validation rules)
   - templates/astro-basic/ plus
     templates/SECTIONS.md and
     training/sam/registry.json (section components, props, docs)
   Changes to any other file will be automatically reverted.
3. The fix must GENERALIZE. Do not hard-code this scenario's specific
   wording, titles, or content anywhere.
4. Do NOT run ANY git command (no add, no commit, no checkout, no restore,
   no stash) — the harness manages all git state. Do NOT create new
   top-level files.
5. Write {{run_dir}}/fix_report.md describing the root cause and your fix
   in a few sentences.
