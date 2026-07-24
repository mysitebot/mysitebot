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


@pytest.mark.slow
def test_bloglist_section_renders_cards_on_a_page(tmp_path):
    site = tmp_path / "site"
    result = build_site(site, pages={
        "index.mdx": '---\ntitle: "Home"\npageLayout: "full"\n---\n'
                     '<BlogList heading="Latest news" limit={2} />\n',
    }, posts={
        "one.mdx": post_file("First Post", "2026-07-01", excerpt="About the first"),
        "two.mdx": post_file("Second Post", "2026-07-02"),
        "three.mdx": post_file("Third Post", "2026-07-03"),
    })
    assert result.returncode == 0, result.stderr
    html = (site / "dist" / "index.html").read_text()
    assert "Latest news" in html
    # limit=2, newest first
    assert "Third Post" in html and "Second Post" in html
    assert "First Post" not in html
    assert '/blog/three' in html


def _numbered_posts(count: int) -> dict[str, str]:
    return {
        f"post-{i:02d}.mdx": post_file(f"Post {i:02d}", f"2026-07-{i:02d}")
        for i in range(1, count + 1)
    }


@pytest.mark.slow
def test_no_blog_route_when_there_are_no_posts(tmp_path):
    site = tmp_path / "site"
    result = build_site(site)
    assert result.returncode == 0, result.stderr
    assert not (site / "dist" / "blog").exists()


@pytest.mark.slow
def test_nine_posts_fit_on_one_page(tmp_path):
    site = tmp_path / "site"
    build_site(site, posts=_numbered_posts(9))
    assert (site / "dist" / "blog" / "index.html").exists()
    assert not (site / "dist" / "blog" / "2").exists()


@pytest.mark.slow
def test_tenth_post_creates_a_second_page(tmp_path):
    site = tmp_path / "site"
    build_site(site, posts=_numbered_posts(10))
    first = (site / "dist" / "blog" / "index.html").read_text()
    second = (site / "dist" / "blog" / "2" / "index.html").read_text()
    # Newest first: Post 10 leads page 1, the oldest falls to page 2.
    assert "Post 10" in first
    assert "Post 01" in second and "Post 01" not in first
    # Proves the extracted Pagination component rendered end-to-end.
    assert "Newer posts" in second


@pytest.mark.slow
def test_tag_page_lists_only_its_posts(tmp_path):
    site = tmp_path / "site"
    result = build_site(site, posts={
        "a.mdx": post_file("Pasta Night", "2026-07-01", tags=["Recipes"]),
        "b.mdx": post_file("Opening Hours", "2026-07-02", tags=["News"]),
    })
    assert result.returncode == 0, result.stderr
    html = (site / "dist" / "blog" / "tag" / "recipes" / "index.html").read_text()
    assert "Pasta Night" in html
    assert "Opening Hours" not in html


@pytest.mark.slow
def test_tags_colliding_after_slugification_share_one_page(tmp_path):
    site = tmp_path / "site"
    build_site(site, posts={
        "a.mdx": post_file("Older", "2026-07-01", tags=["web design"]),
        "b.mdx": post_file("Newer", "2026-07-02", tags=["Web Design"]),
    })
    html = (site / "dist" / "blog" / "tag" / "web-design" / "index.html").read_text()
    assert "Older" in html and "Newer" in html
    # Label comes from the newest post's spelling.
    assert "Web Design" in html


@pytest.mark.slow
def test_no_tag_routes_without_tags(tmp_path):
    site = tmp_path / "site"
    build_site(site, posts={"a.mdx": post_file("Untagged", "2026-07-01")})
    assert not (site / "dist" / "blog" / "tag").exists()
