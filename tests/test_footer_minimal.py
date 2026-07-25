"""Footer's two conditional rendering branches (added mapping websight_0396).

1. `hasUpperContent` — when a page supplies no brand/columns/newsletter content,
   the whole upper block is dropped and the footer collapses to a copyright bar
   (py-6, no top border) instead of a py-16 block.
2. `barJustifyClass` — the bottom bar spreads copyright and CTA apart by default,
   but collapses them into one aligned group for align=center/right.

The template ships no JS test runner on purpose, so a real `npm run build` is the
seam (see tests/template_build.py).
"""
import re

import pytest

from tests.template_build import TEMPLATE, build_site

SOURCE = TEMPLATE / "src" / "components" / "sections" / "Footer.astro"

# The page-level footer must be suppressed or settings.yaml's automatic footer
# renders alongside ours and every assertion below matches the wrong element.
PAGE = '---\ntitle: "Home"\npageLayout: "full"\nhideFooter: true\n---\n{body}\n'


def build_footer(tmp_path, body: str) -> str:
    """Builds a one-page site whose only footer is `body`, returns that <footer>."""
    site = tmp_path / "site"
    result = build_site(site, pages={"index.mdx": PAGE.format(body=body)})
    assert result.returncode == 0, result.stderr
    html = (site / "dist" / "index.html").read_text()
    match = re.search(r"<footer\b.*?</footer>", html, re.S)
    assert match, f"no <footer> in built page:\n{html[:2000]}"
    return match.group(0)


def test_source_gates_the_upper_block_and_bar_alignment():
    source = SOURCE.read_text()
    assert "hasUpperContent" in source
    assert "barJustifyClass" in source


@pytest.mark.slow
def test_content_bearing_footer_keeps_the_upper_block(tmp_path):
    footer = build_footer(tmp_path, '<Footer siteName="Acme" copyright="© Acme" />')
    assert "lg:grid-cols-4" in footer, "upper block should render"
    assert "border-t" in footer, "bottom bar keeps its divider under content"
    assert "py-16" in footer
    assert "Acme" in footer


@pytest.mark.slow
def test_minimal_footer_collapses_to_a_copyright_bar(tmp_path):
    # description carries a non-empty default, so a truly minimal footer has to
    # blank it explicitly -- see test_default_description_defeats_collapse.
    footer = build_footer(
        tmp_path, '<Footer copyright="© Acme" description="" />')
    assert "lg:grid-cols-4" not in footer, "upper block should be dropped"
    assert "border-t" not in footer, "no divider when there is nothing above it"
    assert "py-6" in footer and "py-16" not in footer
    assert "© Acme" in footer


@pytest.mark.slow
def test_default_align_spreads_the_bottom_bar(tmp_path):
    footer = build_footer(
        tmp_path,
        '<Footer copyright="© Acme" description="" '
        'action={{ label: "Contact", href: "/contact" }} />')
    assert "justify-between" in footer


@pytest.mark.slow
@pytest.mark.parametrize("align,expected", [
    ("center", "justify-center"),
    ("right", "justify-end"),
])
def test_aligned_bottom_bar_groups_instead_of_spreading(tmp_path, align, expected):
    footer = build_footer(
        tmp_path,
        f'<Footer copyright="© Acme" description="" align="{align}" '
        'action={{ label: "Contact", href: "/contact" }} />')
    assert expected in footer
    assert "justify-between" not in footer


@pytest.mark.slow
def test_default_description_defeats_collapse(tmp_path):
    """`description` defaults to a marketing sentence and is one of the terms in
    `hasUpperContent`, so <Footer /> alone can never reach the collapsed branch --
    it renders the upper block plus boilerplate the page never asked for."""
    footer = build_footer(tmp_path, '<Footer copyright="© Acme" />')
    assert "Providing high-quality care" in footer
    assert "lg:grid-cols-4" in footer
