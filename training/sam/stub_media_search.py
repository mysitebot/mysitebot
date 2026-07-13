"""Deterministic, dependency-free MediaSearch stub for the Sam eval harness.

The live AgentSiteEditor needs a real MediaSearch (Postgres + embeddings + GCS).
The eval harness only needs the agent's `search_media_library` tool to return
realistic, well-formed library hits so image scenarios are winnable offline —
with no external service. Results are deterministic per query and carry "good"
match quality (distance < media_search.WEAK_MATCH_DISTANCE) so render_results
does not steer Sam away from using an image.
"""
import re

from agent.media_search import MediaResult

_BUCKET = "mysitebot-media-stub"


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "image"


class StubMediaSearch:
    """In-memory MediaSearch (implements the agent.media_search.MediaSearch
    Protocol) returning 3 deterministic CC0-style hits for any query."""

    async def search(self, query: str) -> list[MediaResult]:
        slug = _slugify(query)
        terms = [t for t in re.split(r"[^a-z0-9]+", query.lower()) if t][:5] or ["image"]
        results = []
        for i in range(3):
            name = f"{slug}-{i + 1}"
            results.append(MediaResult(
                url=f"https://storage.googleapis.com/{_BUCKET}/media/{name}/full.webp",
                thumbnail=f"https://storage.googleapis.com/{_BUCKET}/media/{name}/thumb.webp",
                tags=terms + ["stub", "cc0"],
                distance=0.10 + 0.05 * i,  # 0.10 / 0.15 / 0.20 — all "good" (< 0.6)
                attribution={"creator": "Eval Stub Library", "license": "CC0",
                             "title": f"{query.strip().title()} ({i + 1})"},
            ))
        return results
