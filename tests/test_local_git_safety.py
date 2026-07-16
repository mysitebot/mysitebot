import os

import pytest

from agent.providers.git.base import LocalGitProvider


@pytest.mark.asyncio
async def test_create_project_rejects_path_traversal(tmp_path):
    """A traversing name must not write outside the workspace root."""
    workspace = tmp_path / "workspace"
    git = LocalGitProvider(workspace_root=str(workspace))
    res = await git.create_project("../../pwned", "astro-basic")
    # The escape target above the workspace must not exist.
    assert not (tmp_path / "pwned").exists()
    assert not (tmp_path.parent / "pwned").exists()
    # The project lives inside the workspace, with a contained folder.
    real_root = os.path.realpath(str(workspace))
    real_dir = os.path.realpath(res["web_url"].replace("local://", ""))
    assert real_dir == real_root or real_dir.startswith(real_root + os.sep)


@pytest.mark.asyncio
async def test_availability_answer_matches_created_folder(tmp_path):
    """check_project_availability (provider-interface default) and
    create_project share ONE sanitizer, so the name reported available is
    exactly the folder/id create_project will use — the two used to run
    different cleaning rules and could disagree."""
    workspace = tmp_path / "workspace"
    git = LocalGitProvider(workspace_root=str(workspace))

    answer = await git.check_project_availability("My Bakery.Site!")
    assert answer["available"] is True
    assert answer["name"] == "my-bakery.site"

    proj = await git.create_project("My Bakery.Site!", "astro-basic")
    assert proj["project_id"] == f"local_{answer['name']}"
    assert (workspace / answer["name"]).is_dir()


@pytest.mark.asyncio
async def test_create_project_refuses_to_overwrite_existing(tmp_path):
    """Re-creating an existing project must not silently wipe it."""
    workspace = tmp_path / "workspace"
    git = LocalGitProvider(workspace_root=str(workspace))
    await git.create_project("blog", "astro-basic")
    marker = workspace / "blog" / "content" / "MINE.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("user data")

    with pytest.raises(ValueError):
        await git.create_project("blog", "astro-basic")

    # User content survived — no destructive rmtree happened.
    assert marker.exists()
    assert marker.read_text() == "user data"


@pytest.mark.asyncio
async def test_delete_file_removes_content_file(tmp_path):
    workspace = tmp_path / "workspace"
    git = LocalGitProvider(workspace_root=str(workspace))
    target = workspace / "content" / "pages" / "about.mdx"
    target.parent.mkdir(parents=True)
    target.write_text("---\ntitle: About\n---\n")

    res = await git.delete_file(
        "local_project", "remove-about", "content/pages/about.mdx", "Remove about")

    assert not target.exists()
    assert res["status"] == "deleted_locally"
    assert res["file"] == "content/pages/about.mdx"


@pytest.mark.asyncio
async def test_delete_file_rejects_paths_outside_content(tmp_path):
    """Deletion is bounded to content/ exactly like commit_file, traversal included."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    victim = workspace / "package.json"
    victim.write_text("{}")
    git = LocalGitProvider(workspace_root=str(workspace))

    for path in ("package.json", "content/../package.json", "src/components/Hero.astro"):
        with pytest.raises(ValueError):
            await git.delete_file("local_project", "b", path, "m")
    assert victim.exists()


@pytest.mark.asyncio
async def test_delete_file_missing_file_raises(tmp_path):
    workspace = tmp_path / "workspace"
    git = LocalGitProvider(workspace_root=str(workspace))
    with pytest.raises(FileNotFoundError):
        await git.delete_file(
            "local_project", "b", "content/pages/ghost.mdx", "m")


@pytest.mark.asyncio
async def test_commit_file_rejects_absolute_path_even_inside_a_content_dir(tmp_path, monkeypatch):
    """An absolute path under <cwd>/content passed the old CWD-relative check yet
    os.path.join discards project_dir for absolute paths — the file would land
    OUTSIDE any project workspace. Must be rejected before anything is written."""
    monkeypatch.chdir(tmp_path)
    workspace = tmp_path / "workspace"
    git = LocalGitProvider(workspace_root=str(workspace))
    evil = tmp_path / "content" / "evil.mdx"
    with pytest.raises(ValueError):
        await git.commit_file("local_project", "b", str(evil), "---\ntitle: x\n---\n", "m")
    assert not evil.exists()


def test_get_path_raises_on_escape(tmp_path):
    """_get_path is the single join point for reads/writes/deletes — it must
    assert containment (mirroring _contained_dir) so no path resolves outside
    the project workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    git = LocalGitProvider(workspace_root=str(workspace))
    for path in ("/etc/passwd", "../../etc/passwd", "content/../../outside.txt"):
        with pytest.raises(ValueError):
            git._get_path("local_project", path)
        with pytest.raises(ValueError):
            git._get_path("local_myproj", path)
    # Contained paths still resolve.
    inside = git._get_path("local_project", "content/pages/index.mdx")
    assert inside.startswith(str(workspace))


@pytest.mark.asyncio
async def test_delete_project_cannot_escape_workspace(tmp_path):
    """A traversing project id must not rmtree a directory outside the workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    sentinel = tmp_path / "keep_me"
    sentinel.mkdir()
    (sentinel / "important.txt").write_text("do not delete")

    git = LocalGitProvider(workspace_root=str(workspace))
    # Sanitized to a basename inside the workspace (which doesn't exist) -> no-op.
    # Absent counts as deleted (F04, matching F03's fail-closed callers) — the
    # traversal is still blocked (the sentinel survives outside the workspace);
    # only the return value's semantic changed, not the safety guarantee.
    result = await git.delete_project("local_../../keep_me")
    assert result is True
    assert (sentinel / "important.txt").exists()


@pytest.mark.asyncio
async def test_delete_project_absent_dir_counts_as_deleted(tmp_path):
    provider = LocalGitProvider(workspace_root=str(tmp_path))
    assert await provider.delete_project("never_created") is True
