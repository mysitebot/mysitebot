"""The frozen public surface of the OSS `sam` distribution.

Every name here is imported by the private product. If a symbol is removed or
renamed, this test fails FIRST — forcing a conscious contract change rather than
a silent break of the downstream repo.
"""
import importlib

import agent

# (module, symbol) pairs — exactly the surface the private `api` consumes.
PUBLIC_SURFACE = [
    ("agent.site_editor", "AgentSiteEditor"),
    ("agent.site_editor", "TurnContext"),
    ("agent.templates", "template_path"),
    ("agent.templates", "BUILD_ENV_PASSTHROUGH"),
    ("agent.providers.git.base", "GitProvider"),
    ("agent.providers.git.base", "LocalGitProvider"),
    ("agent.media_search", "MediaSearch"),
    ("agent.media_search", "MediaResult"),
    ("agent.media_search", "WagmiMediaSearch"),
    ("agent.media_search", "render_results"),
    ("agent.content_safety", "is_safe_content_path"),
    ("agent.content_safety", "check_content_for_cookies"),
    ("agent.content_validator", "validate_content"),
    ("agent.mdx_scan", "js_aware_brace_end"),
    ("agent.llm", "LLMClient"),
    ("agent.llm.types", "LLMResult"),
    ("agent.llm.types", "Usage"),
]


def test_every_public_symbol_is_reexported_at_top_level():
    """`from agent import <Name>` works for every documented symbol."""
    for _module, name in PUBLIC_SURFACE:
        assert hasattr(agent, name), f"agent.{name} missing from the façade"


def test_facade_matches_underlying_modules():
    """The façade re-exports the SAME object as its source module (no shadowing)."""
    for module_name, name in PUBLIC_SURFACE:
        mod = importlib.import_module(module_name)
        assert getattr(agent, name) is getattr(mod, name), (
            f"agent.{name} is not the object from {module_name}"
        )


def test_all_is_declared_and_complete():
    exported = set(agent.__all__)
    expected = {name for _module, name in PUBLIC_SURFACE}
    assert expected <= exported, f"__all__ missing: {expected - exported}"
