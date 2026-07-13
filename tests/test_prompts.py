"""Guard tests for Task 5's positive-only prompt rewrite.

Documented footgun (2026-07-07 live eval, newsletter_about_001): for a
gemini-2.5-flash-class model, a prompt rule that QUOTES the unwanted behavior
verbatim — even inside a "NEVER do this" prohibition — plants that behavior
instead of suppressing it. These tests assert the forbidden exemplars are
gone from the assembled system instructions, and that the publish / page-
removal policy has exactly one source of truth (PUBLISH_POLICY /
PAGE_REMOVAL_POLICY) shared between the prompt and the corresponding tool
docstrings in site_editor.py, so the two can never drift apart again.
"""
import pytest

from agent.prompts import (
    BASE_SYSTEM_INSTRUCTION,
    ONBOARDING_WIZARD_INSTRUCTION,
    PUBLISH_POLICY,
    PAGE_REMOVAL_POLICY,
)

ASSEMBLED = BASE_SYSTEM_INSTRUCTION + ONBOARDING_WIZARD_INSTRUCTION


def test_no_quoted_forbidden_named_page_reply():
    """prompts.py used to quote the exact forbidden reply ("you don't have
    this page yet, would you like me to create it?") inside a NEVER clause —
    Sam parroted it verbatim live. The instruction must state the desired
    action only, never echo the bad reply."""
    assert "you don't have this page yet" not in ASSEMBLED.lower()


def test_no_placeholder_project_name_exemplar():
    """The onboarding rule used to name a bad placeholder project
    ('my-business-site') as a failure exemplar — replaced with a positive
    "ask for identity first" rule."""
    assert "my-business-site" not in ASSEMBLED


def test_intro_script_greeting_appears_exactly_once_outside_a_prohibition():
    """"Hello! I'm Sam" must appear exactly once in the assembled prompt: as
    the literal [INIT] intro script. It must NOT also appear quoted inside a
    "do NOT say ..." / "no ..." prohibition (the old wording named the
    greeting as a negative example, which plants it)."""
    occurrences = ASSEMBLED.count("Hello! I'm Sam")
    assert occurrences == 1, f"expected exactly 1 occurrence, found {occurrences}"
    idx = ASSEMBLED.index("Hello! I'm Sam")
    preceding = ASSEMBLED[max(0, idx - 100):idx].lower()
    assert "do not" not in preceding
    assert "no \"hello" not in preceding


def test_no_never_plus_quoted_reply_in_same_sentence():
    """No rule may combine a hard "NEVER" prohibition with a verbatim quoted
    example of the forbidden reply in the same sentence — that combination is
    exactly the footgun pattern that plants unwanted behavior in a
    flash-class model."""
    for sentence in ASSEMBLED.replace("\n", " ").split(". "):
        if "NEVER" in sentence and '"' in sentence:
            lowered = sentence.lower()
            assert "never reply with" not in lowered, f"forbidden pattern: {sentence!r}"
            assert "never say" not in lowered, f"forbidden pattern: {sentence!r}"


def test_bias_toward_action_principle_present():
    """Task 5 (22f28740) rewrote the named-page rule to drop the quoted
    forbidden reply (the flash footgun), but that rewrite also silently
    dropped the general "act, don't ask permission" imperative the quote had
    been carrying — regressing newsletter_fields_001 (holdout): Sam correctly
    picked ContactForm over the email-only Newsletter section but then asked
    instead of building it. This restores that bias-to-action principle in
    positive-only form (no quoted reply, no named unwanted phrase)."""
    assert "Bias toward action" in BASE_SYSTEM_INSTRUCTION


def test_bias_toward_action_preserves_ambiguity_and_destructive_exception():
    """The bias-to-action rule must not become "never ask" — the corpus has
    negative scenarios (negative_ambiguous_homepage_001,
    negative_delete_site_001, ambiguous_button_reference_00X) where Sam
    SHOULD ask or refuse. The rule must explicitly carve those out."""
    idx = BASE_SYSTEM_INSTRUCTION.index("Bias toward action")
    window = BASE_SYSTEM_INSTRUCTION[idx:idx + 600]
    assert "ambiguous" in window.lower()
    assert "destructive" in window.lower()


def test_named_page_rule_still_creates_directly_without_asking():
    """The named-page bullet (Edit Loop step 1) must retain an explicit
    "act now, don't pause to check first" imperative — restored alongside
    the T5 no-footgun-quote wording — without reintroducing the quoted
    forbidden reply itself (covered by test_no_quoted_forbidden_named_page_reply)."""
    assert "without pausing first to check whether you should" in BASE_SYSTEM_INSTRUCTION


def test_no_visual_preview_promise_language():
    """Line 63 used to forbid promising a "visual preview" while line 80 (and
    site_editor's committed_fallback) promised a "live preview" — a direct
    contradiction. All "preview" language is dropped; the draft becomes
    visible once published, described without the word "preview"."""
    assert "preview" not in ASSEMBLED.lower()


def test_self_heal_script_wording_is_preview_free_in_prompt():
    """The self-heal script (prompts.py, step 5 of Auto-Correction &
    Self-Healing) must drop "preview" language entirely."""
    assert "corrected it automatically" in BASE_SYSTEM_INSTRUCTION
    assert "I'll let you know the moment it's live" in BASE_SYSTEM_INSTRUCTION


@pytest.mark.asyncio
async def test_committed_fallback_matches_prompt_no_preview_wording(
        tmp_path, monkeypatch):
    """site_editor.py's committed_fallback (the reply used when an is_system
    self-heal turn commits a fix but returns empty text — see
    test_site_editor_selfheal.py) must use the SAME no-preview wording as the
    prompt's self-heal script, not the old contradictory "live preview" text."""
    from agent.llm.types import LLMResult, Usage
    from agent.providers.git.base import LocalGitProvider
    from agent.site_editor import AgentSiteEditor

    ws = tmp_path / "workspace"
    (ws / "content" / "pages").mkdir(parents=True)
    (ws / "content" / "pages" / "about.mdx").write_text("---\ntitle: About\n---\nbroken")
    (ws / "content" / "settings.yaml").write_text("site:\n  name: My Business\n")

    async def _run_turn(self, *, system_instruction, messages, tools,
                         force_thinking=False):
        tool_map = {t.__name__: t for t in tools}
        await tool_map["branch_and_edit_content"](
            branch_name="fix-build", file_path="content/pages/about.mdx",
            content="---\ntitle: About\npageLayout: \"default\"\n---\n<Hero heading=\"About Us\" />\n")
        return LLMResult(text="", tool_calls=[], usage=Usage())

    monkeypatch.setattr("agent.llm.LLMClient.run_turn", _run_turn)
    provider = LocalGitProvider(workspace_root=str(ws))
    editor = AgentSiteEditor(git_provider=provider, api_key="test-key")
    result = await editor.run("build failed logs...", "local_project", is_system=True)

    assert "preview" not in result["text"].lower()
    assert "corrected it automatically" in result["text"]
    assert "I'll let you know the moment it's live" in result["text"]


@pytest.mark.asyncio
async def test_publish_policy_is_shared_single_source(tmp_path, monkeypatch, fake_store):
    """PUBLISH_POLICY must be the literal text embedded in both the system
    prompt and the publish_changes tool docstring — one source of truth.
    (Publish tools only exist in store-backed mode — see
    test_site_editor_publish_gating.py.)"""
    assert PUBLISH_POLICY in BASE_SYSTEM_INSTRUCTION
    tool_map = await _get_tool_map(tmp_path, monkeypatch, store=fake_store)
    assert PUBLISH_POLICY in (tool_map["publish_changes"].__doc__ or "")


@pytest.mark.asyncio
async def test_page_removal_policy_is_shared_single_source(tmp_path, monkeypatch):
    """PAGE_REMOVAL_POLICY must be the literal text embedded in both the
    system prompt and the delete_content_file tool docstring — one source
    of truth."""
    assert PAGE_REMOVAL_POLICY in BASE_SYSTEM_INSTRUCTION
    tool_map = await _get_tool_map(tmp_path, monkeypatch)
    assert PAGE_REMOVAL_POLICY in (tool_map["delete_content_file"].__doc__ or "")


async def _get_tool_map(tmp_path, monkeypatch, store=None):
    """Instantiates a real AgentSiteEditor over a throwaway local workspace,
    drives one turn with a stubbed LLM (same seam as the rest of the suite,
    agent.llm.testing.patch_run_turn) that performs no tool calls, and
    returns the {name: function} map of tools handed to run_turn — the only
    way to inspect the nested closures' live __doc__ strings. Pass a store
    for SaaS (publish-capable) mode."""
    from agent.llm.testing import patch_run_turn
    from agent.llm.types import LLMResult, Usage
    from agent.providers.git.base import LocalGitProvider
    from agent.site_editor import AgentSiteEditor

    captured = {}

    async def driver(*, system_instruction, messages, tools):
        captured["tools"] = {t.__name__: t for t in tools}
        return LLMResult(text="ok", tool_calls=[], usage=Usage())

    patch_run_turn(monkeypatch, driver)

    ws = tmp_path / "workspace"
    (ws / "content" / "pages").mkdir(parents=True)
    (ws / "content" / "pages" / "index.mdx").write_text("---\ntitle: Home\n---\n")
    (ws / "content" / "settings.yaml").write_text("site:\n  name: My Business\n")
    provider = LocalGitProvider(workspace_root=str(ws))
    editor = AgentSiteEditor(git_provider=provider, api_key="test-key", store=store)
    await editor.run("hello", "local_project")
    return captured["tools"]
