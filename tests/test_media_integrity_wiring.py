"""End-to-end wiring of the media handle + integrity guard through the two
tools that touch it: search_media_library (issues handles) and
branch_and_edit_content (substitutes them, then runs the backstop + optional
HEAD-check). Real AgentSiteEditor over a real LocalGitProvider workspace,
storeless CLI mode (active_provider_id 'local_project' maps onto the root)."""
import pytest

from agent.providers.git.base import LocalGitProvider
from agent.site_editor import AgentSiteEditor, TurnContext
from agent.toolbox import build_tools
from agent.media_search import MediaResult

REAL = "https://cdn.wagmi.photos/img/f3a16e.jpeg"
MANGLED = "https://cdn.wagmi.photos/img/f3f16e.jpeg"


class FakeMedia:
    def __init__(self, url=REAL):
        self.url = url
        self.queries = []

    async def search(self, query):
        self.queries.append(query)
        return [MediaResult(url=self.url, tags=["cafe"],
                            attribution={"creator": "x", "license": "CC0"})]


def _seed(tmp_path):
    ws = tmp_path / "ws"
    (ws / "content" / "pages").mkdir(parents=True)
    (ws / "content" / "pages" / "index.mdx").write_text(
        '---\ntitle: Home\n---\n<Hero heading="Hi" />\n')
    return ws


def _editor(ws, media=None, head=None):
    return AgentSiteEditor(
        git_provider=LocalGitProvider(workspace_root=str(ws)),
        session_id="t", api_key="k", media_search=media, media_head_check=head)


def _tools(editor, ctx):
    return {fn.__name__: fn for fn in build_tools(editor, ctx)}


def _ctx():
    return TurnContext(active_project_id="local_project",
                       active_provider_id="local_project")


async def _edit(tools, content, path="content/pages/index.mdx"):
    return await tools["branch_and_edit_content"]("draft", path, content)


@pytest.mark.asyncio
async def test_search_returns_handle_not_raw_url(tmp_path):
    media = FakeMedia()
    ed = _editor(_seed(tmp_path), media)
    ctx = _ctx()
    tools = _tools(ed, ctx)
    out = await tools["search_media_library"]("cafe")
    assert "media://0" in out
    assert REAL not in out  # the raw UUID URL never reaches the model
    assert ctx.media_handles["media://0"] == REAL


@pytest.mark.asyncio
async def test_edit_substitutes_handle_to_real_url(tmp_path):
    ed = _editor(_seed(tmp_path), FakeMedia())
    ctx = _ctx()
    tools = _tools(ed, ctx)
    await tools["search_media_library"]("cafe")
    content = ('---\ntitle: Home\n---\n'
               '<Hero heading="Hi" image={{ src: "media://0", alt: "cafe" }} />\n')
    res = await _edit(tools, content)
    assert "error" not in res, res
    saved = await ed.git_provider.read_file("local_project", "content/pages/index.mdx")
    assert REAL in saved
    assert "media://0" not in saved  # handle resolved server-side


@pytest.mark.asyncio
async def test_edit_rejects_invented_handle(tmp_path):
    ed = _editor(_seed(tmp_path), FakeMedia())
    tools = _tools(ed, _ctx())
    # no search this turn -> media://3 maps to nothing
    content = '---\ntitle: Home\n---\n<Hero image={{ src: "media://3" }} />\n'
    res = await _edit(tools, content)
    assert "error" in res
    assert "media://3" in res["error"]


@pytest.mark.asyncio
async def test_backstop_rejects_mangled_media_url(tmp_path):
    ed = _editor(_seed(tmp_path), FakeMedia())
    ctx = _ctx()
    tools = _tools(ed, ctx)
    await tools["search_media_library"]("cafe")  # guards cdn.wagmi.photos this turn
    content = f'---\ntitle: Home\n---\n<Hero image={{{{ src: "{MANGLED}" }}}} />\n'
    res = await _edit(tools, content)
    assert "error" in res
    assert MANGLED in res["error"]


@pytest.mark.asyncio
async def test_head_check_rejects_dead_external_image(tmp_path):
    async def head(url):
        return 404

    ed = _editor(_seed(tmp_path), FakeMedia(), head=head)
    tools = _tools(ed, _ctx())
    dead = "https://example.com/missing.jpg"
    content = f'---\ntitle: Home\n---\n<Hero image={{{{ src: "{dead}" }}}} />\n'
    res = await _edit(tools, content)
    assert "error" in res
    assert dead in res["error"]


@pytest.mark.asyncio
async def test_head_check_skipped_when_unconfigured(tmp_path):
    # No checker injected (eval / offline): a syntactically valid edit with an
    # external image still commits — the HEAD-check must never run a network
    # call by default.
    ed = _editor(_seed(tmp_path), FakeMedia(), head=None)
    tools = _tools(ed, _ctx())
    content = ('---\ntitle: Home\n---\n'
               '<Hero image={{ src: "https://example.com/live.jpg" }} />\n')
    res = await _edit(tools, content)
    assert "error" not in res, res
