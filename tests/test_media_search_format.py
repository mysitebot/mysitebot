from agent.media_search import MediaResult, render_results


def test_good_match_lists_title_and_quality():
    out = render_results([MediaResult(
        url="https://x/desktop.webp", tags=["cafe", "cozy"], distance=0.2,
        attribution={"creator": "Jane", "license": "CC0", "title": "Cozy cafe"},
        thumbnail="https://x/thumb.webp",
    )])
    assert "TOP SEMANTIC MATCHES" in out
    assert "Title: Cozy cafe" in out
    assert "Match quality: good" in out


def test_all_weak_matches_warn():
    out = render_results([MediaResult(url="https://x/desktop.webp", tags=["x"], distance=0.9)])
    assert "WARNING" in out
    assert "Match quality: weak" in out


def test_empty_results_message():
    assert "media library is currently empty" in render_results([])
