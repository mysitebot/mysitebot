"""
Red-team regression harness: MDX `{...}` expressions execute arbitrary
JavaScript at Astro build time. Any content file the agent writes into
`content/` can smuggle a brace expression that reads process.env secrets,
reads/writes the filesystem, or shells out — and none of that is caught by
the current write-gate.

This module drives each payload through the REAL gate, in the REAL order,
by importing the three gate functions directly from their production
modules and replicating the call sequence in `site_editor.py` (see
`branch_and_edit_content`, roughly lines 290-306):

    1. is_safe_content_path(file_path)      -- agent.content_safety
    2. validate_content(file_path, content) -- agent.content_validator
    3. check_content_for_cookies(content, file_path) -- agent.content_safety

`_run_gate` below is a small local re-implementation of that sequence
(not a call into site_editor itself, which also needs a live git provider)
returning the first error dict encountered, or None if every check passes.

Status (Wave 2 Task 3): CLOSED. `content_validator.py` now hosts an
allowlist literal-expression grammar (`_is_literal_expression` +
`_expression_values` / `_bare_body_expressions`) that `validate_content`
applies to every component attribute `{...}` value and every bare-body
`{...}` in page content, plus a leading import/export rejection. All 7
injection payloads below are now BLOCKED (their former
`xfail(strict=True)` markers are removed — that was the proof-of-fix
signal: once the grammar landed, those cases XPASS-errored under
strict=True until the markers were deleted here). The 2 control payloads
(a legitimate braced prop and plain markdown with no braces at all) are
ordinary assertions that must never be blocked, now or ever.

Status (fix round 1, post-Task-3 adversarial review): a CRITICAL bypass one
layer below the grammar was found and closed. `_strip_code_spans` — the
pre-pass that removes fenced code/inline code so documentation examples
aren't scanned as live JSX — used a regex backreference that treated a
length-MISMATCHED later backtick run as a valid "closer" (e.g. a 3-backtick
opener "closed" by the first 3 backticks of a later 4-backtick run). Real
CommonMark/MDX never neutralizes that shape (only an EXACT-length run
closes an inline code span), so the old regex was stripping — and hence
hiding from the grammar — text MDX executes live: a confirmed build-time
RCE (verified against the real @mdx-js/mdx compiler). `_strip_code_spans`
was rewritten as a small hand-rolled CommonMark-accurate scanner (see
`fence_bypass_env_read` / `fence_bypass_command_exec` below); the grammar
itself needed no changes.

Status (fix round 2, second adversarial review): TWO MORE confirmed-live
bypasses were found in `_strip_code_spans`, and this time the fix removes
the security guarantee's dependence on that stripper entirely rather than
patching another hole in it. (1) CRLF/CR: splitting the body on a bare LF
left a trailing CR character on a closing-fence line, which never matches
the closer regex, so the fence was wrongly classified as unclosed and
"swallowed to EOF" — hiding a live expression (or a live `import`) that
appeared AFTER the real close. (2) Backslash-escaped backticks: the
stripper treated an escaped backtick as a real delimiter, so a
backslash-escaped backtick pair around a live `{...}` expression was
(wrongly) stripped as an inert code span, though MDX executes the `{...}`
(the backslash escapes the backtick, not the expression). Both confirmed
executing live against the real @mdx-js/mdx compiler (see the
`crlf_bypass_env_read` / `crlf_bypass_import_exec` /
`escaped_backtick_bypass_env_read` payloads below).

Round 2's actual fix: the literal-expression scan (and the import/export
check) no longer reads `_strip_code_spans`'s output (`scan_body`) AT ALL —
both now scan the raw body (with line endings normalized) directly, so a
non-literal `{...}` or an `import`/`export` line is rejected wherever it
textually appears in the file, fenced or not. This is fail-closed by
construction: no future stripper bug can ever hide a live expression from
these two checks again, because they no longer depend on the stripper's
fence/code-span boundary detection being correct at all. (The stripper
itself was ALSO hardened — CRLF/CR normalization and backslash-escape
awareness — but only for defense-in-depth on the component-NAME/PROP scans,
which are not a security boundary.) See `test_mdx_fuzz_invariant` below,
which fuzzes hundreds of randomized fence/code-span shapes against the
REAL @mdx-js/mdx compiler and asserts the invariant: MDX executes a body's
sentinel expression ⟹ `validate_content` rejects it.
"""
from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agent.content_safety import check_content_for_cookies, is_safe_content_path
from agent.content_validator import validate_content
from agent.templates import template_path


def _run_gate(file_path: str, content: str) -> Optional[Dict[str, Any]]:
    """
    Replicates the write-gate call order from
    `SiteEditorAgent.branch_and_edit_content` (site_editor.py ~L290-306):
    path check -> content validation -> cookie check. Returns the first
    error dict raised by any stage, or None if the content is accepted.
    """
    if not is_safe_content_path(file_path):
        return {"error": "Access denied: can only edit content/ directory."}

    validation_error = validate_content(file_path, content)
    if validation_error:
        return validation_error

    cookie_error = check_content_for_cookies(content, file_path)
    if cookie_error:
        return {
            "error": (
                "Privacy Constraint Violated: The platform is strict "
                "'Privacy First' and cookie-free. Generated file content "
                f"contains forbidden cookie-accessing code/references. Details: {cookie_error}"
            )
        }

    return None


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------
# Every payload is a *complete* content/pages file (valid frontmatter with a
# title, so it clears the earlier structural checks) that isolates exactly
# one injection technique in the body. This proves the hole is in the MDX
# expression itself, not in some unrelated frontmatter/section defect.

_FRONTMATTER = '---\ntitle: "Home"\ndescription: "Landing page"\n---\n\n'

MDX_ATTR_ENV_READ = (
    _FRONTMATTER
    + '<Hero heading={process.env.SECRET} subheading="Welcome" />\n'
)

MDX_BARE_BODY_ENV_READ = (
    _FRONTMATTER
    + "Welcome to our site. {process.env.SECRET}\n"
)

MDX_GLOBALTHIS_ENV_READ = (
    _FRONTMATTER
    + "{globalThis.process.env.SECRET}\n"
)

MDX_FUNCTION_CTOR = (
    _FRONTMATTER
    + '{Function("return process.env.SECRET")()}\n'
)

MDX_FILE_READ = (
    _FRONTMATTER
    + 'import { readFileSync } from "node:fs";\n\n'
    + '{readFileSync("/etc/passwd", "utf8")}\n'
)

MDX_COMMAND_EXEC = (
    _FRONTMATTER
    + 'import { execSync } from "node:child_process";\n\n'
    + '{execSync("id")}\n'
)

MDX_IIFE_SIDE_EFFECT = (
    _FRONTMATTER
    + '{(() => { globalThis.x = 1; return "" })()}\n'
)

# --- Fence-stripping bypass (fix round 1) -----------------------------------
#
# `_strip_code_spans` used a regex backreference (`(\`{3,}|~{3,}).*?\1`) that
# matched ANY later occurrence of the same N-backtick substring as a
# "closer" -- including one found INSIDE a longer backtick run (e.g. a
# 3-backtick opener "closed" by the first 3 of a later 4-backtick run).
# Confirmed against the real @mdx-js/mdx compiler: a length-mismatched
# backtick delimiter forms NO code span at all in real MDX/CommonMark (the
# backticks stay literal), so the `{...}` between them is LIVE JavaScript --
# yet the old regex stripped it from `scan_body`, meaning it was never
# scanned by the expression grammar. Confirmed full command-exec bypass.
MDX_FENCE_BYPASS_ENV_READ = (
    _FRONTMATTER
    + "prose ```{process.env.SECRET}```` more\n"
)

MDX_FENCE_BYPASS_COMMAND_EXEC = (
    _FRONTMATTER
    + "prose ```{require('child_process').execSync('id')}```` more\n"
)

# --- CRLF-fence bypass (fix round 2) -----------------------------------------
#
# `_strip_code_spans` used `body.split("\n")`; a CRLF closing-fence line
# ("```\r\n") keeps a trailing "\r" that never matches the closer regex
# (only trailing spaces/tabs are allowed there), so the fence was wrongly
# classified as unclosed and "swallowed to EOF" -- hiding whatever came
# after the real close (a live `{...}` expression, or a live `import` line)
# from every scan that read `scan_body`. Confirmed executing against the
# real @mdx-js/mdx compiler.
MDX_CRLF_BYPASS_ENV_READ = (
    _FRONTMATTER.replace("\n", "\r\n")
    + "```\r\nsafe placeholder\r\n```\r\n{process.env.SECRET}\r\n"
)

MDX_CRLF_BYPASS_IMPORT_EXEC = (
    _FRONTMATTER.replace("\n", "\r\n")
    + "```\r\nsafe placeholder\r\n```\r\n"
    + 'import { execSync } from "node:child_process";\r\n\r\n'
    + "{execSync('id')}\r\n"
)

# --- Backslash-escaped-backtick bypass (fix round 2) -------------------------
#
# `_strip_inline_code_spans` treated `` \` `` as a real delimiter; a
# backslash-escaped backtick is never a code-span delimiter in real MDX (the
# backslash escapes just that one character), so `` a \`{x}\` b `` forms NO
# code span at all and `{x}` is live body text -- yet the old stripper
# treated the two escaped backticks as a real (inert) span, hiding a live
# expression between them. Confirmed executing against the real
# @mdx-js/mdx compiler.
MDX_ESCAPED_BACKTICK_BYPASS_ENV_READ = (
    _FRONTMATTER
    + "a \\`{process.env.SECRET}\\` b\n"
)

# Controls: must never be blocked, before or after Task 3.
MDX_LEGIT_HERO_ACTIONS = (
    _FRONTMATTER
    + '<Hero heading="Welcome" actions={[{ label: "Go", href: "/x", variant: "primary" }]} />\n'
)

MD_PLAIN_NO_BRACES = (
    '---\ntitle: "About Us"\ndescription: "A plain page"\n---\n\n'
    "# About Us\n\n"
    "This is a plain paragraph with no braces or components at all.\n"
)

# (name, file_path, mdx, must_be_blocked)
#
# All injection payloads (the original 7, the 2 fence-bypass payloads from
# fix round 1, and the 3 CRLF/backslash-escape bypass payloads from fix
# round 2) are blocked; the 2 controls must never be blocked, now or ever.
# (Previously the injection rows carried `xfail(strict=True)` markers
# documenting that the gate did not yet block them — Task 3 turned those
# into XPASS errors, which is exactly the signal to delete the markers,
# done here.)
PAYLOADS: list[tuple[str, str, str, bool]] = [
    ("attr_env_read", "content/pages/index.mdx", MDX_ATTR_ENV_READ, True),
    ("bare_body_env_read", "content/pages/index.mdx", MDX_BARE_BODY_ENV_READ, True),
    ("globalthis_env_read", "content/pages/index.mdx", MDX_GLOBALTHIS_ENV_READ, True),
    ("function_ctor", "content/pages/index.mdx", MDX_FUNCTION_CTOR, True),
    ("file_read", "content/pages/index.mdx", MDX_FILE_READ, True),
    ("command_exec", "content/pages/index.mdx", MDX_COMMAND_EXEC, True),
    ("iife_side_effect", "content/pages/index.mdx", MDX_IIFE_SIDE_EFFECT, True),
    ("fence_bypass_env_read", "content/pages/index.mdx", MDX_FENCE_BYPASS_ENV_READ, True),
    ("fence_bypass_command_exec", "content/pages/index.mdx", MDX_FENCE_BYPASS_COMMAND_EXEC, True),
    ("crlf_bypass_env_read", "content/pages/index.mdx", MDX_CRLF_BYPASS_ENV_READ, True),
    ("crlf_bypass_import_exec", "content/pages/index.mdx", MDX_CRLF_BYPASS_IMPORT_EXEC, True),
    ("escaped_backtick_bypass_env_read", "content/pages/index.mdx", MDX_ESCAPED_BACKTICK_BYPASS_ENV_READ, True),
    ("legit_hero_actions", "content/pages/index.mdx", MDX_LEGIT_HERO_ACTIONS, False),
    ("plain_markdown_no_braces", "content/pages/about.md", MD_PLAIN_NO_BRACES, False),
]


def _pytest_params():
    for name, file_path, mdx, must_be_blocked in PAYLOADS:
        yield pytest.param(name, file_path, mdx, must_be_blocked, id=name)


@pytest.mark.parametrize("name, file_path, mdx, must_be_blocked", list(_pytest_params()))
def test_payload_gate(name: str, file_path: str, mdx: str, must_be_blocked: bool) -> None:
    result = _run_gate(file_path, mdx)
    blocked = result is not None
    assert must_be_blocked == blocked, (
        f"{name}: expected must_be_blocked={must_be_blocked} but the gate "
        f"{'blocked' if blocked else 'accepted'} it (result={result!r})"
    )


# =============================================================================
# Fuzz harness (fix round 2): prove the fail-closed invariant against the
# REAL @mdx-js/mdx compiler, not just the hand-picked bypass payloads above.
#
# The literal-expression security check no longer depends on `_strip_code_
# spans` correctly identifying fence/code-span boundaries (see the round-2
# module docstring above) — it scans the raw, line-ending-normalized body
# directly. That means the specific SHAPE of a fence/code-span bypass no
# longer matters for security. This harness still exists to prove it: it
# generates many randomized fence/code-span/line-ending combinations, each
# embedding an EXECUTION-OBSERVABLE sentinel expression
# (`globalThis.__c = (globalThis.__c || 0) + 1`), and for each body checks
# two independent facts:
#   1. Does the REAL @mdx-js/mdx compiler execute the sentinel? (compiled
#      and run via `evaluateSync` with a minimal no-op JSX runtime, checking
#      whether the sentinel global was actually mutated — not string
#      matching on compiler output.)
#   2. Does `validate_content` reject the body?
# INVARIANT: (1) implies (2). It is fine (expected, even) for (2) to be True
# when (1) is False — fail-closed over-rejection of an inert code sample is
# the accepted trade-off, never the reverse.
# =============================================================================

_MDX_ENTRY = Path(template_path("astro-basic", "node_modules", "@mdx-js", "mdx", "index.js"))
_NODE_BIN = shutil.which("node")

# The bare inner expression (no enclosing braces) and the same thing already
# wrapped as a standalone top-level `{...}` — the former is what the tag
# generators below splice into an attribute/children position (which supplies
# its own braces), the latter is what the fence/inline generators embed
# directly as prose (unchanged from before this round).
_SENTINEL_EXPR = "globalThis.__c=(globalThis.__c||0)+1"
_SENTINEL = "{" + _SENTINEL_EXPR + "}"
_FUZZ_FRONTMATTER = '---\ntitle: "x"\ndescription: "y"\n---\n\n'
_EOLS = ["\n", "\r\n", "\r"]

# Batch runner: reads a JSON array of MDX body strings, evaluates each with
# the real compiler, and writes a JSON array of {"executed": bool, "error":
# str|None} results. Run as ONE node process for the whole batch (a few
# hundred bodies) instead of one process per body, for speed.
_NODE_BATCH_SCRIPT = """
import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const mdxEntry = process.argv[2];
const inputFile = process.argv[3];
const outputFile = process.argv[4];

const { evaluateSync } = await import(pathToFileURL(mdxEntry).href);

function jsx(type, props) { return { type, props }; }
const runtime = { Fragment: Symbol("Fragment"), jsx, jsxs: jsx, jsxDEV: jsx };

const bodies = JSON.parse(readFileSync(inputFile, "utf8"));
const results = [];

for (const body of bodies) {
  globalThis.__c = 0;
  let executed = false;
  let error = null;
  // MDX inserts a runtime guard that throws "Expected component `X` to be
  // defined" for any capitalized tag not present in `props.components` --
  // BEFORE the tag's own prop-expression object literal is even
  // constructed -- which would make every <Hero .../> sample look like it
  // never executes its attribute expression at all (a false negative, not
  // a real "this is inert" result). MDX reads `props.components` via an
  // object SPREAD (`{...props.components}`), which only copies a Proxy's
  // own keys if it implements `ownKeys`/`getOwnPropertyDescriptor` -- far
  // simpler to just scan the body's own text for the capitalized tag
  // name(s) it actually uses and hand back a concrete plain object with a
  // harmless stub for each, so prop/spread expressions are actually
  // evaluated: the real build-time behavior for a page that does provide
  // the section components.
  const components = {};
  for (const m of body.matchAll(/<([A-Z][A-Za-z0-9]*)/g)) {
    components[m[1]] = (props) => ({ type: m[1], props });
  }
  try {
    const mod = evaluateSync(body, runtime);
    try {
      mod.default({ components });
    } catch (runErr) {
      error = "run:" + String((runErr && runErr.message) || runErr);
    }
    executed = globalThis.__c > 0;
  } catch (compileErr) {
    error = "compile:" + String((compileErr && compileErr.message) || compileErr);
    executed = globalThis.__c > 0;
  }
  results.push({ executed, error });
}

writeFileSync(outputFile, JSON.stringify(results));
"""


def _fence_body(rng: random.Random) -> str:
    """One randomized fenced-code-block construct: varies fence char
    (`` ` `` / `~`), opener/closer length (3-5, matched or mismatched),
    indentation (0-3 valid, 4+ over-indented), presence of a closer at all,
    blank-line boundaries, and line-ending style — with the sentinel placed
    either just after the construct (the exact shape of the reported
    bypasses) or inside it (exercises the "should be inert" direction)."""
    indent = rng.choice([0, 1, 2, 3, 4, 5])
    fence_char = rng.choice(["`", "~"])
    opener_len = rng.choice([3, 4, 5])
    has_closer = rng.choice([True, False])
    closer_len = rng.choice([3, 4, 5])
    closer_indent = rng.choice([0, 1, 2, 3])
    eol = rng.choice(_EOLS)
    blank_before = rng.choice([True, False])
    blank_after = rng.choice([True, False])
    sentinel_inside = rng.choice([True, False])
    info_has_backtick = rng.choice([True, False]) if fence_char == "`" else False

    lines = ["Intro prose before."]
    if blank_before:
        lines.append("")
    info = " `oops`" if info_has_backtick else ""
    lines.append((" " * indent) + (fence_char * opener_len) + info)
    lines.append(_SENTINEL if sentinel_inside else "safe filler text")
    if has_closer:
        lines.append((" " * closer_indent) + (fence_char * closer_len))
        if blank_after:
            lines.append("")
    lines.append("more prose after." if sentinel_inside else f"{_SENTINEL} more prose after.")
    body_lf = "\n".join(lines) + "\n"
    return body_lf.replace("\n", eol)


def _inline_body(rng: random.Random) -> str:
    """One randomized inline-code-span construct: backtick run length 1-3
    on each side (matched or mismatched), independent backslash-escape
    parity on each delimiter (0-3 backslashes), an optional embedded line
    ending inside the span (paragraph-scoped multiline span), and line-
    ending style — sentinel always follows the construct."""
    open_len = rng.choice([1, 2, 3])
    close_len = rng.choice([1, 2, 3])
    open_bs = rng.choice([0, 1, 2, 3])
    close_bs = rng.choice([0, 1, 2, 3])
    eol = rng.choice(_EOLS)
    embed_eol = rng.choice([True, False])

    open_delim = ("\\" * open_bs) + ("`" * open_len)
    close_delim = ("\\" * close_bs) + ("`" * close_len)
    inner = "safe\nfiller" if embed_eol else "safe filler"
    span_text = f"pre {open_delim}{inner}{close_delim} post {_SENTINEL} end"
    body_lf = "Intro.\n\n" + span_text + "\n"
    return body_lf.replace("\n", eol)


# --- Tag-bearing bodies (hardening round 3) ---------------------------------
#
# The fence/inline generators above only ever embed the sentinel as a bare
# top-level `{...}` around fence/code-span constructs: `re.search(r'<[A-Za-z]',
# body)` matched 0 of the 380 bodies they produced. That means the fuzz's
# 0-counterexample invariant proof never covered the tag-attribute surface
# `_tag_header`/`_expression_values` parse (component-tag attributes,
# lowercase-tag attributes/children, fragments, attribute spreads) — the final
# adversarial review had to test that surface by hand instead. These five
# forms put the execution-observable sentinel expression inside exactly that
# surface, each as a single top-level `{...}` group (or, for the spread form,
# inside one):
#   - a component-tag attribute:      <Hero heading={expr} ... />
#   - a lowercase-tag attribute:      <span x={expr}>...</span>
#   - lowercase-tag children:         <div>{expr}</div>
#   - a fragment:                     <>{expr}</>
#   - an attribute spread:            <Hero {...{a: expr}} />
def _tag_forms(expr: str) -> List[str]:
    return [
        "<Hero heading={" + expr + '} subheading="Welcome" />',
        "<span x={" + expr + "}>content</span>",
        "<div>{" + expr + "}</div>",
        "<>{" + expr + "}</>",
        "<Hero {...{a: " + expr + "}} />",
    ]


def _tag_body(rng: random.Random) -> str:
    """One randomized tag-bearing construct (see `_tag_forms`), combined —
    where sensible — with the same line-ending axis the fence/inline
    generators use, and sometimes nested inside a fenced code block. The
    RCE-critical scans (`raw_tag_spans`/`_expression_values` for capitalized
    tags, `_bare_body_expressions` for everything else) run over the raw,
    un-stripped body by design (see `validate_content`'s round-2 docstring),
    so a fence is not expected to make any of these constructs inert —
    fencing is exercised here anyway, to prove that invariant rather than
    merely assume it."""
    form = rng.choice(_tag_forms(_SENTINEL_EXPR))
    eol = rng.choice(_EOLS)
    wrap_in_fence = rng.choice([True, False])
    if wrap_in_fence:
        lines = ["Intro prose before.", "```", form, "```", "more prose after."]
    else:
        lines = ["Intro prose before.", form, "more prose after."]
    body_lf = "\n".join(lines) + "\n"
    return body_lf.replace("\n", eol)


def _generate_fuzz_bodies(seed: int, n_fence: int, n_inline: int, n_tag: int = 0) -> List[str]:
    rng = random.Random(seed)
    bodies = [_fence_body(rng) for _ in range(n_fence)]
    bodies += [_inline_body(rng) for _ in range(n_inline)]
    bodies += [_tag_body(rng) for _ in range(n_tag)]
    return bodies


def _run_node_batch(bodies: List[str]) -> List[Dict[str, Any]]:
    tmpdir = tempfile.mkdtemp(prefix="mdx_fuzz_")
    try:
        script_path = Path(tmpdir) / "batch_check.mjs"
        input_path = Path(tmpdir) / "bodies.json"
        output_path = Path(tmpdir) / "results.json"
        script_path.write_text(_NODE_BATCH_SCRIPT, encoding="utf-8")
        input_path.write_text(json.dumps(bodies), encoding="utf-8")
        subprocess.run(
            [_NODE_BIN, str(script_path), str(_MDX_ENTRY), str(input_path), str(output_path)],
            check=True,
            capture_output=True,
            timeout=120,
            text=True,
        )
        return json.loads(output_path.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.skipif(
    _NODE_BIN is None or not _MDX_ENTRY.exists(),
    reason="node or the real @mdx-js/mdx package is not available; skipping compiler-backed fuzz",
)
def test_mdx_fuzz_invariant() -> None:
    bodies = _generate_fuzz_bodies(seed=20260707, n_fence=200, n_inline=180, n_tag=150)

    # A body "has a tag" if it contains a capitalized/lowercase JSX tag or a
    # fragment opener — the exact shape the round-2 fuzz never produced at
    # all (0/380 matched `<[A-Za-z]`).
    tag_bearing_count = sum(1 for b in bodies if re.search(r"<[A-Za-z]", b) or "<>" in b)

    results = _run_node_batch(bodies)
    assert len(results) == len(bodies)

    counterexamples: List[Tuple[int, str, Dict[str, Any]]] = []
    executed_count = 0
    rejected_count = 0
    tag_bearing_executed_count = 0
    for i, (body, result) in enumerate(zip(bodies, results)):
        executed = bool(result["executed"])
        is_tag_bearing = bool(re.search(r"<[A-Za-z]", body)) or "<>" in body
        if executed:
            executed_count += 1
            if is_tag_bearing:
                tag_bearing_executed_count += 1
        content = _FUZZ_FRONTMATTER + body
        rejected = validate_content("content/pages/index.mdx", content) is not None
        if rejected:
            rejected_count += 1
        if executed and not rejected:
            counterexamples.append((i, body, result))

    print(
        f"\n[mdx fuzz] samples={len(bodies)} tag_bearing={tag_bearing_count} "
        f"({100 * tag_bearing_count / len(bodies):.0f}%) executed={executed_count} "
        f"tag_bearing_executed={tag_bearing_executed_count} "
        f"rejected={rejected_count} counterexamples={len(counterexamples)}"
    )

    assert not counterexamples, (
        f"MDX-executes-but-validate_content-accepts counterexample(s) found "
        f"({len(counterexamples)} of {len(bodies)}); first: index="
        f"{counterexamples[0][0]} body={counterexamples[0][1]!r} "
        f"node_result={counterexamples[0][2]!r}"
    )
    # Sanity: the harness must actually be exercising both directions (some
    # bodies execute, some don't; validate_content is fail-closed so it
    # rejects at least every executing one), AND now actually generates
    # tag-bearing bodies (the gap this round closes).
    assert executed_count > 0, "fuzz generator produced no executing bodies — harness is not exercising anything"
    assert rejected_count >= executed_count
    assert tag_bearing_count > 0, "fuzz generator produced no tag-bearing bodies — the tag-attribute surface is unexercised"
