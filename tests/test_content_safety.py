from agent.content_safety import is_safe_content_path, check_content_for_cookies


def test_rejects_path_traversal():
    assert is_safe_content_path("content/pages/index.mdx") is True
    assert is_safe_content_path("../etc/passwd") is False
    assert is_safe_content_path("") is False


def test_rejects_absolute_paths():
    # os.path.join(project_dir, file_path) discards project_dir entirely for an
    # absolute file_path, so absolute paths must never validate.
    assert is_safe_content_path("/etc/passwd") is False
    assert is_safe_content_path("/content/pages/index.mdx") is False


def test_rejects_absolute_path_even_inside_a_cwd_content_dir(tmp_path, monkeypatch):
    # The old implementation resolved against the process CWD, so an absolute
    # path pointing INSIDE <cwd>/content validated — yet it escapes every
    # per-project workspace when joined. Must be rejected lexically.
    monkeypatch.chdir(tmp_path)
    assert is_safe_content_path(str(tmp_path / "content" / "x.mdx")) is False


def test_rejects_all_dotdot_traversal_forms():
    assert is_safe_content_path("content/../package.json") is False
    assert is_safe_content_path("content/../../etc/passwd") is False
    # Even a '..' that stays inside content/ is rejected: the raw (unnormalized)
    # path is what gets joined downstream.
    assert is_safe_content_path("content/pages/../settings.yaml") is False


def test_accepts_normal_content_paths():
    assert is_safe_content_path("content/settings.yaml") is True
    assert is_safe_content_path("./content/pages/about.mdx") is True
    # Sibling directory that merely shares the prefix string is not content/.
    assert is_safe_content_path("contentx/pages/about.mdx") is False


def test_flags_programmatic_cookie_access():
    assert check_content_for_cookies("document.cookie = 'x'") is not None
    assert check_content_for_cookies("We do not use cookies.") is None
