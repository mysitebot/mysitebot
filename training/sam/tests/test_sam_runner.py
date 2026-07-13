import pytest
import sam_runner
from conftest import make_scenario
from agent.llm.types import ToolCall


def test_extract_tool_calls_strips_suffix_and_maps_args():
    tool_calls = [
        ToolCall(name="branch_and_edit_content_tool",
                 args={"file_path": "content/settings.yaml"}, result="ok"),
    ]
    assert sam_runner.extract_tool_calls(tool_calls) == [
        {"name": "branch_and_edit_content",
         "args": {"file_path": "content/settings.yaml"}}]


def test_extract_tool_calls_handles_empty():
    assert sam_runner.extract_tool_calls(None) == []
    assert sam_runner.extract_tool_calls([]) == []


def test_workspace_changes_lists_modified_and_new_files(tmp_path):
    ws = tmp_path / "ws"
    (ws / "content").mkdir(parents=True)
    (ws / "content" / "a.md").write_text("one")
    sam_runner.init_baseline(ws)
    (ws / "content" / "a.md").write_text("two")
    (ws / "content" / "b.md").write_text("brand new")
    changes = sam_runner.workspace_changes(ws)
    assert changes["files"] == ["content/a.md", "content/b.md"]
    assert "two" in changes["diff"]
    assert "brand new" in changes["diff"]


def test_baseline_ignores_node_modules_dist(tmp_path):
    ws = tmp_path / "ws"
    (ws / "node_modules").mkdir(parents=True)
    (ws / "f.txt").write_text("f")
    sam_runner.init_baseline(ws)
    (ws / "node_modules" / "y.js").write_text("y")
    (ws / "dist").mkdir()
    (ws / "dist" / "index.html").write_text("<h1>x</h1>")
    assert sam_runner.workspace_changes(ws)["files"] == []


def test_run_sam_dry_applies_edits_and_returns_transcript(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    scenario = make_scenario(dry_run={
        "text": "done",
        "tool_calls": [{"name": "branch_and_edit_content", "args": {}}],
        "edits": {"content/pages/index.mdx": "---\ntitle: Home\n---\nMARKER\n"},
    })
    result = sam_runner.run_sam_dry(scenario, ws)
    assert result.text == "done"
    assert result.tool_calls[0]["name"] == "branch_and_edit_content"
    assert "MARKER" in (ws / "content" / "pages" / "index.mdx").read_text()


def test_workspace_changes_handles_paths_with_spaces(tmp_path):
    ws = tmp_path / "ws"
    (ws / "content" / "pages").mkdir(parents=True)
    (ws / "content" / "pages" / "index.mdx").write_text("base")
    sam_runner.init_baseline(ws)
    (ws / "content" / "pages" / "about us.mdx").write_text("new page")
    changes = sam_runner.workspace_changes(ws)
    assert changes["files"] == ["content/pages/about us.mdx"]


def test_workspace_changes_handles_rename_records(tmp_path):
    ws = tmp_path / "ws"
    (ws / "content").mkdir(parents=True)
    (ws / "content" / "old-page.mdx").write_text("x" * 200)
    sam_runner.init_baseline(ws)
    # stage an explicit rename so porcelain emits an R record with two fields
    sam_runner._git(ws, "mv", "content/old-page.mdx", "content/new-page.mdx")
    changes = sam_runner.workspace_changes(ws)
    assert "content/new-page.mdx" in changes["files"]
    assert "content/old-page.mdx" in changes["files"]   # the old path counts as changed
    assert ".mdx" not in changes["files"]               # no garbage entries


@pytest.mark.asyncio
async def test_provision_workspace_copies_template_and_baselines(tmp_path):
    scenario = make_scenario(
        id="prov_test",
        setup=[{"path": "content/extra.md", "content": "# extra"}])
    provider, project_dir = await sam_runner.provision_workspace(tmp_path, scenario)
    assert (project_dir / "content" / "settings.yaml").exists()
    assert (project_dir / "content" / "pages" / "index.mdx").exists()
    assert (project_dir / "content" / "extra.md").read_text() == "# extra"
    # setup edits are part of the baseline, not "changes"
    assert sam_runner.workspace_changes(project_dir)["files"] == []


def test_infra_error_classification():
    # Credentials/quota/endpoint problems are the harness's fault, not Sam's.
    import httpx
    import openai
    from agent.llm.types import LLMTransientError
    resp = httpx.Response(401, request=httpx.Request("POST", "http://llm.test"))
    assert sam_runner._is_infra_error(
        openai.AuthenticationError("Error code: 401 - dead key",
                                   response=resp, body=None))
    assert sam_runner._is_infra_error(LLMTransientError("exhausted retries"))
    assert not sam_runner._is_infra_error(ValueError("Sam crashed mid-edit"))


@pytest.mark.asyncio
async def test_run_sam_marks_auth_failure_as_infra(monkeypatch):
    import httpx
    import openai
    import agent.site_editor as se

    class BoomEditor:
        def __init__(self, **kwargs):
            pass

        async def run(self, prompt, project_id, is_init=False, is_system=False):
            resp = httpx.Response(401, request=httpx.Request("POST", "http://llm.test"))
            raise openai.AuthenticationError("Error code: 401 - dead key",
                                             response=resp, body=None)

    monkeypatch.setattr(se, "AgentSiteEditor", BoomEditor)
    result = await sam_runner.run_sam(make_scenario(), provider=None, model="gemini-x")
    assert result.infra is True
    assert "401" in result.error


def test_run_sam_dry_applies_deletes(tmp_path):
    """dry_run.deletes lets a deletion scenario carry an offline reference."""
    from conftest import make_scenario
    proj = tmp_path / "proj"
    (proj / "content" / "pages").mkdir(parents=True)
    (proj / "content" / "pages" / "about.mdx").write_text("---\ntitle: About\n---\n")
    scenario = make_scenario(dry_run={
        "text": "Removed the About page.",
        "tool_calls": [{"name": "delete_content_file", "args": {}}],
        "edits": {},
        "deletes": ["content/pages/about.mdx"],
    })
    rr = sam_runner.run_sam_dry(scenario, proj)
    assert not (proj / "content" / "pages" / "about.mdx").exists()
    assert rr.tool_calls[0]["name"] == "delete_content_file"


@pytest.mark.asyncio
async def test_run_sam_passes_system_and_init_flags(monkeypatch):
    import agent.site_editor as se

    seen = {}

    class RecordingEditor:
        def __init__(self, **kwargs):
            pass

        async def run(self, prompt, project_id, is_init=False, is_system=False):
            seen.update(prompt=prompt, is_init=is_init, is_system=is_system)
            return {"text": "ok", "tool_calls": []}

    monkeypatch.setattr(se, "AgentSiteEditor", RecordingEditor)

    await sam_runner.run_sam(
        make_scenario(is_system=True, prompt="build failed logs"),
        provider=None, model="m")
    assert (seen["is_system"], seen["is_init"]) == (True, False)

    await sam_runner.run_sam(
        make_scenario(is_init=True, prompt="build me a bakery site"),
        provider=None, model="m")
    assert (seen["is_system"], seen["is_init"]) == (False, True)

    await sam_runner.run_sam(make_scenario(), provider=None, model="m")
    assert (seen["is_system"], seen["is_init"]) == (False, False)


@pytest.mark.asyncio
async def test_provision_workspace_is_init_starts_empty(tmp_path):
    """Onboarding scenarios start from NOTHING: in production a wizard user has
    no site yet, and a pre-provisioned template would put a full CURRENT SITE
    STATE in Sam's prompt and tempt it to edit instead of create."""
    scenario = make_scenario(is_init=True)
    provider, project_dir = await sam_runner.provision_workspace(
        tmp_path / "scn", scenario)
    assert project_dir.exists()
    assert not (project_dir / "content").exists()
    # The git baseline still works so workspace_changes measures Sam's actions.
    assert sam_runner.workspace_changes(project_dir)["files"] == []


@pytest.mark.asyncio
async def test_run_sam_multi_turn_calls_editor_per_turn_with_shared_store(
        monkeypatch):
    """Each turn is one editor.run call with its own flags; all turns share one
    store carrying the conversation log (api core.py contract: inbound appended
    before the call, agent reply after); tool calls concatenate across turns."""
    from types import SimpleNamespace
    import agent.site_editor as se

    calls = []
    captured = {}

    class RecordingEditor:
        def __init__(self, **kwargs):
            captured["store"] = kwargs.get("store")
            captured["session_id"] = kwargs.get("session_id")

        async def run(self, prompt, project_id, is_init=False, is_system=False):
            log = await captured["store"].get_conversation_log(
                captured["session_id"])
            calls.append({"prompt": prompt, "is_init": is_init,
                          "is_system": is_system, "log_len": len(log)})
            n = len(calls)
            return {"text": f"reply-{n}",
                    "tool_calls": [SimpleNamespace(name=f"tool_{n}", args={})]}

    monkeypatch.setattr(se, "AgentSiteEditor", RecordingEditor)
    scenario = make_scenario(turns=[
        {"prompt": "change the tagline"},
        {"prompt": "publish"},
        {"prompt": "the build failed", "is_system": True},
    ])
    rr = await sam_runner.run_sam(scenario, provider=None, model="m")

    assert rr.error is None
    assert [c["is_system"] for c in calls] == [False, False, True]
    # the inbound message is appended BEFORE each call: 1, then 1+2, then 1+2+2
    assert [c["log_len"] for c in calls] == [1, 3, 5]
    log = await captured["store"].get_conversation_log(captured["session_id"])
    assert [e["role"] for e in log] == [
        "user", "agent", "user", "agent", "system", "agent"]
    assert [c["name"] for c in rr.tool_calls] == ["tool_1", "tool_2", "tool_3"]
    assert rr.text == "reply-3"
    assert [t["role"] for t in rr.transcript] == [
        "user", "agent", "user", "agent", "system", "agent"]


@pytest.mark.asyncio
async def test_multi_turn_publish_flow_through_real_editor(tmp_path, monkeypatch):
    """Two-turn confirmed-publish through the REAL AgentSiteEditor: turn 1 edits
    and opens a publish request (persisted in the harness store); turn 2's
    publish_changes finds the pending draft, and the second model call sees
    turn 1 in its history."""
    from agent.llm.types import LLMResult, Usage

    state = {"turn": 0}
    histories = []
    out = {}

    async def _run_turn(self, *, system_instruction, messages, tools,
                        force_thinking=False):
        tool_map = {t.__name__: t for t in tools}
        state["turn"] += 1
        histories.append(list(messages))
        if state["turn"] == 1:
            await tool_map["branch_and_edit_content"](
                branch_name="edit-tagline", file_path="content/settings.yaml",
                content="site:\n  name: My Business\n  tagline: \"Fresh bread\"\n")
            await tool_map["create_publish_request"](
                branch_name="edit-tagline", title="New tagline")
            return LLMResult(text="Done — say publish when you're ready!",
                             tool_calls=[], usage=Usage())
        out["publish"] = await tool_map["publish_changes"]()
        return LLMResult(text="Published!", tool_calls=[], usage=Usage())

    monkeypatch.setattr("agent.llm.LLMClient.run_turn", _run_turn)
    scenario = make_scenario(
        turns=[{"prompt": "Change the tagline to Fresh bread"},
               {"prompt": "publish"}],
        setup=[{"path": "content/settings.yaml",
                "content": "site:\n  name: My Business\n"}])
    provider, project_dir = await sam_runner.provision_workspace(
        tmp_path / "scn", scenario)
    rr = await sam_runner.run_sam(scenario, provider, "gemini-x")

    assert rr.error is None
    assert out["publish"].get("status") == "published"
    assert any("Change the tagline" in m["content"] for m in histories[1])
    assert (project_dir / "content" / "settings.yaml").read_text().count("Fresh bread") == 1


def test_run_sam_dry_builds_transcript_for_turns(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    scenario = make_scenario(
        turns=[{"prompt": "a"}, {"prompt": "b"}],
        dry_run={"text": "done", "tool_calls": [], "edits": {}})
    rr = sam_runner.run_sam_dry(scenario, proj)
    assert [t["role"] for t in rr.transcript] == ["user", "user", "agent"]
