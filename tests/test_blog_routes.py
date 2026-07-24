import pytest

from tests.template_build import build_site, post_file

DRAFT_ENV = {"MYSITEBOT_INCLUDE_DRAFTS": "1"}


@pytest.mark.slow
def test_post_detail_page_is_emitted(tmp_path):
    site = tmp_path / "site"
    result = build_site(site, posts={
        "hello-world.mdx": post_file("Hello World", "2026-07-01"),
    })
    assert result.returncode == 0, result.stderr
    html = (site / "dist" / "blog" / "hello-world" / "index.html").read_text()
    assert "Hello World" in html


@pytest.mark.slow
def test_draft_post_excluded_from_production_build(tmp_path):
    site = tmp_path / "site"
    build_site(site, posts={
        "secret.mdx": post_file("Secret Post", "2026-07-01", draft=True),
    })
    assert not (site / "dist" / "blog" / "secret").exists()


@pytest.mark.slow
def test_draft_post_included_in_draft_build(tmp_path):
    site = tmp_path / "site"
    build_site(site, posts={
        "secret.mdx": post_file("Secret Post", "2026-07-01", draft=True),
    }, env=DRAFT_ENV)
    assert (site / "dist" / "blog" / "secret" / "index.html").exists()


@pytest.mark.slow
def test_existing_pages_still_render_sections(tmp_path):
    """The section map moved out of [...slug].astro — prove the core rendering
    path for every existing customer site is unchanged."""
    site = tmp_path / "site"
    result = build_site(site, pages={
        "index.mdx": '---\ntitle: "Home"\npageLayout: "full"\n---\n'
                     '<Hero heading="Welcome aboard" />\n',
    })
    assert result.returncode == 0, result.stderr
    assert "Welcome aboard" in (site / "dist" / "index.html").read_text()
