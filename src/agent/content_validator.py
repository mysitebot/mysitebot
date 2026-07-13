import json
import os
import re
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional

from agent.templates import template_path
from agent.mdx_scan import js_aware_brace_end as _js_aware_brace_end

# Content files the agent may create or edit inside content/
ALLOWED_EXTENSIONS = {".md", ".mdx", ".yaml", ".yml"}

# Maximum length (characters) of a single content file the agent may write. Bounds both
# storage growth and the prompt/tool-result token cost of re-reading large files.
# MUST stay <= site_editor's READ_TRUNCATION_LIMIT (which shares this constant):
# a file bigger than the read threshold gets truncated on read and then
# permanently refuses full rewrites, so anything writable must stay fully
# readable. The largest legitimate content file (corpus + templates) is ~1.7k
# chars, so 20k is still generous headroom.
MAX_CONTENT_LENGTH = 20_000

# Raw-HTML XSS vectors that must never reach the rendered site. Content is
# markdown/MDX (prose + capitalized section components); none of these belong in
# it. MDX renders raw lowercase HTML verbatim (and parses it as JSX, so a
# render-time rehype sanitizer would miss it), so we reject at edit time.
_UNSAFE_HTML_PATTERNS = [
    # Inline event handlers: <img ... onerror="...">, <svg onload=...>, etc.
    # Case-insensitive; value may be quoted or a { } expression.
    (re.compile(r"\bon[a-z]+\s*=\s*[\"'{]", re.IGNORECASE), "an inline event handler (on...=)"),
    # Dangerous element tags.
    (re.compile(r"<\s*(script|iframe|object|embed|base|meta|link|form)\b", re.IGNORECASE), "a raw HTML element"),
    # Script-bearing URL schemes.
    (re.compile(r"(?:javascript|vbscript)\s*:", re.IGNORECASE), "a javascript:/vbscript: URL"),
    (re.compile(r"data:\s*text/html", re.IGNORECASE), "a data:text/html URL"),
]


def _find_unsafe_html(body: str) -> Optional[str]:
    """Return a human description of the first XSS-capable raw-HTML construct in
    the content body, or None if the body is safe. Benign formatting tags
    (<br>, <strong>, <em>, plain <a href>) are intentionally left alone."""
    for pattern, description in _UNSAFE_HTML_PATTERNS:
        if pattern.search(body):
            return description
    return None


def _schema_fallback_sections() -> List[str]:
    """Section names from the committed templates/sections-schema.json — the
    generated snapshot of the component library. Used only when the astro-basic
    component directory itself cannot be scanned (e.g. a slim install that
    ships the schema but not the template sources)."""
    schema_path = Path(template_path("sections-schema.json"))
    data = json.loads(schema_path.read_text(encoding="utf-8"))
    return sorted(data["sections"].keys())


def get_allowed_sections() -> List[str]:
    """
    Returns the list of MDX section components available in the sealed template.
    Derived from the actual component files so the whitelist can never drift;
    falls back to the generated sections-schema.json snapshot when the
    component directory is missing. Raises TemplatesUnavailableError (via
    template_path) when no templates tree exists at all — a silently empty
    whitelist would reject every section the model writes.
    """
    sections_dir = Path(template_path("astro-basic", "src", "components", "sections"))
    try:
        names = sorted(p.stem for p in sections_dir.glob("*.astro"))
        if names:
            return names
    except OSError:
        pass
    return _schema_fallback_sections()


# (cache_key, parsed blocks) — keyed on the file's identity/size/mtime so an
# in-process regeneration of SECTIONS.md (the training loop does this) is
# picked up instead of serving a stale parse for the process lifetime.
_SECTION_BLOCKS_CACHE: Optional[tuple] = None


def _split_section_blocks(text: str) -> Dict[str, str]:
    """
    Single parse of SECTIONS.md into {component: full doc block}, where each
    block is the component's `## \\`<Name />\\`` header line, its one-line
    purpose, and its prop table verbatim (everything up to the next `---`
    separator or the next header). This is the ONE place that understands the
    file's layout — get_section_props() and get_section_reference_text() both
    derive from it so there is exactly one parser to keep in sync with
    generate_sections_doc.py's output format.
    """
    blocks: Dict[str, List[str]] = {}
    current = None
    for line in text.splitlines():
        header = re.match(r"##\s*`<(\w+)\s*/?>`", line)
        if header:
            current = header.group(1)
            blocks[current] = [line]
            continue
        if current is None:
            continue
        if line.strip() == "---":
            current = None
            continue
        blocks[current].append(line)
    return {name: "\n".join(lines).rstrip() for name, lines in blocks.items()}


def _get_section_blocks() -> Dict[str, str]:
    global _SECTION_BLOCKS_CACHE
    sections_path = Path(template_path("SECTIONS.md"))
    try:
        stat = sections_path.stat()
        cache_key = (str(sections_path), stat.st_size, stat.st_mtime_ns)
    except OSError:
        cache_key = (str(sections_path), None, None)
    if _SECTION_BLOCKS_CACHE is not None and _SECTION_BLOCKS_CACHE[0] == cache_key:
        return _SECTION_BLOCKS_CACHE[1]

    try:
        text = sections_path.read_text(encoding="utf-8")
    except OSError:
        text = ""

    blocks = _split_section_blocks(text)
    _SECTION_BLOCKS_CACHE = (cache_key, blocks)
    return blocks


def get_section_props() -> Dict[str, set]:
    """
    Returns {component: {allowed prop names}} parsed from SECTIONS.md — the same
    reference the agent is prompted with, so validation matches what the model
    was told. Components without a parsed table validate names only.
    """
    props: Dict[str, set] = {}
    for name, block in _get_section_blocks().items():
        prop_set: set = set()
        for line in block.splitlines():
            row = re.match(r"\|\s*`(\w+)`\s*\|", line)
            if row:
                prop_set.add(row.group(1))
        props[name] = prop_set
    return props


_PROP_TYPE_ROW_RE = re.compile(r"^\|\s*`(\w+)`\s*\|\s*(?:yes|no)\s*\|\s*`(.*?)`\s*\|")


def get_section_prop_types(name: str) -> Dict[str, str]:
    """
    Returns {prop_name: type_str} parsed from a component's SECTIONS.md prop
    table rows (`| \\`prop\\` | yes/no | \\`Type\\` | description |`) — the
    same per-component block get_section_props() and
    get_section_reference_text() read via _get_section_blocks(), so this is a
    SIBLING accessor, not a second SECTIONS.md parser: it derives from the
    SAME cache, just keeping one more column than get_section_props()'s
    name-only row regex (e.g. `{"image": "{ src: string; alt: string; }"}`).
    Backs prompts.py's compact SECTION_INDEX, which needs a prop's TYPE (not
    just its name) to flag structured (object/array) props the model would
    otherwise guess as a plain string.

    A row's type cell is wrapped in backticks and may itself contain
    markdown-escaped pipes for union types (e.g. `` `'left' \\| 'right'` ``)
    — matching non-greedily up to the FIRST closing backtick after the
    type's opening one still finds the right span, since those escaped
    pipes never contain a literal backtick. A row that doesn't match this
    fuller shape (e.g. a minimal test fixture with no required/type columns)
    is simply skipped rather than raising, so this stays tolerant of any
    block get_section_props() itself can still parse names from.
    """
    block = _get_section_blocks().get(name)
    if not block:
        return {}
    types: Dict[str, str] = {}
    for line in block.splitlines():
        m = _PROP_TYPE_ROW_RE.match(line)
        if m:
            types[m.group(1)] = m.group(2)
    return types


def get_section_reference_text(name: str) -> Optional[str]:
    """
    Returns a component's full documented block (header + one-line purpose +
    prop table) exactly as it appears in SECTIONS.md, or None if the name is
    unknown. Backs the on-demand `get_section_reference` tool in
    site_editor.py — the compact SECTION_INDEX in prompts.py only lists names
    and prop names, so this is where the model gets prop types/requiredness/
    descriptions for a section it's about to use.
    """
    return _get_section_blocks().get(name)


def _extract_top_level_attrs(tag_header: str) -> List[str]:
    """
    Extracts attribute names assigned at the top level of an MDX tag header,
    ignoring anything inside {...} expressions or quoted strings (object keys
    like `label:` inside `actions={[...]}` are not props).
    """
    flat = []
    depth = 0
    quote = None
    for ch in tag_header:
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            flat.append(ch)
    return re.findall(r"([A-Za-z_]\w*)\s*=(?![=>])", "".join(flat))


def _first_unbraced_attr(tag_header: str) -> Optional[str]:
    """Name of the first top-level attribute whose value is neither a quoted
    string nor a {...} expression — e.g. `actions=[...]` with the braces dropped,
    which is invalid MDX/JSX and breaks the build but slips past the prop-name
    check. Returns None when every top-level value is well-formed. Object keys
    inside {...} live at depth > 0 and are ignored."""
    depth = 0
    quote = None
    n = len(tag_header)
    i = 0
    while i < n:
        ch = tag_header[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        elif depth == 0 and ch == "=" and not (i + 1 < n and tag_header[i + 1] in "=>"):
            j = i - 1
            while j >= 0 and tag_header[j].isspace():
                j -= 1
            end = j + 1
            while j >= 0 and (tag_header[j].isalnum() or tag_header[j] == "_"):
                j -= 1
            name = tag_header[j + 1:end]
            k = i + 1
            while k < n and tag_header[k].isspace():
                k += 1
            if name and (k >= n or tag_header[k] not in "\"'{"):
                return name
        i += 1
    return None


# Fenced code blocks (``` or ~~~) and `inline code` spans render as literal
# text, not live JSX — never scan them for components or `{...}` expressions.
#
# This is a hand-rolled scanner (not a single regex) implementing the actual
# CommonMark/MDX fence and code-span rules, verified against the real
# @mdx-js/mdx compiler. The previous implementation used a backreference
# regex (`(\`{3,}|~{3,}).*?\1`) that matched ANY later occurrence of the same
# N-backtick substring as a "closer" — including one found INSIDE a longer
# run of backticks (a 3-backtick opener "closed" by the first 3 of a later
# 4-backtick run). MDX does NOT neutralize that shape: an inline code span
# only forms between two backtick runs of EXACTLY equal length; a
# length-mismatched later run is not a delimiter at all and the backticks
# (and anything between them) stay live. The old regex was therefore
# stripping — and hence never scanning — text MDX actually executes: a
# confirmed build-time RCE bypass.
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def _is_escaped(text: str, pos: int) -> bool:
    """
    True iff `text[pos]` is preceded by an ODD number of consecutive
    backslash characters (a backslash escapes exactly the single character
    immediately following it; a run of N backslashes leaves the character
    after them escaped iff N is odd — an even run is itself N/2 escaped
    backslashes and does not touch what follows).
    """
    count = 0
    j = pos - 1
    while j >= 0 and text[j] == "\\":
        count += 1
        j -= 1
    return count % 2 == 1


def _strip_inline_code_spans(text: str) -> str:
    """
    Removes inline code spans from `text` (a single paragraph's worth of
    non-fenced content — may contain embedded newlines, since CommonMark
    lets an inline code span's content include a single line ending within
    the same paragraph). Per CommonMark, a backtick run of length N is
    closed only by the NEXT run of EXACTLY N backticks — a run of any other
    length is not a delimiter for it and is left as literal text, with the
    search continuing past it for a true closer.

    A backslash-escaped backtick (`` \\` ``) is never a delimiter character
    at all — confirmed against the real @mdx-js/mdx compiler: `` a \\`{x}\\` b ``
    forms NO code span (the backslash escapes just that one backtick),
    leaving `{x}` live body text. The previous implementation was unaware of
    this and treated any backtick — escaped or not — as a real delimiter,
    which meant a backslash-escaped pair could hide a live `{...}` MDX
    expression from the scan: a confirmed build-time RCE bypass (fix round
    2). Only the run's OPENING character can ever be escaped (every other
    character in a run of backticks is preceded by another backtick, never
    a backslash), so the escape check only needs to run there; an escaped
    backtick is emitted as literal text and the scan continues from the very
    next character (which may itself start a new, unescaped, shorter run).
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "`":
            out.append(text[i])
            i += 1
            continue
        if _is_escaped(text, i):
            out.append(text[i])
            i += 1
            continue
        j = i
        while j < n and text[j] == "`":
            j += 1
        run_len = j - i
        k = j
        close_end = -1
        while k < n:
            if text[k] != "`":
                k += 1
                continue
            if _is_escaped(text, k):
                k += 1
                continue
            k2 = k
            while k2 < n and text[k2] == "`":
                k2 += 1
            if k2 - k == run_len:
                close_end = k2
                break
            k = k2
        if close_end == -1:
            # No same-length closer anywhere in this paragraph — the
            # backticks stay literal text; whatever they "wrapped" is live
            # and must remain.
            out.append(text[i:j])
            i = j
        else:
            i = close_end
    return "".join(out)


def _strip_code_spans(body: str) -> str:
    """
    Removes fenced code blocks and inline code spans so JSX examples inside
    code (e.g. a ```jsx fence showing <Suspense>) — and any `{...}` written
    purely as documentation text — are not mistaken for live component
    markup/expressions.

    Two phases, matching real CommonMark/MDX block structure:
    1. Line-based fence scanning: a valid fence opener/closer always
       resolves at the BLOCK level regardless of surrounding paragraph
       text (a fence can interrupt a paragraph with no blank line needed),
       so this always runs first, line by line.
    2. Whatever text fencing didn't consume is grouped into paragraphs (a
       blank line, same as a fence, always ends one) and inline code spans
       are stripped across each whole paragraph at once — a span's content
       may include one embedded line ending, so this must not be scoped to
       a single line.

    Line endings are normalized (CRLF/CR -> LF) before splitting into lines.
    Without this, a closing fence line ending in "\r\n" keeps its trailing
    "\r" after `body.split("\n")`, which never matches the closer regex
    (only trailing spaces/tabs are allowed) — the fence is then wrongly
    classified as unclosed and "swallows to EOF", hiding everything after
    the real close (including a live `{...}` expression) from every scan
    that reads `scan_body`: a confirmed build-time RCE bypass (fix round 2).
    """
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = body.split("\n")
    raw_out: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = _FENCE_OPEN_RE.match(line)
        valid_opener = False
        fence_char = fence_len = None
        if m:
            run, rest = m.group(1), m.group(2)
            fence_char, fence_len = run[0], len(run)
            # A backtick-fenced opening line's info string may not itself
            # contain a backtick (CommonMark); if it does, this line is not
            # a valid fence opener at all — real MDX leaves it (and any
            # `{...}` on later lines) as live text. Tilde fences have no
            # such restriction.
            valid_opener = not (fence_char == "`" and "`" in rest)
        if valid_opener:
            close_re = re.compile(
                r"^ {0,3}" + re.escape(fence_char) + "{" + str(fence_len) + r",}[ \t]*$"
            )
            j = i + 1
            while j < n and not close_re.match(lines[j]):
                j += 1
            # Whether closed (a valid closer found) or unclosed (ran to
            # EOF — CommonMark: an unterminated fence neutralizes to end of
            # file), the whole fence block collapses to a single empty
            # placeholder line: the newline immediately before the opener
            # and immediately after the closer survive; every newline
            # strictly inside the fence does not.
            raw_out.append("")
            i = n if j >= n else j + 1
            continue
        raw_out.append(line)
        i += 1

    result_lines: List[str] = []
    i = 0
    n = len(raw_out)
    while i < n:
        if raw_out[i] == "":
            result_lines.append("")
            i += 1
            continue
        j = i
        while j < n and raw_out[j] != "":
            j += 1
        paragraph = "\n".join(raw_out[i:j])
        result_lines.extend(_strip_inline_code_spans(paragraph).split("\n"))
        i = j
    return "\n".join(result_lines)


# --- Literal-only MDX `{...}` expression grammar (Wave 2 Task 3) -----------
#
# `{...}` in MDX is a live JavaScript expression evaluated at Astro build
# time. Agent-written content must never be allowed to smuggle executable
# code there (process.env reads, filesystem/exec access, dynamic imports,
# side-effecting IIFEs, etc.) — only pure data literals are legitimate:
# arrays, objects (bareword or quoted-string keys), strings, numbers,
# booleans, and null.
#
# This is an ALLOWLIST grammar, not a denylist: a substring blocklist is
# exactly what a red-team defeats (there is always one more spelling of
# `process`). Instead, every quoted string is neutralized to a placeholder,
# then the remaining "shape" of the expression is checked against a tiny
# fixed set of punctuation, digits, and bareword-as-object-key positions —
# anything else (identifiers used as values, member access, calls, arrow
# functions, template literals, comments, unicode-escape identifier tricks,
# optional chaining, spreads, ...) is rejected because it simply cannot be
# spelled using only the allowed characters.
_STRING_LITERAL_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.DOTALL)
_BAREWORD_RE = re.compile(r"[A-Za-z_$][\w$]*")
_LITERAL_KEYWORDS = {"true", "false", "null"}
# Everything allowed to remain once every quoted string has been replaced by
# the single-character placeholder and every legitimate bareword (a literal
# keyword, or an object key immediately followed by ':') has been removed.
_DISALLOWED_LEFTOVER_RE = re.compile(r"[^\[\]{}:,.\-+\s0-9§]")
_STRING_PLACEHOLDER = "§"  # '§' — not a JS identifier character, so it
# can never be mistaken for a bareword by _BAREWORD_RE, and is added to the
# leftover allowlist above just for this placeholder.

# Standard JS numeric-literal forms that are pure data (safe to allow): hex
# (`0x1F`), an optional exponent suffix on a decimal number (`1e10`,
# `1E-10`), and a leading-dot float (`.5`). Matched and replaced with a
# same-length run of '0' characters *before* the bareword scan below, so
# e.g. the `x`/`e` inside `0x1F`/`1e10` is never mistaken for a standalone
# identifier used in value position. The leading-dot alternative requires
# it NOT be immediately preceded by an identifier character — otherwise
# masking the '.' in something like `obj.5` (member access on a numeric
# property name, not a valid literal at all) would erase the very
# character that keeps `obj` and `5` from being merged into one bareword
# token by the scan below.
_NUMBER_LITERAL_RE = re.compile(
    r"0[xX][0-9a-fA-F]+"
    r"|\d+\.\d*(?:[eE][+-]?\d+)?"
    r"|(?<![\w$])\.\d+(?:[eE][+-]?\d+)?"
    r"|\d+(?:[eE][+-]?\d+)?"
)


def _is_literal_expression(expr: str) -> bool:
    """
    True iff `expr` (the text inside a `{...}` MDX expression, braces
    excluded) parses as a pure data literal: an array/object/string/number/
    boolean/null, and nothing else. False for any construct that would
    execute code at build time (identifiers used as values, member access,
    calls, arrow functions, template literals, imports, comments, ...).
    """
    # Template literals execute their `${...}` interpolations, so a backtick
    # anywhere — even one a naive scan might assume is "just a character
    # inside a string" — is rejected outright. This is deliberately
    # conservative: it also rejects a quoted string that merely *contains* a
    # literal backtick character, trading a small false-positive rate for a
    # simpler, unambiguous rule.
    if "`" in expr:
        return False

    # (a) Neutralize every quoted string (object keys or values) so nothing
    # inside it — including a string that itself contains code-like text —
    # is reasoned about as code.
    destringed = _STRING_LITERAL_RE.sub(_STRING_PLACEHOLDER, expr)
    if '"' in destringed or "'" in destringed:
        # A leftover quote character means a string never closed, or a quote
        # appears outside of a clean string literal — not a parseable literal.
        return False

    # (a2) Neutralize standard JS numeric-literal forms (hex, exponent,
    # leading-dot float) to same-length '0' runs so the checks below (the
    # '.' adjacency rule, the bareword scan) see them as plain digits rather
    # than tripping over the letters in `0x1F`/`1e10` or the dot in `.5`.
    destringed = _NUMBER_LITERAL_RE.sub(lambda m: "0" * len(m.group(0)), destringed)

    # (b) Calls, arrow functions, statement separators are never part of a
    # data literal.
    if "(" in destringed or ")" in destringed or "=>" in destringed or ";" in destringed:
        return False
    # A '.' is only legitimate as a decimal point between two digits;
    # anywhere else it is member access (or a spread's '...').
    for m in re.finditer(r"\.", destringed):
        i = m.start()
        before = destringed[i - 1] if i > 0 else ""
        after = destringed[i + 1] if i + 1 < len(destringed) else ""
        if not (before.isdigit() and after.isdigit()):
            return False
    # A computed key ( `[expr]:` ) is not a bareword or string key — reject
    # it outright rather than rely on its *contents* alone being caught,
    # since `]` can only legitimately be followed by ':' via this shape (an
    # array VALUE is always followed by ',' / '}' / end-of-input, never ':').
    if re.search(r"\]\s*:", destringed):
        return False

    # A '+'/'-' is only legitimate as a unary sign directly in front of a
    # number, at a position where a new value begins (start of the
    # expression, or right after '[', '{', ',', ':', or another sign).
    # Anywhere else it's a binary arithmetic/string-concat operator — e.g.
    # `1 + 2` or `"a" + "b"` — which, while inert here, is not a literal.
    _value_start = set("[{:,+-")
    for i, ch in enumerate(destringed):
        if ch not in "+-":
            continue
        after = destringed[i + 1] if i + 1 < len(destringed) else ""
        if not (after.isdigit() or after == "."):
            return False
        j = i - 1
        while j >= 0 and destringed[j].isspace():
            j -= 1
        if j >= 0 and destringed[j] not in _value_start:
            return False

    # (c) Every bareword must be a literal keyword, or an object key (a
    # bareword immediately followed, after optional whitespace, by ':').
    # Anything else — a bare identifier, a function name, a computed-key
    # expression, `require`, `import`, ... — is an identifier used in value
    # position, which is exactly the shape every injection payload needs.
    pieces = []
    last = 0
    for m in _BAREWORD_RE.finditer(destringed):
        word = m.group(0)
        start, end = m.span()
        if word not in _LITERAL_KEYWORDS:
            j = end
            while j < len(destringed) and destringed[j].isspace():
                j += 1
            if not (j < len(destringed) and destringed[j] == ":"):
                return False
        pieces.append(destringed[last:start])
        last = end
    pieces.append(destringed[last:])
    remainder = "".join(pieces)

    # (d) Whatever's left (after removing recognized barewords and quoted
    # strings) must be nothing but literal-shaped punctuation, digits, and
    # whitespace. This is the safety net that catches anything not spelled
    # out above: comments (`/* */`, `//`), optional chaining (`?.`),
    # nullish/logical operators, bitwise/exponent operators, unicode
    # homoglyph identifiers, stray backslashes (unicode-escape identifier
    # tricks), etc. — none of those can be built from this charset.
    if _DISALLOWED_LEFTOVER_RE.search(remainder):
        return False

    return True


# _js_aware_brace_end moved to agent.mdx_scan (shared with the api's
# mdx_editor so both sides agree on expression spans); alias kept for the
# in-module call sites and the validator tests.


def _expression_values(tag_header: str) -> List[str]:
    """
    Returns the inner text (braces excluded) of every top-level `{...}`
    group in an MDX tag header — both `attr={...}` values and any bare
    `{...}` spread — respecting quoted attribute-string boundaries so a
    literal `{`/`}` inside a quoted value is never mistaken for a live
    expression boundary, and using `_js_aware_brace_end` to find each
    group's TRUE end (so a `}` embedded in a JS string/backtick/comment
    inside the expression itself can never truncate it).
    """
    values: List[str] = []
    i = 0
    n = len(tag_header)
    quote = None
    while i < n:
        ch = tag_header[i]
        if quote:
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            i += 1
            continue
        if ch == "{":
            end = _js_aware_brace_end(tag_header, i)
            values.append(tag_header[i + 1:end])
            i = end + 1
            continue
        i += 1
    return values


def _bare_body_expressions(body: str, tag_spans: List[tuple]) -> List[str]:
    """
    Returns the inner text of every top-level `{...}` group found in `body`
    text that falls entirely outside the given component tag-header spans
    (those are validated separately via `_expression_values`). MDX treats
    ANY top-level `{...}` in body text as a live JS expression — there is no
    "just prose that happens to contain braces" escape hatch in real MDX —
    so every one found here must also be a pure literal. Uses
    `_js_aware_brace_end` so a `}` embedded in a JS string/backtick/comment
    inside the expression can never truncate the scan.
    """
    masked = list(body)
    for s, e in tag_spans:
        for i in range(s, min(e, len(masked))):
            masked[i] = " "
    text = "".join(masked)
    values: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "{":
            end = _js_aware_brace_end(text, i)
            if end >= n:
                # Unterminated top-level brace: the file has a structural
                # syntax error the Astro build will reject regardless;
                # nothing further can be safely attributed past this point.
                break
            values.append(body[i + 1:end])
            i = end + 1
            continue
        i += 1
    return values


def _tag_header(body: str, start: int) -> str:
    """Returns the tag header from `start` (at '<') up to its closing '>',
    respecting quotes and delegating every top-level `{...}` interior to
    `_js_aware_brace_end` — the SAME comment/string-aware helper
    `_expression_values` uses — so both functions can never compute a
    different boundary for the same tag. Falls back to the rest of the body
    when no closing '>' is found outside a quote/expression.

    A previous version walked `{...}` interiors with its own naive
    char-by-char quote/depth tracker that toggled `quote` on ANY raw quote
    character, even one that isn't a real string delimiter at all (e.g. the
    apostrophe in `it's` inside a `/* it's a note */` JS comment nested in an
    attribute expression). With no partner quote left in the remaining text,
    that tracker got stuck "inside a string" to EOF and returned
    `body[start:]` — the WHOLE REST OF THE FILE as one tag header — which
    then masks everything after it from `_bare_body_expressions` via
    `raw_tag_spans`. Not exploitable in practice (such comments are
    independently rejected by the literal-expression grammar or aren't valid
    MDX), but an accidental safety net that a future change could silently
    lose. Delegating to `_js_aware_brace_end` removes the whole class of
    bug (comments, backtick spans, and backslash-escaped quotes inside an
    expression are all handled correctly, the same way `_expression_values`
    already handles them)."""
    i = start
    n = len(body)
    quote = None
    while i < n:
        ch = body[i]
        if quote:
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            i += 1
            continue
        if ch == "{":
            i = _js_aware_brace_end(body, i) + 1
            continue
        if ch == ">":
            return body[start:i + 1]
        i += 1
    return body[start:]


def check_navigation_consistency(settings_content: str, page_files: List[str]) -> Optional[str]:
    """
    Cross-checks navigation entries in settings.yaml against the existing pages.
    Returns a human-readable warning when a nav url points to a page that does
    not exist (external links and pure anchors are skipped), else None.
    """
    try:
        parsed = yaml.safe_load(settings_content)
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None

    pages = set()
    for f in page_files:
        f = f.replace("\\", "/")
        if f.startswith("content/pages/") and os.path.splitext(f)[1] in (".md", ".mdx"):
            slug = os.path.splitext(f[len("content/pages/"):])[0]
            pages.add("" if slug == "index" else slug)

    missing = []
    for entry in (parsed.get("navigation") or []):
        if not isinstance(entry, dict):
            continue
        url = (entry.get("url") or entry.get("href") or "").strip()
        if not url or url.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path = url.split("#")[0].strip("/")
        if path not in pages:
            missing.append(url)

    if missing:
        return (
            f"Navigation links point to pages that do not exist: {', '.join(missing)}. "
            "Create those pages or remove the links, otherwise visitors get broken navigation."
        )
    return None


def _split_frontmatter(content: str):
    """Returns (frontmatter_str or None, body)."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, re.DOTALL)
    if match:
        return match.group(1), match.group(2)
    return None, content


def validate_content(file_path: str, content: str) -> Optional[Dict[str, Any]]:
    """
    Validates agent-generated content BEFORE it is committed, so syntax errors
    are caught immediately instead of one CI build cycle later.
    Returns None when valid, or a machine-readable error dict with a fix hint
    that the model can act on within the same turn.
    """
    if content is not None and len(content) > MAX_CONTENT_LENGTH:
        return {
            "error": f"Content for '{file_path}' is too large ({len(content)} chars; limit {MAX_CONTENT_LENGTH}).",
            "fix_hint": "Reduce the file size — split long pages into sections or trim the content.",
        }

    # Detect double-escaping: literal \n (backslash-n) used instead of real newlines.
    # Happens when the model JSON-encodes the content string before placing it in the
    # function call, producing \\n/\\" in JSON → literal \n/" in the parsed string.
    if content is not None and "\n" not in content and "\\n" in content:
        return {
            "error": f"Content for '{file_path}' contains literal backslash-n ('\\n') sequences instead of real newline characters.",
            "fix_hint": (
                "Pass the file text with actual newlines — do not manually escape the content. "
                "MDX attribute values with quotes (e.g. heading=\"My Title\") should be submitted "
                "exactly as they appear, without extra backslash escaping."
            ),
        }

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return {
            "error": f"Invalid file extension '{ext}' for '{file_path}'.",
            "fix_hint": "Only .md, .mdx, .yaml or .yml files may be created in content/.",
        }

    if ext in (".yaml", ".yml"):
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError as e:
            return {
                "error": f"Invalid YAML syntax in '{file_path}': {e}",
                "fix_hint": "Fix the YAML syntax and call the tool again with the corrected full file content.",
            }
        if file_path.endswith("settings.yaml") and not isinstance(parsed, dict):
            return {
                "error": "settings.yaml must be a YAML mapping (key: value structure).",
                "fix_hint": "Provide the full settings.yaml with top-level keys like site:, contact:, navigation:.",
            }
        return None

    # Markdown / MDX pages
    frontmatter_str, body = _split_frontmatter(content)
    is_page = file_path.replace("\\", "/").startswith("content/pages/")

    frontmatter = None
    if frontmatter_str is not None:
        try:
            frontmatter = yaml.safe_load(frontmatter_str)
        except yaml.YAMLError as e:
            return {
                "error": f"Invalid YAML frontmatter in '{file_path}': {e}",
                "fix_hint": "Fix the frontmatter between the --- markers and resubmit the full file.",
            }

    if is_page:
        if not isinstance(frontmatter, dict):
            return {
                "error": f"'{file_path}' is missing YAML frontmatter.",
                "fix_hint": 'Pages must start with frontmatter, e.g.\n---\ntitle: "Page Title"\ndescription: "SEO description"\npageLayout: "full"\n---',
            }
        if not frontmatter.get("title"):
            return {
                "error": f"'{file_path}' frontmatter is missing the required 'title' field.",
                "fix_hint": 'Add title: "..." to the frontmatter.',
            }
        if "layout" in frontmatter:
            return {
                "error": "Frontmatter uses the reserved property 'layout'.",
                "fix_hint": "Rename 'layout' to 'pageLayout' (values: default, full, sidebar).",
            }

    # Block XSS-capable raw HTML in any rendered markdown/MDX body. Runs for all
    # .md/.mdx content, not just pages, since non-page markdown is rendered too.
    unsafe = _find_unsafe_html(body)
    if unsafe:
        return {
            "error": f"'{file_path}' contains {unsafe}, which is not allowed in site content.",
            "fix_hint": (
                "Remove raw HTML event handlers, <script>/<iframe>/<object>/<embed>/"
                "<form>/<meta>/<link> tags, and javascript:/data:text/html URLs. Use "
                "markdown and the provided section components instead."
            ),
        }

    if ext == ".mdx" or is_page:
        # RCE-critical: normalize line endings before any scanning at all. A
        # lone trailing "\r" (from a CRLF or CR-only file) surviving into a
        # "\n"-split line defeats fence/closer-line matching — see
        # `_strip_code_spans`'s docstring — which is exactly how a fix-round-2
        # bypass hid a live `{...}` expression from every check that read
        # `scan_body`. Every check below runs on this normalized body; the
        # raw, un-normalized `body` is never scanned again past this point.
        norm_body = body.replace("\r\n", "\n").replace("\r", "\n")

        # One shared pre-pass: code fences / inline code render as text, so
        # the component-NAME and PROP scans below (only) use it. Those two
        # scans are NOT a security boundary — a false positive there is a
        # harmless "unknown component"/build-break message, never RCE — so a
        # best-effort, imperfect stripper is an acceptable basis for them.
        # (`_strip_code_spans` also normalizes line endings itself, so this
        # is defense in depth, not a dependency on the line above.)
        scan_body = _strip_code_spans(norm_body)

        # A top-level import/export line is a real MDX/ESM statement (not a
        # {...} expression at all, so the literal-expression checks below
        # never see it), and it is exactly how the build-time RCE payloads
        # pull in node:fs / node:child_process. Agent content never needs an
        # import or export. RCE-critical, like the expression scan below:
        # scans the normalized RAW body, never `scan_body` — a stripper bug
        # that mis-hides an import statement must never be load-bearing for
        # this check (fix round 2: this used to read `scan_body`, and a
        # CRLF-triggered "unclosed fence swallows to EOF" mis-strip could
        # hide an `import ... from "node:child_process"` line from it).
        if re.search(r"(?m)^\s*(import|export)\b", norm_body):
            return {
                "error": f"'{file_path}' contains an import/export statement, which is not allowed in agent-authored content.",
                "fix_hint": "Remove the import/export line; only markdown prose and section components are allowed in content files.",
            }

        allowed = set(get_allowed_sections())
        used = set(re.findall(r"<([A-Z][A-Za-z0-9]*)", scan_body))
        unknown = sorted(used - allowed)
        if unknown:
            return {
                "error": f"Unknown section component(s) in '{file_path}': {', '.join(unknown)}. These do not exist and the site build would fail.",
                "fix_hint": f"Only use these sections: {', '.join(sorted(allowed))}.",
            }

        # RCE-critical, fail-closed expression scan (fix round 2). Every
        # `{...}` — component-attribute or bare-body — must be a pure
        # literal, and this scan runs over the normalized RAW body, NEVER
        # over `scan_body`: the SECURITY guarantee must not depend on
        # `_strip_code_spans` correctly identifying fence/code-span
        # boundaries, because that stripper has repeatedly had bypasses (see
        # the fence-bypass and CRLF/backslash-escape notes throughout this
        # module). Consequence, accepted as safe: a non-literal `{...}`
        # written purely as documentation inside what looks like a fenced
        # code SAMPLE is now rejected too (over-rejection, never
        # under-rejection) — only a genuinely PURE-LITERAL `{...}` (e.g.
        # `{3}`, `{"x"}`) can appear anywhere in the file, fenced or not.
        raw_tag_spans: List[tuple] = []
        for match in re.finditer(r"<([A-Z][A-Za-z0-9]*)", norm_body):
            comp = match.group(1)
            header = _tag_header(norm_body, match.start())
            raw_tag_spans.append((match.start(), match.start() + len(header)))
            for inner in _expression_values(header):
                if not _is_literal_expression(inner):
                    return {
                        "error": f"Section <{comp}> attribute expression must be a literal (lists/objects/strings/numbers only); executable expressions are not allowed.",
                        "fix_hint": 'Use plain data, e.g. actions={[{ label: "...", href: "..." }]} — no function calls, imports, or variable references.',
                    }
        # Bare-body {...} expressions (outside any component tag header) are
        # just as live as attribute ones — MDX evaluates any top-level {...}
        # in body text as JavaScript — so they must be pure literals too.
        for inner in _bare_body_expressions(norm_body, raw_tag_spans):
            if not _is_literal_expression(inner):
                return {
                    "error": f"'{file_path}' contains an inline {{ }} expression in the page body that is not allowed.",
                    "fix_hint": "Write literal text; only section-component attributes may carry { } data.",
                }

        # ONE scan of the stripped body collects every component tag with its
        # quote/brace-aware header (computed once per tag); the prop check and
        # the self-closing count below both consume it. Error precedence is
        # unchanged: first offending tag in document order for the prop
        # checks, then the unterminated-tag heuristic over the whole file.
        scanned_tags: List[tuple] = []  # (comp, header) in document order
        for match in re.finditer(r"<([A-Z][A-Za-z0-9]*)", scan_body):
            scanned_tags.append((match.group(1), _tag_header(scan_body, match.start())))

        # Validate the props of each section against the documented reference
        # — undocumented props silently no-op or break the build, costing a
        # full CI round-trip to discover. Not a security boundary (worst case
        # is a harmless "unknown component"/build-break message), so this
        # keeps using the stripper-based `scan_body`, as before.
        section_props = get_section_props()
        for comp, header in scanned_tags:
            # Every top-level attribute value must be a quoted string or a {...}
            # expression. A bare value like actions=[...] (missing its braces) is
            # invalid MDX and breaks the build, yet passes the prop-name check.
            unbraced = _first_unbraced_attr(header)
            if unbraced:
                return {
                    "error": f"Section <{comp}> in '{file_path}' has attribute '{unbraced}' with an unbraced value; array/object/expression values must be wrapped in {{ }}.",
                    "fix_hint": f"Write {unbraced}={{ ... }} (e.g. {unbraced}={{[ ... ]}} for a list of items). Only quoted string values may omit the braces.",
                }
            documented = section_props.get(comp)
            if not documented:
                continue
            bad = [a for a in _extract_top_level_attrs(header) if a not in documented]
            if bad:
                return {
                    "error": f"Section <{comp}> in '{file_path}' uses unknown propert{'ies' if len(bad) > 1 else 'y'}: {', '.join(sorted(set(bad)))}.",
                    "fix_hint": f"<{comp}> only supports: {', '.join(sorted(documented))}.",
                }

        # Heuristic check for unterminated component tags. Count self-closing
        # tags via the collected _tag_header results (quote/brace-aware)
        # rather than a naive `<comp[^>]*?/>` regex, so a '>' inside an
        # attribute string or a {expression} doesn't truncate the tag and make
        # a properly self-closed section look unterminated.
        opens: Dict[str, int] = {}
        self_closing: Dict[str, int] = {}
        for comp, header in scanned_tags:
            opens[comp] = opens.get(comp, 0) + 1
            if header.rstrip().endswith("/>"):
                self_closing[comp] = self_closing.get(comp, 0) + 1
        for comp in used:
            closes = len(re.findall(rf"</{comp}>", scan_body))
            if opens.get(comp, 0) != self_closing.get(comp, 0) + closes:
                return {
                    "error": f"Section <{comp}> appears to have an unterminated tag in '{file_path}'.",
                    "fix_hint": f"Close every <{comp} .../> with /> (self-closing) or a matching </{comp}>.",
                }

    return None
