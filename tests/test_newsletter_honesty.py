"""The newsletter form has no backend. Until it does, it must say so rather
than telling visitors they were subscribed."""
import pytest

from tests.template_build import TEMPLATE, build_site

SOURCE = TEMPLATE / "src" / "components" / "sections" / "Newsletter.astro"
UNAVAILABLE = "Newsletter signup isn't available on this site yet."


def test_component_source_makes_no_subscription_claim():
    source = SOURCE.read_text()
    assert "subscribed" not in source.lower()
    assert "data-success-msg" not in source


@pytest.mark.slow
def test_rendered_form_shows_the_unavailable_message(tmp_path):
    site = tmp_path / "site"
    result = build_site(site, pages={
        "index.mdx": '---\ntitle: "Home"\npageLayout: "full"\n---\n'
                     '<Newsletter heading="Join us" />\n',
    })
    assert result.returncode == 0, result.stderr
    html = (site / "dist" / "index.html").read_text()
    assert UNAVAILABLE in html
    assert "subscribed" not in html.lower()
