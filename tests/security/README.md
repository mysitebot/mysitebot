# MDX expression injection — red-team regression harness

This proves that MDX `{...}` expressions (attribute values, bare body
expressions, and `import`ed Node builtins) execute arbitrary JavaScript at
Astro build time, and that none of the three write-gate checks the agent
runs before committing content (`is_safe_content_path` →
`validate_content` → `check_content_for_cookies`, in the order used by
`SiteEditorAgent.branch_and_edit_content` in
`src/agent/site_editor.py`) inspect the *inside* of a brace
expression. A malicious or compromised model turn can read `process.env`
secrets into the public `dist/` output, read/write arbitrary files, or
shell out — all while passing today's gate.

`test_mdx_expression_injection.py` drives a table of payloads through a
local `_run_gate()` that replicates that exact call order (importing the
three real functions from `agent.content_safety` /
`agent.content_validator`, not a mock). The 7 injection payloads are
marked `xfail(strict=True)` — the gate currently accepts them, so the
suite stays green while documenting the hole. The 2 control payloads (a
legitimate braced Hero prop, and plain markdown with no braces) are
ordinary passing assertions and must never be blocked.

Wave 2 Task 3 implements the expression-grammar validator that closes this
hole. When a payload's assertion starts passing for real, `strict=True`
turns its xfail into a hard error — remove that payload's xfail marker
(the trailing `True` in its `PAYLOADS` tuple) to confirm the fix and keep
the suite green.

Run just this harness (from the sam repo root):

```
uv run pytest tests/security -q
```

Run the full agent suite (must include this harness, always green):

```
uv run pytest tests -q
```
