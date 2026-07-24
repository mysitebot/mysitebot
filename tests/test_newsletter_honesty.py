"""The newsletter form is functional: it POSTs to the site's shared form
endpoint (like the contact form) tagged as a newsletter signup, which emails
the owner that someone wants to subscribe. It must NOT fake success offline in
a way that lies, and must no longer show the old "unavailable" placeholder."""
import pytest

from tests.template_build import TEMPLATE, build_site

SOURCE = TEMPLATE / "src" / "components" / "sections" / "Newsletter.astro"


def test_component_source_is_wired_to_the_backend():
    source = SOURCE.read_text()
    # POSTs to the shared form endpoint, tagged as a newsletter signup.
    assert "mysitebot:form-endpoint" in source
    assert "form_type" in source and "newsletter" in source.lower()
    # The dead "unavailable" placeholder is gone.
    assert "isn't available on this site yet" not in source
    assert "data-unavailable-msg" not in source
    # Honest success + error affordances, announced to assistive tech.
    assert "data-newsletter-success" in source
    assert "data-newsletter-error" in source
    assert 'role="alert"' in source


@pytest.mark.slow
def test_rendered_form_has_no_unavailable_notice(tmp_path):
    site = tmp_path / "site"
    result = build_site(site, pages={
        "index.mdx": '---\ntitle: "Home"\npageLayout: "full"\n---\n'
                     '<Newsletter heading="Join us" />\n',
    })
    assert result.returncode == 0, result.stderr
    html = (site / "dist" / "index.html").read_text()
    assert "isn't available" not in html
    assert "data-newsletter-form" in html
