import pytest

from tests.template_build import build_site, post_file


@pytest.mark.slow
def test_valid_post_builds(tmp_path):
    site = tmp_path / "site"
    result = build_site(site, posts={
        "hello-world.mdx": post_file("Hello World", "2026-07-01"),
    })
    assert result.returncode == 0, result.stderr
    assert (site / "src" / "content" / "posts" / "hello-world.mdx").exists()


@pytest.mark.slow
def test_blogless_site_builds(tmp_path):
    result = build_site(tmp_path / "site")
    assert result.returncode == 0, result.stderr


@pytest.mark.slow
def test_post_without_date_fails_the_build(tmp_path):
    result = build_site(tmp_path / "site", posts={
        "broken.mdx": '---\ntitle: "Broken"\n---\n\nNo date.\n',
    })
    assert result.returncode != 0
    assert "date" in (result.stdout + result.stderr)


@pytest.mark.slow
def test_post_title_rejects_tracking_code(tmp_path):
    result = build_site(tmp_path / "site", posts={
        "sneaky.mdx": post_file("googletagmanager", "2026-07-01"),
    })
    assert result.returncode != 0
    assert "Privacy Constraint Violated" in (result.stdout + result.stderr)
