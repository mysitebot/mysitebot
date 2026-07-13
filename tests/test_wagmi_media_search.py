"""WagmiMediaSearch maps wagmi.photos' OpenAI-compatible image API onto the
MediaSearch protocol. Network is mocked via an injected fake async client."""
import pytest

from agent.media_search import MediaResult, MediaSearch, WagmiMediaSearch


class _FakeImage:
    def __init__(self, url):
        self.url = url


class _FakeResponse:
    def __init__(self, url, shared_cache=None):
        self.data = [_FakeImage(url)]
        # openai-python surfaces out-of-schema response fields via model_extra.
        self.model_extra = {"shared_cache": shared_cache} if shared_cache else {}


class _FakeImages:
    def __init__(self, response):
        self._response = response
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.images = _FakeImages(response)


def test_is_a_media_search():
    wagmi = WagmiMediaSearch(api_key="k", client=_FakeClient(_FakeResponse("u")))
    assert isinstance(wagmi, MediaSearch)


@pytest.mark.asyncio
async def test_search_maps_generated_image_to_media_result():
    resp = _FakeResponse(
        "https://cdn.wagmi.photos/assets/pd12m-8f31/image.webp",
        shared_cache={"result": "hit", "similarity": 0.9312,
                      "source": "pd12m", "model_used": "flux-schnell"},
    )
    client = _FakeClient(resp)
    wagmi = WagmiMediaSearch(api_key="k", client=client)

    results = await wagmi.search("a corgi wearing sunglasses on a beach")

    assert client.images.calls == [{"prompt": "a corgi wearing sunglasses on a beach"}]
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, MediaResult)
    assert r.url == "https://cdn.wagmi.photos/assets/pd12m-8f31/image.webp"
    assert r.distance == 0.0  # generated for the query → "good" quality, no weak-match warning
    assert r.attribution["creator"] == "flux-schnell"
    assert r.attribution["source"] == "pd12m"
    assert r.attribution["license"] == "generated (wagmi.photos)"


@pytest.mark.asyncio
async def test_search_without_shared_cache_still_returns_url():
    client = _FakeClient(_FakeResponse("https://cdn.wagmi.photos/x.webp"))
    results = await WagmiMediaSearch(api_key="k", client=client).search("a mountain")
    assert len(results) == 1
    assert results[0].url == "https://cdn.wagmi.photos/x.webp"
    assert results[0].attribution["creator"] == "wagmi.photos"


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_usable_image():
    client = _FakeClient(_FakeResponse(url=None))
    results = await WagmiMediaSearch(api_key="k", client=client).search("q")
    assert results == []


@pytest.mark.asyncio
async def test_passes_model_when_configured():
    client = _FakeClient(_FakeResponse("u"))
    await WagmiMediaSearch(api_key="k", model="flux-schnell", client=client).search("q")
    assert client.images.calls[0] == {"prompt": "q", "model": "flux-schnell"}
