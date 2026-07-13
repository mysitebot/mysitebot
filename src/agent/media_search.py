from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class MediaResult:
    url: str
    tags: list[str] = field(default_factory=list)
    distance: float = 0.0
    attribution: dict = field(default_factory=dict)  # creator, license, title
    thumbnail: str | None = None


@runtime_checkable
class MediaSearch(Protocol):
    async def search(self, query: str) -> list[MediaResult]:
        """Return up to ~5 semantically-ranked CC0 media results for the query."""
        ...


# Cosine distance: below this the tags genuinely relate to the query; above it
# the result is just the nearest of an unrelated library.
WEAK_MATCH_DISTANCE = 0.6


def render_results(results: list[MediaResult]) -> str:
    """Format ranked results into the agent-facing tool result (all LLM prompt-shaping
    lives here, in the agent — not in the media backend)."""
    if not results:
        return "The media library is currently empty. Please notify the administrator to ingest images."

    formatted = []
    for res in results:
        attribution = res.attribution or {}
        quality = "weak" if res.distance > WEAK_MATCH_DISTANCE else "good"
        lines = [
            f"URL: {res.url}",
            f"Tags: {', '.join(res.tags)}",
            f"Match quality: {quality}",
            f"Attribution: {attribution.get('creator', 'CC0')} ({attribution.get('license', 'CC0')})",
        ]
        if attribution.get("title"):
            lines.insert(1, f"Title: {attribution['title']}")
        if res.thumbnail:
            lines.append(f"Thumbnail: {res.thumbnail}")
        formatted.append("\n".join(lines))

    guidance = (
        "TOP SEMANTIC MATCHES (judge by the tags — pick one ONLY if it genuinely fits "
        "the page and the site's style/audience):\n"
    )
    footer = (
        "\nIf none of these fit, search again with a different descriptive query "
        "(e.g. add the business type or mood), or leave the existing image in place "
        "rather than using a mismatched one."
    )
    if all(r.distance > WEAK_MATCH_DISTANCE for r in results):
        guidance = (
            "WARNING: no close matches found for this query — all results below are weak. "
            "Try a different query before settling for one of these:\n"
        )
    return guidance + "\n---\n".join(formatted) + footer


class WagmiMediaSearch:
    """MediaSearch backed by wagmi.photos' OpenAI-compatible image API (BYO key).

    Calls `images.generate(prompt=query)`; wagmi returns the closest cached image
    (or generates one) in OpenAI shape plus a `shared_cache` block. Because the
    image is produced FOR the query it inherently fits, so distance is 0.0. All
    prompt-shaping of results stays in `render_results` above — this class only
    adapts the transport.
    """

    DEFAULT_BASE_URL = "https://api.wagmi.photos/v1"

    def __init__(self, api_key: str, *, base_url: str | None = None,
                 model: str | None = None, client=None):
        self._model = model
        if client is not None:
            self._client = client
        else:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=api_key, base_url=base_url or self.DEFAULT_BASE_URL
            )

    async def search(self, query: str) -> list[MediaResult]:
        kwargs: dict = {"prompt": query}
        if self._model:
            kwargs["model"] = self._model
        resp = await self._client.images.generate(**kwargs)
        data = getattr(resp, "data", None) or []
        if not data or not getattr(data[0], "url", None):
            return []
        cache = _response_extra(resp, "shared_cache") or {}
        attribution = {
            "creator": cache.get("model_used") or "wagmi.photos",
            "license": "generated (wagmi.photos)",
            "title": query,
        }
        if cache.get("source"):
            attribution["source"] = cache["source"]
        return [MediaResult(url=data[0].url, tags=[], distance=0.0, attribution=attribution)]


def _response_extra(resp, key):
    """Read an out-of-schema response field (openai-python exposes these via model_extra)."""
    extra = getattr(resp, "model_extra", None)
    if isinstance(extra, dict) and key in extra:
        return extra[key]
    return getattr(resp, key, None)
