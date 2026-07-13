import asyncio

from agent.media_search import MediaSearch, render_results
from stub_media_search import StubMediaSearch


def test_stub_satisfies_protocol_and_returns_good_matches():
    stub = StubMediaSearch()
    assert isinstance(stub, MediaSearch)  # runtime_checkable Protocol
    results = asyncio.run(stub.search("modern bakery storefront"))
    assert results
    # all "good" quality (distance < WEAK_MATCH_DISTANCE) so render_results does
    # NOT emit the "no close matches" warning that steers Sam off the image.
    assert all(r.distance < 0.6 for r in results)
    rendered = render_results(results)
    assert "WARNING" not in rendered
    assert "storage.googleapis.com" in rendered


def test_stub_is_deterministic_and_query_derived():
    stub = StubMediaSearch()
    a = asyncio.run(stub.search("misty mountain"))
    b = asyncio.run(stub.search("misty mountain"))
    assert [r.url for r in a] == [r.url for r in b]
    assert "misty-mountain" in a[0].url
