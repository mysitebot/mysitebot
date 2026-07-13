"""Shared fixtures for the site_editor test files: workspace seeding, editor
construction over the standard LLM seam (agent.llm.testing.patch_run_turn),
and a minimal in-memory store for tests that need SaaS (publish-capable) mode."""
import pytest

from agent.providers.git.base import LocalGitProvider

# A minimal, valid site: homepage + settings (project id 'local_project' maps
# straight onto the workspace root, so no template copy is needed).
DEFAULT_WORKSPACE_FILES = {
    "content/pages/index.mdx": "---\ntitle: Home\n---\n",
    "content/settings.yaml": "site:\n  name: My Business\n",
}


class FakeEditorStore:
    """In-memory EditorStore: just enough for the editor's five duck-typed
    methods. Passing one switches the editor into SaaS (publish-capable) mode."""

    def __init__(self):
        self.projects = {}
        self.sessions = {}
        self.logs = {}

    async def get_project(self, project_id):
        return self.projects.get(project_id)

    async def save_project(self, project_id, data):
        self.projects[project_id] = data

    async def get_user_session(self, session_id):
        return self.sessions.get(session_id)

    async def get_conversation_log(self, session_id):
        return list(self.logs.get(session_id, []))

    async def is_locked(self, project_id):
        return False


@pytest.fixture
def fake_store():
    return FakeEditorStore()


@pytest.fixture
def seed_workspace(tmp_path):
    """seed_workspace(files=None) -> workspace path. `files` maps relative
    paths to content; defaults to DEFAULT_WORKSPACE_FILES."""
    def _seed(files=None):
        ws = tmp_path / "workspace"
        for rel, content in (files or DEFAULT_WORKSPACE_FILES).items():
            target = ws / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        return ws
    return _seed


@pytest.fixture
def make_editor(monkeypatch):
    """make_editor(ws, driver, **editor_kwargs) -> AgentSiteEditor over a real
    LocalGitProvider with LLMClient.run_turn replaced by `driver` (the standard
    patch_run_turn seam — a driver may declare `force_thinking` to observe
    escalation)."""
    def _make(ws, driver, **editor_kwargs):
        from agent.llm.testing import patch_run_turn
        from agent.site_editor import AgentSiteEditor

        patch_run_turn(monkeypatch, driver)
        provider = LocalGitProvider(workspace_root=str(ws))
        editor_kwargs.setdefault("api_key", "test-key")
        return AgentSiteEditor(git_provider=provider, **editor_kwargs)
    return _make
