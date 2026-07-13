"""Public API of the standalone site-editing agent (the OSS `sam` distribution).

This module is the FROZEN contract the private product depends on. Import public
names from here (`from agent import AgentSiteEditor`) rather than reaching into
submodules, so internal module layout can change without breaking consumers.
Adding to this surface is fine; removing/renaming is a breaking change and must
be deliberate (see tests/test_public_surface.py).
"""
from agent.content_safety import check_content_for_cookies, is_safe_content_path
from agent.content_validator import validate_content
from agent.llm import LLMClient
from agent.llm.types import LLMResult, Usage
from agent.mdx_scan import js_aware_brace_end
from agent.media_search import MediaResult, MediaSearch, WagmiMediaSearch, render_results
from agent.providers.git.base import GitProvider, LocalGitProvider
from agent.site_editor import AgentSiteEditor, TurnContext
from agent.templates import BUILD_ENV_PASSTHROUGH, template_path

__all__ = [
    "AgentSiteEditor",
    "TurnContext",
    "template_path",
    "BUILD_ENV_PASSTHROUGH",
    "GitProvider",
    "LocalGitProvider",
    "MediaSearch",
    "MediaResult",
    "WagmiMediaSearch",
    "render_results",
    "is_safe_content_path",
    "check_content_for_cookies",
    "validate_content",
    "js_aware_brace_end",
    "LLMClient",
    "LLMResult",
    "Usage",
]
