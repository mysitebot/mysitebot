"""The editor's per-turn tool set, extracted from AgentSiteEditor.run().

build_tools() returns the same closures run() used to define inline — bound to
the editor instance and the per-turn TurnContext — so tool NAMES, signatures
and docstrings (the model-facing contract) are unchanged. The publish tools
are only offered when a store exists: without one there is no pending-draft
record to publish, and the prompt's publish narrative is dropped too (see
prompts.base_system_instruction).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

import yaml

from agent.content_safety import is_safe_content_path, check_content_for_cookies
from agent.content_validator import (
    MAX_CONTENT_LENGTH,
    check_navigation_consistency,
    get_section_reference_text,
    validate_content,
)
from agent.media_search import render_results
from agent.prompts import PAGE_REMOVAL_POLICY, PUBLISH_POLICY

if TYPE_CHECKING:  # only for type hints — site_editor imports this module
    from agent.site_editor import AgentSiteEditor, TurnContext

logger = logging.getLogger(__name__)

# Reads are truncated beyond this many characters. Shares the write cap so the
# two thresholds can never drift apart: any file the agent is allowed to write
# (validate_content enforces MAX_CONTENT_LENGTH) stays fully readable, and
# therefore rewritable — otherwise files between the two caps become write-once.
READ_TRUNCATION_LIMIT = MAX_CONTENT_LENGTH


async def _nav_warning(editor: "AgentSiteEditor", ctx: "TurnContext", branch: str,
                       settings_yaml: Optional[str] = None) -> Optional[str]:
    """Navigation must stay consistent with the pages that exist — returns the
    dangling-link warning for the given branch (reading settings.yaml from the
    repo unless the caller already has it), or None. Check failures are logged
    and swallowed: a broken warning probe must never fail the edit itself."""
    try:
        if settings_yaml is None:
            settings_yaml = await editor.git_provider.read_file(
                ctx.active_provider_id, "content/settings.yaml", ref=branch)
        pages = await editor.git_provider.list_files(
            ctx.active_provider_id, "content", ref=branch)
        return check_navigation_consistency(settings_yaml, pages)
    except Exception as e:
        logger.warning(f"[Agent Tool] Nav consistency check skipped: {e}")
        return None


def build_tools(editor: "AgentSiteEditor", ctx: "TurnContext") -> List[Callable]:
    """The core tools for one editor turn, in their stable advertised order.
    create_publish_request / publish_changes are omitted when the editor has
    no store (CLI / standalone mode)."""

    async def create_project(name: str, template: str = "astro-basic") -> Dict[str, Any]:
        """
        Creates a brand new customer website from the mysite.bot template.
        Supported templates: 'landing-page', 'business-standard', 'portfolio', 'restaurant-cafe', 'blog', or 'astro-basic' (default).
        Returns project ID and URL.
        """
        try:
            pre = await editor._before_create_project(name, ctx)
            if pre is not None:
                return pre
            res = await editor.git_provider.create_project(name, template)
            # Handle both 'id' (GitLab) and 'project_id' (legacy/local fallback)
            actual_id = res.get("id") or res.get("project_id")
            if actual_id:
                ctx.active_provider_id = str(actual_id)
            override = await editor._after_create_project(name, res, ctx)
            if override is not None:
                return override

            pages_url = (res.get("pages_url") or "").rstrip(".,!?")
            gitlab_url = (res.get("web_url") or "").rstrip(".,!?")

            # The initial template commit kicks off a build (GitLab CI on main,
            # or the in-process pipeline in local mode)
            ctx.pipeline_triggered = True

            logger.info(f"[Agent Tool] Successfully provisioned {name} for {editor.session_id}")
            return {
                "status": "success",
                "message": f"Website '{name}' has been successfully created and initialized.",
                "id": actual_id,
                "pages_url": pages_url,
                "gitlab_url": gitlab_url
            }
        except Exception as e:
            logger.error(f"[Agent Tool] Error in create_project: {e}")
            return {
                "error": f"Could not create the website: {e}",
                "fix_hint": "Check the name with check_project_availability (or pick a "
                            "different one) and try again; if it keeps failing, tell the "
                            "user plainly that the website could not be created right now."
            }

    async def check_project_availability(name: str) -> Dict[str, Any]:
        """
        Checks if a desired project name is available.
        This tool automatically cleans the name (lowercase, no spaces, no special chars)
        and handles duplicates by appending a numeric suffix.
        Returns the final available 'name' you should use.
        """
        # Provider-interface call: GitLab does a real namespace duplicate
        # check; the default (local) implementation sanitizes with the SAME
        # function that names the created folder, so the answer always
        # matches what create_project will actually use.
        return await editor.git_provider.check_project_availability(name)

    async def list_content_files() -> Dict[str, Any]:
        """
        Lists every content file of the active website (pages, settings).
        Use this to discover which pages exist before editing or adding pages.
        Reflects the unpublished draft when one is open.
        """
        try:
            files = await editor.git_provider.list_files(ctx.active_provider_id, "content", ref=await editor._read_ref(ctx))
            return {"files": files}
        except Exception as e:
            return {"error": f"Could not list files: {e}"}

    async def read_content_file(file_path: str) -> Dict[str, Any]:
        """
        Reads the current content of a file of the active website (e.g. 'content/pages/index.mdx'
        or 'content/settings.yaml'). ALWAYS read a file before editing it so your edit
        preserves everything the user did not ask to change. Returns the latest draft
        version when an unpublished draft is open, so you never edit from a stale state.
        """
        if not is_safe_content_path(file_path):
            return {"error": "Access denied: can only read files in the content/ directory."}
        try:
            content = await editor.git_provider.read_file(ctx.active_provider_id, file_path, ref=await editor._read_ref(ctx))
            # Bound the payload fed back into the model to keep tool-result token cost in check.
            if content and len(content) > READ_TRUNCATION_LIMIT:
                ctx.truncated_reads.add(file_path)
                content = content[:READ_TRUNCATION_LIMIT] + "\n\n...(truncated for length — this file is too large to rewrite safely)..."
            else:
                ctx.truncated_reads.discard(file_path)
            return {"file_path": file_path, "content": content}
        except Exception as e:
            return {"error": f"Could not read '{file_path}': {e}"}

    async def branch_and_edit_content(branch_name: str, file_path: str, content: str) -> Dict[str, Any]:
        """
        Commits the FULL new content of a single file to a draft branch.
        While an unpublished draft is open, every edit is automatically added to that
        draft (the branch_name argument is then ignored) so changes stack until published.
        Security Constraint: file_path MUST start with 'content/' and have a .md, .mdx, .yaml or .yml extension.
        Read the file first and include all existing content you do not intend to change.
        CRITICAL: The 'content' value must be the literal file text with real newline characters.
        Do NOT manually escape quotes or newlines — MDX attribute values like heading="My Title"
        must be submitted exactly as they appear in the file, without extra backslash escaping.
        """
        if not is_safe_content_path(file_path):
            return {"error": "Access denied: can only edit content/ directory."}
        if file_path in ctx.truncated_reads:
            return {
                "error": f"Refusing to rewrite '{file_path}': its content was truncated when read, "
                         "so a full rewrite would silently delete everything beyond the truncation point.",
                "fix_hint": "Tell the user this page has grown too large to edit automatically and "
                            "suggest splitting it into multiple smaller pages."
            }
        validation_error = validate_content(file_path, content)
        if validation_error:
            return validation_error
        cookie_error = check_content_for_cookies(content, file_path)
        if cookie_error:
            return {
                "error": f"Privacy Constraint Violated: The platform is strict 'Privacy First' and cookie-free. Generated file content contains forbidden cookie-accessing code/references. Details: {cookie_error}"
            }
        # Re-committing a file with its existing content produces no visible
        # change yet still reports success and rebuilds the site — the user
        # is then told their site changed when nothing did.
        try:
            # Compare against the SAME ref this edit will commit to (the open
            # draft / this turn's branch), not main. Reading main would make a
            # revert of drafted content back to main's text look like "no
            # change" and silently drop the user's undo while the draft keeps
            # the unwanted edit.
            existing = await editor.git_provider.read_file(
                ctx.active_provider_id, file_path, ref=await editor._read_ref(ctx))
        except Exception:
            existing = None
        if existing is not None and existing == content:
            return {
                "warning": f"No change: the new content of '{file_path}' is identical to what is already there — nothing was committed. "
                           "If the user asked for something different (e.g. a different image), choose a genuinely different option, "
                           "or tell them plainly that you could not find anything new."
            }
        draft_branch = await editor._pending_draft_branch(ctx)
        # All edits of a turn stack on one branch: the open draft if there is
        # one, else whatever branch this turn already committed to. Otherwise
        # a second edit with a different branch_name forks off and is never
        # included in the publish request.
        target_branch = draft_branch or ctx.turn_branch or branch_name
        try:
            result = await editor.git_provider.commit_file(ctx.active_provider_id, target_branch, file_path, content, f"Updated {file_path} via Sam AI")
        except Exception as e:
            return {"error": f"Commit failed: {e}", "fix_hint": "Check the file path and content, then try again."}
        ctx.pipeline_triggered = True
        ctx.turn_branch = target_branch
        if isinstance(result, dict):
            result = {**result, "branch": target_branch}
            if target_branch != branch_name:
                if draft_branch:
                    result["note"] = f"Added to the existing unpublished draft '{draft_branch}' — no new publish request is needed."
                else:
                    result["note"] = f"Added to this turn's draft branch '{target_branch}' so all changes publish together."
            # Surface a dangling navigation link immediately so it is fixed in-turn.
            if file_path.endswith(("settings.yaml", "settings.yml")):
                warning = await _nav_warning(editor, ctx, target_branch, settings_yaml=content)
                if warning:
                    result["warning"] = warning
        return result

    async def delete_content_file(branch_name: str, file_path: str) -> Dict[str, Any]:
        # __doc__ set below (composes the shared PAGE_REMOVAL_POLICY from
        # prompts.py so this tool's description and the system prompt's
        # "Removing a Page" section can never drift apart).
        if not is_safe_content_path(file_path):
            return {"error": "Access denied: can only delete files in the content/ directory."}
        normalized = file_path.lstrip("./")
        if normalized in ("content/pages/index.mdx", "content/pages/index.md"):
            return {
                "error": "The homepage cannot be deleted — every website needs one.",
                "fix_hint": "Offer to replace or rewrite the homepage content instead (branch_and_edit_content)."
            }
        if normalized in ("content/settings.yaml", "content/settings.yml"):
            return {
                "error": "The site settings file cannot be deleted.",
                "fix_hint": "Edit content/settings.yaml with branch_and_edit_content instead."
            }
        draft_branch = await editor._pending_draft_branch(ctx)
        target_branch = draft_branch or ctx.turn_branch or branch_name
        try:
            result = await editor.git_provider.delete_file(
                ctx.active_provider_id, target_branch, file_path, f"Deleted {file_path} via Sam AI")
        except FileNotFoundError:
            return {
                "error": f"'{file_path}' does not exist — nothing to delete.",
                "fix_hint": "Call list_content_files to see which files the website has."
            }
        except Exception as e:
            return {"error": f"Delete failed: {e}"}
        ctx.pipeline_triggered = True
        ctx.turn_branch = target_branch
        if isinstance(result, dict):
            result = {**result, "branch": target_branch}
            if draft_branch:
                result["note"] = f"Added to the existing unpublished draft '{draft_branch}' — no new publish request is needed."
            # A deleted page must not leave a dangling navigation entry —
            # surface it immediately so Sam fixes the menu in the same turn.
            warning = await _nav_warning(editor, ctx, target_branch)
            if warning:
                result["warning"] = warning
        return result

    delete_content_file.__doc__ = (
        "Permanently deletes a single content file (e.g. a page) from the website.\n\n"
        + PAGE_REMOVAL_POLICY +
        "\n\nWhile an unpublished draft is open, the deletion is added to that draft "
        "(the branch_name argument is then ignored) so changes stack until published."
    )

    async def create_publish_request(branch_name: str, title: str) -> Dict[str, Any]:
        """
        Creates a publish request (Merge Request) so the draft branch can be checked and then published to main.
        If a publish request is already open, the existing one is reused — edits on the
        open draft do not need a new publish request.
        """
        if editor.store:
            proj = (await editor.store.get_project(ctx.active_project_id)) or {}
            if proj.get("pending_mr_iid"):
                return {
                    "status": "already_open",
                    "iid": proj["pending_mr_iid"],
                    "branch": proj.get("pending_mr_branch"),
                    "message": "A publish request is already open for the current draft; your edits are included in it."
                }
        # The publish request must cover the branch the commits actually
        # landed on, regardless of the name the model passes here.
        source_branch = ctx.turn_branch or branch_name
        try:
            mr_data = await editor.git_provider.create_merge_request(ctx.active_provider_id, source_branch, "main", title)
        except Exception as e:
            return {"error": f"Could not create the publish request: {e}"}
        ctx.pipeline_triggered = True
        if editor.store:
            proj = await editor.store.get_project(ctx.active_project_id)
            if proj:
                proj["pending_mr_iid"] = mr_data.get("iid")
                proj["pending_mr_branch"] = source_branch
                await editor.store.save_project(ctx.active_project_id, proj)
        return mr_data

    async def publish_changes() -> Dict[str, Any]:
        # __doc__ set below (composes the shared PUBLISH_POLICY from
        # prompts.py so this tool's description and the system prompt's
        # Edit Loop step 5 can never drift apart).
        proj = await editor.store.get_project(ctx.active_project_id) if editor.store else None
        mr_iid = (proj or {}).get("pending_mr_iid")
        if not mr_iid:
            return {"error": "There is no pending draft to publish. Make an edit first."}
        try:
            await editor.git_provider.merge_merge_request(ctx.active_provider_id, mr_iid)
        except Exception as e:
            return {"error": f"Could not publish the changes: {e}"}
        if editor.store and proj:
            proj["pending_mr_iid"] = None
            proj["pending_mr_branch"] = None
            await editor.store.save_project(ctx.active_project_id, proj)
        ctx.pipeline_triggered = True
        return {"status": "published", "detail": "The changes are being deployed to the live website now."}

    publish_changes.__doc__ = (
        "Publishes the pending draft to the LIVE website (merges the open publish "
        "request to main).\n\n" + PUBLISH_POLICY
    )

    async def show_settings_page() -> Dict[str, Any]:
        """Returns the website's current global settings (site name, colors, contact, navigation)."""
        # The repository's settings.yaml is the source of truth (draft-aware)
        read_error = "the file is missing or is not a valid YAML mapping"
        try:
            raw = await editor.git_provider.read_file(ctx.active_provider_id, "content/settings.yaml", ref=await editor._read_ref(ctx))
            parsed = yaml.safe_load(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception as e:
            read_error = str(e)
        if editor.store:
            proj = await editor.store.get_project(ctx.active_project_id)
            if proj and "settings" in proj:
                return proj["settings"]
        # Never invent settings: relaying plausible-looking defaults would
        # tell the user their site has values it does not actually have.
        return {
            "error": f"Could not read the site settings (content/settings.yaml): {read_error}",
            "fix_hint": "Tell the user the settings could not be loaded right now — do not guess or invent values.",
        }

    async def show_website_status() -> Dict[str, Any]:
        """Renders the current website status screen including live site URLs, build states, and locks."""
        if editor.store:
            locked = await editor.store.is_locked(ctx.active_project_id)
            project = (await editor.store.get_project(ctx.active_project_id)) or {}
            last_pipe = project.get("last_pipeline") or {}

            site_url = project.get("pages_url") or "Generating..."

            status_text = "Idle"
            if locked:
                status_text = "Building / Applying Edits"
            elif last_pipe.get("status") == "success":
                status_text = "Live"
            elif last_pipe.get("status") == "failed":
                status_text = "Build Failed (Auto-healing in progress)"

            return {
                "site_name": project.get("name", "My Website"),
                "status": status_text,
                "live_url": site_url,
                "has_unpublished_draft": bool(project.get("pending_mr_iid")),
                "estimated_build_time": "2-3 minutes",
                "build_progress": "Ongoing" if locked else "Completed"
            }
        return {"status": "offline"}

    async def search_media_library(query: str) -> str:
        """Searches the internal privacy-first media library for high-quality CC0 images.
        ALWAYS use this tool to find image URLs instead of linking to external sites.

        Args:
            query: Descriptive semantic search query.
        """
        if editor.media_search is None:
            return "Media search is not configured in this environment."
        try:
            results = await editor.media_search.search(query)
        except Exception as e:
            return f"Error searching media library: {str(e)}"
        return render_results(results)

    async def get_section_reference(section_name: str) -> Dict[str, Any]:
        """
        Returns the full property reference (types, which properties are required, and
        descriptions) for ONE section component named in the system prompt's compact
        Section Reference index. Call this before first using a section in a turn so you
        fill in its properties correctly — the index only lists names and prop names, not
        full detail. Read-only; does not change the website.

        Args:
            section_name: The component name, e.g. "Hero" or "ContactForm" (no angle brackets).
        """
        reference = get_section_reference_text(section_name)
        if reference is None:
            return {
                "error": f"Unknown section '{section_name}'.",
                "fix_hint": "Use one of the exact component names listed in the Section Reference index.",
            }
        return {"section": section_name, "reference": reference}

    tools: List[Callable] = [
        create_project,
        check_project_availability,
        list_content_files,
        read_content_file,
        branch_and_edit_content,
        delete_content_file,
    ]
    # The publish flow only exists where a store can hold the pending-draft
    # record (SaaS). Without one there is nothing to publish from, so the
    # tools are withheld and the prompt's publish narrative is dropped in
    # step (see prompts.base_system_instruction(include_publish=False)).
    if editor.store is not None:
        tools += [create_publish_request, publish_changes]
    tools += [
        show_settings_page,
        show_website_status,
        search_media_library,
        get_section_reference,
    ]
    return tools
