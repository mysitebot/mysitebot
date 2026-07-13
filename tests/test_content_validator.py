import pytest
from agent.content_validator import validate_content, get_allowed_sections, _strip_code_spans


def test_allowed_sections_derived_from_template():
    sections = get_allowed_sections()
    assert "Hero" in sections
    assert "ContactForm" in sections
    assert len(sections) >= 10


def test_valid_mdx_page_passes():
    content = '---\ntitle: "Home"\npageLayout: "full"\n---\n<Hero heading="Welcome" />\n'
    assert validate_content("content/pages/index.mdx", content) is None


def test_unknown_section_rejected():
    content = '---\ntitle: "Home"\n---\n<MegaWidget heading="x" />\n'
    error = validate_content("content/pages/index.mdx", content)
    assert error is not None
    assert "MegaWidget" in error["error"]
    assert "fix_hint" in error


def test_missing_frontmatter_rejected():
    error = validate_content("content/pages/about.mdx", "# Just markdown")
    assert error is not None
    assert "frontmatter" in error["error"]


def test_missing_title_rejected():
    content = '---\ndescription: "x"\n---\nBody'
    error = validate_content("content/pages/about.mdx", content)
    assert error is not None
    assert "title" in error["error"]


def test_reserved_layout_property_rejected():
    content = '---\ntitle: "x"\nlayout: "full"\n---\nBody'
    error = validate_content("content/pages/about.mdx", content)
    assert error is not None
    assert "pageLayout" in error["fix_hint"]


def test_invalid_yaml_rejected():
    error = validate_content("content/settings.yaml", "site:\n  name: [unclosed")
    assert error is not None
    assert "YAML" in error["error"]


def test_valid_settings_yaml_passes():
    content = 'site:\n  name: "My Shop"\nnavigation:\n  - label: "Home"\n    url: "/"\n'
    assert validate_content("content/settings.yaml", content) is None


def test_settings_yaml_with_analytics_block_passes():
    # The default template settings contain an analytics block; editing the
    # site name must not be rejected by the privacy guard.
    content = (
        'site:\n  name: "Coffee Palace"\n'
        'analytics:\n  enabled: true\n  website_id: "abc"\n'
    )
    assert validate_content("content/settings.yaml", content) is None


def test_disallowed_extension_rejected():
    error = validate_content("content/evil.html", "<html></html>")
    assert error is not None
    assert ".html" in error["error"]


def test_unterminated_section_tag_rejected():
    content = '---\ntitle: "x"\n---\n<Hero heading="oops"\n\nSome text'
    error = validate_content("content/pages/index.mdx", content)
    assert error is not None
    assert "Hero" in error["error"]


# --- Section prop validation (props are documented in SECTIONS.md; anything
# --- else silently breaks or no-ops at build time) ---

def test_unknown_section_prop_rejected():
    content = '---\ntitle: "x"\n---\n<Banner text="hi" colour="red" />'
    error = validate_content("content/pages/index.mdx", content)
    assert error is not None
    assert "colour" in error["error"]
    assert "text" in error["fix_hint"], "the fix hint should list the valid props"


def test_known_props_pass_including_complex_expressions():
    content = (
        '---\ntitle: "x"\n---\n'
        '<Hero \n'
        '  badge="New"\n'
        '  heading="Grow fast"\n'
        '  align="center"\n'
        '  actions={[{ label: "Go", href: "/contact", variant: "primary" }]}\n'
        '/>'
    )
    assert validate_content("content/pages/index.mdx", content) is None


def test_object_literal_keys_are_not_mistaken_for_props():
    # label/href/variant live INSIDE the actions expression — only top-level
    # attribute names are props.
    content = (
        '---\ntitle: "x"\n---\n'
        '<ContactForm heading="Hi" fields={[{ label: "Email", type: "email", required: true }]} />'
    )
    assert validate_content("content/pages/index.mdx", content) is None


def test_unbraced_array_attribute_rejected():
    # `actions=[...]` is invalid MDX (array/object values must be wrapped in
    # { }); it breaks the Astro build but slips past the prop-name check. The
    # model sometimes drops the braces when re-emitting a section.
    content = (
        '---\ntitle: "x"\n---\n'
        '<Hero heading="Welcome" actions=[{ label: "Go", href: "/c" }] />'
    )
    error = validate_content("content/pages/index.mdx", content)
    assert error is not None
    assert "actions" in error["error"]
    assert "{" in error["fix_hint"]


def test_quoted_value_containing_equals_not_flagged_unbraced():
    # A '=' inside a quoted string value must not be mistaken for an attribute
    # whose value is an unbraced expression.
    content = (
        '---\ntitle: "x"\n---\n'
        '<Hero heading="a = b = c" subheading="ok" />'
    )
    assert validate_content("content/pages/index.mdx", content) is None


def test_self_closing_tag_with_gt_in_attribute_not_unterminated():
    # A '>' inside an attribute value (a quoted string OR a {expression}) must not
    # fool the unterminated-tag heuristic into rejecting a properly self-closed
    # tag — e.g. a feature description that literally contains '>'.
    string_gt = (
        '---\ntitle: "x"\n---\n'
        '<Features heading="Why Us" features={[{ title: "Fast", description: "Ships in > 24h" }]} />'
    )
    assert validate_content("content/pages/index.mdx", string_gt) is None
    # (post-Task-3: the '>' here must live inside a quoted string, not a bare
    # comparison — `show: 2 > 1` was itself a non-literal expression and the
    # literal-only grammar now (correctly) rejects it.)
    expr_gt = (
        '---\ntitle: "x"\n---\n'
        '<Hero heading="Hi" actions={[{ label: "Go", href: "/c", show: "2 > 1" }]} />'
    )
    assert validate_content("content/pages/index.mdx", expr_gt) is None


# --- Code fences / inline code must not be scanned as live JSX ---


def test_fenced_code_jsx_is_not_treated_as_live_component():
    content = (
        '---\ntitle: "Docs"\n---\n'
        'Example usage:\n\n'
        '```jsx\n<Suspense fallback="spinner">\n  <Widget />\n</Suspense>\n```\n\n'
        '<Hero heading="Hi" />\n'
    )
    assert validate_content("content/pages/docs.mdx", content) is None


def test_inline_code_jsx_is_not_treated_as_live_component():
    content = '---\ntitle: "Docs"\n---\nUse the `<Suspense>` component in React.\n'
    assert validate_content("content/pages/docs.mdx", content) is None


def test_real_unknown_component_outside_code_still_fails():
    content = '---\ntitle: "Docs"\n---\n`<Hero />` is fine but this is not:\n\n<Suspense />\n'
    error = validate_content("content/pages/docs.mdx", content)
    assert error is not None
    assert "Suspense" in error["error"]


def test_unterminated_tag_count_ignores_fences():
    # The open-only <Hero> inside the fence must not make the real, properly
    # self-closed <Hero /> below look unterminated.
    content = (
        '---\ntitle: "Docs"\n---\n'
        '```\n<Hero heading="x">\n```\n\n'
        '<Hero heading="ok" />\n'
    )
    assert validate_content("content/pages/docs.mdx", content) is None


def test_unterminated_fence_swallows_rest_of_file():
    # An unclosed fence turns everything after it into code — no live JSX there.
    content = '---\ntitle: "Docs"\n---\nIntro\n\n```\n<Suspense>\n'
    assert validate_content("content/pages/docs.mdx", content) is None


# --- Fence-stripping bypass (fix round 1): mismatched backtick-run lengths --
#
# CommonMark/MDX only forms an inline code span between two backtick runs of
# EXACTLY equal length; a mismatched-length later run is not a delimiter at
# all (verified against the real @mdx-js/mdx compiler). The old
# `_FENCED_CODE_RE` backreference regex incorrectly matched a 3-backtick
# opener against the first 3 backticks of a LATER 4-backtick run, stripping
# — and thus never scanning — an executable `{...}` MDX expression: a
# confirmed build-time RCE bypass (also covered end-to-end in
# tests/security/test_mdx_expression_injection.py).


def test_mismatched_3open_4close_backticks_do_not_form_a_span():
    content = (
        '---\ntitle: "x"\n---\n'
        "prose ```{process.env.SECRET}```` more\n"
    )
    error = validate_content("content/pages/index.mdx", content)
    assert error is not None, "a length-mismatched backtick run must not hide a live expression"


def test_mismatched_4open_3close_backticks_do_not_form_a_span():
    content = (
        '---\ntitle: "x"\n---\n'
        "prose ````{process.env.SECRET}``` more\n"
    )
    error = validate_content("content/pages/index.mdx", content)
    assert error is not None


# Fix round 2: the literal-expression SECURITY scan no longer trusts
# `scan_body` (the stripper's output) at all — it scans the normalized RAW
# body directly, so a non-literal `{...}` is rejected wherever it textually
# appears, including inside what looks like a fully-neutralizing fenced code
# SAMPLE. This is a deliberate, accepted over-rejection (never an
# under-rejection): the SECURITY guarantee must not depend on the stripper
# being byte-perfect, because it has repeatedly had bypasses. The 4 tests
# below now assert `validate_content` REJECTS these bodies end-to-end, while
# still separately proving `_strip_code_spans` correctly neutralizes them
# (the property the component-NAME/PROP scans — not a security boundary —
# still rely on).


def test_matched_backtick_run_length_code_span_is_neutralized():
    # Equal-length delimiters DO form a real inline code span, so scan_body
    # (used by the component-name/prop scans) must still treat the bracketed
    # text as inert documentation, not live JSX.
    body = "Example: ```{process.env.SECRET}``` is how NOT to write MDX.\n"
    assert "process.env.SECRET" not in _strip_code_spans(body)
    content = '---\ntitle: "Docs"\n---\n' + body
    assert validate_content("content/pages/docs.mdx", content) is not None


def test_block_fence_closer_at_least_as_long_as_opener_still_closes():
    # CommonMark: a closing fence only needs length >= the opening fence's
    # length, not an exact match — scan_body still neutralizes it correctly.
    body = "```\n{process.env.SECRET}\n````\n"
    assert "process.env.SECRET" not in _strip_code_spans(body)
    content = '---\ntitle: "Docs"\n---\n' + body
    assert validate_content("content/pages/docs.mdx", content) is not None


def test_block_fence_closer_shorter_than_opener_runs_to_eof():
    # A closer SHORTER than the opener does not close it; CommonMark then
    # treats the fence as unclosed to end-of-file — scan_body still
    # neutralizes it (and everything after) correctly.
    body = "````\n{process.env.SECRET}\n```\nmore prose after\n"
    assert "process.env.SECRET" not in _strip_code_spans(body)
    content = '---\ntitle: "Docs"\n---\n' + body
    assert validate_content("content/pages/docs.mdx", content) is not None


def test_backtick_fence_with_backtick_in_info_string_is_not_a_fence():
    # A backtick-fenced opening line's info string may not itself contain a
    # backtick (CommonMark); if it does, the line is NOT a valid fence
    # opener at all, so nothing after it is neutralized as code — genuinely
    # live either way, rejected before and after round 2.
    content = '---\ntitle: "Docs"\n---\n```` `oops`\n{process.env.SECRET}\n````\n'
    error = validate_content("content/pages/docs.mdx", content)
    assert error is not None


def test_tilde_fence_info_string_may_contain_backtick():
    # Unlike backtick fences, a tilde fence's info string MAY contain a
    # backtick — this is still a valid, fully-neutralizing fence at the
    # scan_body level.
    body = "~~~ `x`\n{process.env.SECRET}\n~~~\n"
    assert "process.env.SECRET" not in _strip_code_spans(body)
    content = '---\ntitle: "Docs"\n---\n' + body
    assert validate_content("content/pages/docs.mdx", content) is not None


# --- Brace matchers must be quote/backtick/comment-aware (Important #2) ----
#
# A naive brace-depth counter that isn't aware of JS strings/backticks/
# comments would end an "expression" early at a `}` embedded inside one of
# those, silently dropping the real executable tail from the scan. Currently
# non-exploitable only by coincidence (the truncated fragment trips the
# stray-quote/backtick check) — these tests prove the extraction itself is
# now correct (the whole expression is captured), not merely that the
# accidental truncation happens to still get rejected.


def test_bare_body_expression_scans_past_string_embedded_brace():
    from agent.content_validator import _bare_body_expressions

    body = 'Welcome. { a: "x } y", secret: process.env.SECRET } more.'
    values = _bare_body_expressions(body, [])
    assert values == [' a: "x } y", secret: process.env.SECRET ']


def test_expression_values_scans_past_backtick_embedded_brace():
    from agent.content_validator import _expression_values

    header = 'Hero heading={`a } b`} subheading="ok"'
    values = _expression_values(header)
    assert values == ["`a } b`"]


def test_bare_body_expression_with_string_brace_and_executable_tail_rejected():
    # End-to-end: the string-embedded '}' must not truncate the scan and let
    # the real executable tail (process.env.SECRET) slip through unchecked.
    content = (
        '---\ntitle: "x"\n---\n'
        'Welcome. { a: "x } y", secret: process.env.SECRET } more.\n'
    )
    error = validate_content("content/pages/index.mdx", content)
    assert error is not None


# --- _tag_header / _expression_values boundary agreement (hardening round 3) -
#
# `_tag_header` used to walk `{...}` interiors with its own naive quote/depth
# tracker: any raw quote CHARACTER flipped its `quote` state unconditionally,
# even one appearing inside a JS comment/backtick where it isn't a real
# string delimiter at all (e.g. the apostrophe in `it's` inside
# `/* it's a note */`). Once that happened with no partner quote left in the
# remaining text, the tracker got stuck "inside a string" to EOF and
# `_tag_header` fell back to `body[start:]` — the WHOLE REST OF THE FILE —
# instead of the tag's true, much shorter, boundary. That wrong (too-long)
# boundary then gets used as a `raw_tag_spans` mask in `validate_content`,
# hiding everything after the tag from `_bare_body_expressions`. `_tag_header`
# now delegates every top-level `{...}` interior to `_js_aware_brace_end` —
# the SAME comment/string-aware helper `_expression_values` relies on — so
# the two can never compute a different boundary for the same expression.
#
# This is a property test, not a smoke test: for each tricky tag header it
# computes an INDEPENDENT reference boundary (written here, not calling
# `_tag_header` at all) using the identical `_js_aware_brace_end` primitive,
# and asserts `_tag_header`'s actual returned length matches it exactly. A
# future regression back to a naive per-char tracker in `_tag_header` — even
# one that happens to look reasonable — will diverge from this reference and
# fail here, without needing to guess the exact adversarial payload shape
# again.
def _reference_tag_header_end(text: str, start: int) -> int:
    """Independent oracle for where a tag header ends (exclusive index just
    past its closing '>'), built directly on `_js_aware_brace_end` — the
    same primitive `_expression_values` uses for every `{...}` interior —
    rather than on `_tag_header` itself."""
    from agent.content_validator import _js_aware_brace_end

    i = start
    n = len(text)
    quote = None
    while i < n:
        ch = text[i]
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
            end = _js_aware_brace_end(text, i)
            if end >= n:
                return n
            i = end + 1
            continue
        if ch == ">":
            return i + 1
        i += 1
    return n


_TAG_HEADER_BOUNDARY_CASES = [
    pytest.param(
        "<Hero heading={/* it's a note */ 1} /> trailing text more",
        id="comment_with_apostrophe",
    ),
    pytest.param(
        '<Hero heading="a { b > c" sub="ok" /> trailing text',
        id="attr_string_containing_brace_and_gt",
    ),
    pytest.param(
        "<Hero data={{a: 1}} /> trailing text",
        id="nested_double_brace",
    ),
    pytest.param(
        '<Hero heading={"a } b"} /> trailing text',
        id="brace_inside_string_inside_expr",
    ),
    pytest.param(
        '<Hero a="1" b={2} c="three" d={{x: 1}} /> trailing text',
        id="mixed_literal_and_expression_attrs",
    ),
]


@pytest.mark.parametrize("text", _TAG_HEADER_BOUNDARY_CASES)
def test_tag_header_boundary_agrees_with_expression_values_primitive(text):
    from agent.content_validator import _tag_header

    header = _tag_header(text, 0)
    expected_end = _reference_tag_header_end(text, 0)
    assert len(header) == expected_end, (
        f"_tag_header disagrees with the _js_aware_brace_end-based reference "
        f"boundary: got header={header!r} (len {len(header)}), expected end "
        f"{expected_end} for text={text!r}"
    )
    assert "trailing text" not in header


# --- Numeric literal forms (Minor): exponent / hex / leading-dot floats -----


def test_is_literal_expression_accepts_exponent_number():
    assert _is_literal_expression("1e10") is True
    assert _is_literal_expression("1E-10") is True


def test_is_literal_expression_accepts_hex_number():
    assert _is_literal_expression("0x1F") is True


def test_is_literal_expression_accepts_leading_dot_float():
    assert _is_literal_expression(".5") is True


# --- Size caps: anything writable must stay round-trippable ---


def test_write_cap_not_larger_than_read_truncation_limit():
    # A file bigger than the read threshold gets truncated on read and then
    # permanently refuses rewrites; the write cap must never allow creating one.
    from agent.content_validator import MAX_CONTENT_LENGTH
    from agent.site_editor import READ_TRUNCATION_LIMIT
    assert MAX_CONTENT_LENGTH <= READ_TRUNCATION_LIMIT


def test_content_over_write_cap_rejected():
    from agent.content_validator import MAX_CONTENT_LENGTH
    content = '---\ntitle: "x"\n---\n' + "a" * MAX_CONTENT_LENGTH
    error = validate_content("content/pages/index.mdx", content)
    assert error is not None
    assert "too large" in error["error"]


# --- Section-props cache must follow SECTIONS.md changes (the training loop
# --- regenerates it in-process) ---


def test_section_props_cache_refreshes_when_sections_md_changes(tmp_path, monkeypatch):
    import os
    import agent.content_validator as cv

    doc = tmp_path / "SECTIONS.md"
    doc.write_text("## `<Hero />`\n\n| Prop |\n|---|\n| `heading` |\n")
    monkeypatch.setattr(cv, "template_path", lambda *parts: str(doc))
    monkeypatch.setattr(cv, "_SECTION_BLOCKS_CACHE", None)

    assert cv.get_section_props()["Hero"] == {"heading"}

    doc.write_text("## `<Hero />`\n\n| Prop |\n|---|\n| `heading` |\n| `badge` |\n")
    st = doc.stat()
    os.utime(doc, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    assert cv.get_section_props()["Hero"] == {"heading", "badge"}


# --- Raw HTML / XSS safety in rendered content ---


def test_event_handler_attribute_rejected():
    # <img onerror=...> is the canonical stored-XSS vector: MDX renders it as a
    # real <img> with the handler intact, so it must be blocked at edit time.
    content = '---\ntitle: "x"\n---\n<img src="x" onerror="fetch(\'//evil\')" />'
    error = validate_content("content/pages/index.mdx", content)
    assert error is not None
    assert "fix_hint" in error


def test_script_tag_rejected():
    content = '---\ntitle: "x"\n---\nHello <script>alert(1)</script>'
    error = validate_content("content/pages/index.mdx", content)
    assert error is not None


def test_javascript_url_rejected():
    content = '---\ntitle: "x"\n---\n[click](javascript:alert(1))'
    error = validate_content("content/pages/index.mdx", content)
    assert error is not None


def test_iframe_rejected_in_plain_markdown():
    # Applies to non-page .md content too, not just pages.
    content = 'Welcome\n\n<iframe src="https://evil.example"></iframe>'
    error = validate_content("content/home.md", content)
    assert error is not None


def test_benign_inline_html_still_allowed():
    # Common formatting tags must not be over-blocked.
    content = '---\ntitle: "x"\n---\nLine one<br/>Line two with <strong>bold</strong>.'
    assert validate_content("content/pages/index.mdx", content) is None


# --- Navigation consistency (system prompt rule 5: nav must match pages) ---

from agent.content_validator import check_navigation_consistency


def test_nav_link_to_missing_page_warns():
    settings = 'navigation:\n  - label: "About"\n    url: "/about"\n'
    warning = check_navigation_consistency(settings, ["content/pages/index.mdx"])
    assert warning is not None
    assert "/about" in warning


def test_nav_matching_pages_passes():
    settings = (
        'navigation:\n'
        '  - label: "Home"\n    url: "/"\n'
        '  - label: "About"\n    url: "/about"\n'
        '  - label: "Anchor"\n    url: "/#contact"\n'
        '  - label: "External"\n    url: "https://example.com"\n'
    )
    files = ["content/pages/index.mdx", "content/pages/about.mdx"]
    assert check_navigation_consistency(settings, files) is None


# --- Literal-only MDX `{...}` expression grammar (Wave 2 Task 3) -----------
#
# `{...}` bodies in MDX content are live JavaScript expressions evaluated at
# Astro build time. Content is agent-generated, untrusted-ish data, so only
# pure data literals (arrays/objects/strings/numbers/booleans/null) may
# appear — never identifiers, member access, calls, arrows, or template
# literals, all of which the red-team used to read process.env / the
# filesystem / shell out at build time.

from agent.content_validator import _is_literal_expression


@pytest.mark.parametrize(
    "expr",
    [
        '[{ label: "x", href: "/y", variant: "primary" }]',
        "3",
        '"hi"',
        "true",
        "false",
        "null",
        "{ a: 1, b: [2,3] }",
        '{ "a-b": "x" }',
        "-3.5",
        "+2",
        "[]",
        "{}",
    ],
)
def test_is_literal_expression_true_for_pure_literals(expr):
    assert _is_literal_expression(expr) is True


@pytest.mark.parametrize(
    "expr",
    [
        "process.env.X",
        'readFileSync("x")',
        'Function("...")()',
        "globalThis.x",
        "a => a",
        "`t${x}`",
        "foo",
        "1 + x",
        "obj.prop",
        '(() => { globalThis.x = 1; return "" })()',
        'import("node:fs")',
        "[foo]",
        '{ a: foo }',
        '{ a: require("fs") }',
    ],
)
def test_is_literal_expression_false_for_executable(expr):
    assert _is_literal_expression(expr) is False


def test_is_literal_expression_rejects_backtick_anywhere():
    # Template literals execute interpolations; reject even if the backtick
    # is nested deep inside an otherwise-literal-looking structure.
    assert _is_literal_expression('[ "a", `b` ]') is False


def test_is_literal_expression_bareword_object_key_allowed_but_not_value():
    assert _is_literal_expression("{ label: 1 }") is True
    assert _is_literal_expression("{ label: value }") is False


def test_is_literal_expression_rejects_computed_key():
    # `[expr]: value` is a computed key — not a bareword or string key — even
    # when the bracket content is itself a harmless literal string.
    assert _is_literal_expression('{ [x]: 1 }') is False
    assert _is_literal_expression('{ ["a"]: 1 }') is False


def test_is_literal_expression_rejects_binary_plus_minus():
    # '+'/'-' are only legitimate as a unary sign directly in front of a
    # number (e.g. -3.5); between two literals they are a binary
    # arithmetic/concat operator, not a data literal.
    assert _is_literal_expression("1 + 2") is False
    assert _is_literal_expression('"a" + "b"') is False
    assert _is_literal_expression("3 - 1") is False
    # Unary sign at the start of a value (array/object start, after a key,
    # after a comma, or at the very start of the expression) is still fine.
    assert _is_literal_expression("-3.5") is True
    assert _is_literal_expression("+2") is True
    assert _is_literal_expression("{ a: -1, b: [2, -3] }") is True
