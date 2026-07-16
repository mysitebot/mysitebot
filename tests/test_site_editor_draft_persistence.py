"""F05: draft persistence as a mutation postcondition.

Today a turn can end after branch_and_edit_content/delete_content_file set
pipeline_triggered=True but before the model calls create_publish_request
(model drop, LLMTransientError) — the app then builds stale `main` and tells
the user their change is live. Both mutation tools must now create+persist
the publish request themselves, deterministically, before pipeline_triggered
may be set — so a turn that ends early can never leave an unrecorded commit
behind a "your change is live" message.

These tests use the repo's standard seed_workspace/fake_store fixtures (see
conftest.py) plus a local _make_editor/_driving pair mirroring conftest's
make_editor — extended with an injectable git_provider, since the plain
LocalGitProvider always succeeds create_merge_request deterministically and
records no calls, and these tests need to both observe and (once) fail it."""
import pytest

from agent.llm.testing import patch_run_turn
from agent.llm.types import LLMResult, Usage
from agent.providers.git.base import LocalGitProvider
from agent.site_editor import AgentSiteEditor

DRAFT_FILES = {
    "content/pages/index.mdx": "---\ntitle: Home\n---\n",
    "content/pages/about.mdx": "---\ntitle: About\n---\n",
    "content/settings.yaml": "site:\n  name: My Business\n",
}


class RecordingGitProvider(LocalGitProvider):
    """A real LocalGitProvider (so commits/deletes/reads still touch the
    workspace like every other test in this suite) that also records
    create_merge_request calls and can be told to make that one call fail —
    the two things the plain provider can't do (it always succeeds silently
    and keeps no call log)."""

    def __init__(self, workspace_root, *, mr_error: Exception | None = None):
        super().__init__(workspace_root=workspace_root)
        self.calls: list[tuple] = []
        self._mr_error = mr_error

    async def create_merge_request(self, project_id, source_branch, target_branch, title):
        self.calls.append(("create_merge_request", project_id, source_branch, target_branch, title))
        if self._mr_error is not None:
            raise self._mr_error
        return await super().create_merge_request(project_id, source_branch, target_branch, title)


def _make_editor(monkeypatch, ws, driver, *, store=None, git_provider=None):
    """Same construction as conftest's make_editor fixture, but accepts a
    custom git_provider (make_editor hardcodes a plain LocalGitProvider)."""
    patch_run_turn(monkeypatch, driver)
    provider = git_provider or LocalGitProvider(workspace_root=str(ws))
    return AgentSiteEditor(git_provider=provider, api_key="test-key", store=store)


def _driving(drive):
    """run_turn driver that hands the bound tool map to `drive` (same pattern
    as test_site_editor_delete.py's _driving)."""
    async def driver(*, system_instruction, messages, tools):
        tool_map = {t.__name__: t for t in tools}
        await drive(tool_map)
        return LLMResult(text="All done!", tool_calls=[], usage=Usage())
    return driver


@pytest.mark.asyncio
async def test_first_edit_persists_draft_before_returning(monkeypatch, seed_workspace, fake_store):
    """F05: the model 'forgets' create_publish_request — the mutation tool
    must have created and persisted the draft anyway, before returning."""
    ws = seed_workspace(DRAFT_FILES)
    fake_store.projects["local_project"] = {"project_id": "local_project"}
    provider = RecordingGitProvider(str(ws))

    async def drive(tools):
        await tools["branch_and_edit_content"](
            branch_name="new-edit", file_path="content/pages/index.mdx",
            content="---\ntitle: Home\n---\n# Updated")

    editor = _make_editor(monkeypatch, ws, _driving(drive), store=fake_store, git_provider=provider)
    result = await editor.run("Update the homepage", "local_project")

    proj = fake_store.projects["local_project"]
    assert proj["pending_mr_iid"] is not None
    assert proj["pending_mr_branch"] == "new-edit"
    assert any(c[0] == "create_merge_request" for c in provider.calls)
    assert result["pipeline_triggered"] is True


@pytest.mark.asyncio
async def test_edit_with_open_draft_does_not_create_second_mr(monkeypatch, seed_workspace, fake_store):
    ws = seed_workspace(DRAFT_FILES)
    fake_store.projects["local_project"] = {
        "project_id": "local_project",
        "pending_mr_iid": 5,
        "pending_mr_branch": "draft-1",
    }
    provider = RecordingGitProvider(str(ws))
    out = {}

    async def drive(tools):
        out["res"] = await tools["branch_and_edit_content"](
            branch_name="new-edit", file_path="content/pages/index.mdx",
            content="---\ntitle: Home\n---\n# Updated again")

    editor = _make_editor(monkeypatch, ws, _driving(drive), store=fake_store, git_provider=provider)
    result = await editor.run("Update the homepage again", "local_project")

    assert out["res"]["branch"] == "draft-1"
    assert not any(c[0] == "create_merge_request" for c in provider.calls)
    assert result["pipeline_triggered"] is True
    # The already-open draft record is untouched.
    proj = fake_store.projects["local_project"]
    assert proj["pending_mr_iid"] == 5
    assert proj["pending_mr_branch"] == "draft-1"


@pytest.mark.asyncio
async def test_mr_failure_returns_error_and_no_build(monkeypatch, seed_workspace, fake_store):
    """The commit already landed on the branch when create_merge_request
    raises — the tool must still surface an error and refuse to arm the
    pipeline, so the app never builds stale main over an unrecorded draft."""
    ws = seed_workspace(DRAFT_FILES)
    fake_store.projects["local_project"] = {"project_id": "local_project"}
    provider = RecordingGitProvider(str(ws), mr_error=RuntimeError("gitlab is down"))
    out = {}

    async def drive(tools):
        out["res"] = await tools["branch_and_edit_content"](
            branch_name="new-edit", file_path="content/pages/index.mdx",
            content="---\ntitle: Home\n---\n# Updated")

    editor = _make_editor(monkeypatch, ws, _driving(drive), store=fake_store, git_provider=provider)
    result = await editor.run("Update the homepage", "local_project")

    assert "error" in out["res"]
    assert result["pipeline_triggered"] is False
    assert fake_store.projects["local_project"].get("pending_mr_iid") is None
    # The commit itself is real (orphaned on an unrecorded branch — the
    # documented trade-off, mirroring the app's manual editor).
    assert (ws / "content" / "pages" / "index.mdx").read_text() == "---\ntitle: Home\n---\n# Updated"


@pytest.mark.asyncio
async def test_delete_content_file_also_persists_draft(monkeypatch, seed_workspace, fake_store):
    ws = seed_workspace(DRAFT_FILES)
    fake_store.projects["local_project"] = {"project_id": "local_project"}
    provider = RecordingGitProvider(str(ws))

    async def drive(tools):
        await tools["delete_content_file"](
            branch_name="remove-about", file_path="content/pages/about.mdx")

    editor = _make_editor(monkeypatch, ws, _driving(drive), store=fake_store, git_provider=provider)
    result = await editor.run("remove the about page", "local_project")

    proj = fake_store.projects["local_project"]
    assert proj["pending_mr_iid"] is not None
    assert proj["pending_mr_branch"] == "remove-about"
    assert any(c[0] == "create_merge_request" for c in provider.calls)
    assert result["pipeline_triggered"] is True


@pytest.mark.asyncio
async def test_create_publish_request_reports_already_open_after_auto_draft(
        monkeypatch, seed_workspace, fake_store):
    ws = seed_workspace(DRAFT_FILES)
    fake_store.projects["local_project"] = {"project_id": "local_project"}
    provider = RecordingGitProvider(str(ws))
    out = {}

    async def drive(tools):
        await tools["branch_and_edit_content"](
            branch_name="new-edit", file_path="content/pages/index.mdx",
            content="---\ntitle: Home\n---\n# Updated")
        out["res"] = await tools["create_publish_request"](
            branch_name="new-edit", title="Publish my change")

    editor = _make_editor(monkeypatch, ws, _driving(drive), store=fake_store, git_provider=provider)
    await editor.run("Update the homepage and publish it", "local_project")

    assert out["res"]["status"] == "already_open"
    mr_calls = [c for c in provider.calls if c[0] == "create_merge_request"]
    assert len(mr_calls) == 1
