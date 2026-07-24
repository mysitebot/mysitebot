"""Unit tests for the media-URL handle + integrity guard (agent.media_integrity).

Sam retypes search_media_library URLs into MDX and can slip a hex char (live
2026-07-20: committed `…f3f16e.jpeg` 404s; the API served `…f3a16e.jpeg`). The
handle scheme keeps the real UUID out of the model's hands; the backstop and
HEAD-check catch a model that pastes a raw URL anyway.
"""
import pytest

from agent.media_integrity import (
    substitute_media_handles,
    find_unvetted_media_urls,
    hosts_of,
    new_external_image_urls,
    dead_image_urls,
)

REAL = "https://cdn.wagmi.photos/img/f3a16e.jpeg"
MANGLED = "https://cdn.wagmi.photos/img/f3f16e.jpeg"


# --- (c-a) handle substitution -------------------------------------------

def test_substitute_replaces_known_handles():
    content = '<Hero image={{ src: "media://0" }} />\n![logo](media://1)'
    handle_map = {"media://0": REAL, "media://1": "https://cdn.wagmi.photos/b.png"}
    out, unknown = substitute_media_handles(content, handle_map)
    assert REAL in out
    assert "https://cdn.wagmi.photos/b.png" in out
    assert "media://" not in out
    assert unknown == []


def test_substitute_reports_unknown_handles_and_leaves_them():
    content = 'src="media://5"'
    out, unknown = substitute_media_handles(content, {"media://0": REAL})
    assert unknown == ["media://5"]
    assert out == content  # an invented handle is left untouched for the caller to reject


def test_substitute_noop_without_handles():
    content = '<Hero heading="Hi" />'
    out, unknown = substitute_media_handles(content, {"media://0": REAL})
    assert out == content
    assert unknown == []


# --- (c-b) backstop: media-host URL not vetted this turn ------------------

def test_backstop_flags_mangled_media_url():
    offenders = find_unvetted_media_urls(
        new_content=f'<Hero image={{{{ src: "{MANGLED}" }}}} />',
        prior_content="",
        allowed_urls={REAL},
        guarded_hosts={"cdn.wagmi.photos"},
    )
    assert offenders == [MANGLED]


def test_backstop_allows_recorded_and_prior_urls():
    prior_url = "https://cdn.wagmi.photos/img/old.jpeg"
    offenders = find_unvetted_media_urls(
        new_content=f'a "{REAL}" b "{prior_url}"',
        prior_content=f'src="{prior_url}"',
        allowed_urls={REAL},
        guarded_hosts={"cdn.wagmi.photos"},
    )
    assert offenders == []


def test_backstop_ignores_unguarded_hosts():
    offenders = find_unvetted_media_urls(
        new_content='src="https://example.com/pic.jpg"',
        prior_content="",
        allowed_urls=set(),
        guarded_hosts={"cdn.wagmi.photos"},
    )
    assert offenders == []


def test_backstop_dedupes_and_reports_each_once():
    offenders = find_unvetted_media_urls(
        new_content=f'"{MANGLED}" and again "{MANGLED}"',
        prior_content="",
        allowed_urls={REAL},
        guarded_hosts={"cdn.wagmi.photos"},
    )
    assert offenders == [MANGLED]


# --- helpers --------------------------------------------------------------

def test_hosts_of_extracts_netlocs():
    assert hosts_of({"https://a.com/x", "http://b.io:8080/y"}) == {"a.com", "b.io:8080"}


def test_hosts_of_empty():
    assert hosts_of(set()) == set()


# --- (c-c) new external image URLs to HEAD-check --------------------------

def test_new_external_image_urls_only_new_images_on_other_hosts():
    prior = 'src="https://ex.com/old.png"'
    new = (
        'src="https://ex.com/old.png" '          # unchanged — not "new"
        'src="https://ex.com/new.jpg" '          # new image on external host -> check
        'href="https://ex.com/about-page" '      # not an image
        'src="https://cdn.wagmi.photos/x.jpeg"'  # excluded (media) host
    )
    urls = new_external_image_urls(new, prior, exclude_hosts={"cdn.wagmi.photos"})
    assert urls == ["https://ex.com/new.jpg"]


@pytest.mark.asyncio
async def test_dead_image_urls_returns_only_definitive_404():
    statuses = {
        "https://x/a.jpg": 404,   # dead
        "https://x/b.jpg": 200,   # live
        "https://x/c.jpg": None,  # indeterminate (timeout/network) -> fail open, keep
    }

    async def head(url):
        return statuses[url]

    dead = await dead_image_urls(list(statuses), head)
    assert dead == ["https://x/a.jpg"]


@pytest.mark.asyncio
async def test_dead_image_urls_fails_open_on_exception():
    async def head(url):
        raise RuntimeError("network down")

    dead = await dead_image_urls(["https://x/a.jpg"], head)
    assert dead == []  # never reject when liveness can't be determined
