"""Media-URL integrity: keep the real image UUID out of the model's hands, and
catch a model that pastes a raw URL anyway.

Sam authors MDX by retyping tool output, and an LLM can silently corrupt a hex
character in a long UUID URL (live 2026-07-20: it committed `…f3f16e.jpeg`,
which 404s, when the media API had served `…f3a16e.jpeg`). Three defenses,
composed at commit time in branch_and_edit_content:

  (a) search_media_library returns short `media://N` HANDLES as the image src;
      substitute_media_handles() swaps each handle for its recorded real URL
      server-side, so the model never reproduces a UUID at all.
  (b) A backstop for a model that ignores handles and pastes a raw media-host
      URL: find_unvetted_media_urls() rejects any URL on a media host that was
      not served this turn and is not already in the file — a mistyped UUID
      lands here because the corrupted string matches nothing vetted.
  (c) new_external_image_urls() + dead_image_urls() HEAD-check newly added
      NON-media image URLs and reject only on a definitive 404 (fail open on
      any network ambiguity, and never touch URLs the backstop already vets).

Everything here is pure except dead_image_urls, which takes an injected async
HEAD function so the core stays offline-provable and the eval harness never
makes a network call.
"""
import re
from typing import Awaitable, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urlsplit

# `media://N` — the opaque handle the tool hands the model in place of a real
# URL. N is the handle's index within the turn (see toolbox.search_media_library).
_HANDLE_RE = re.compile(r"media://\d+")

# A full http(s) URL. Stops at whitespace and the characters that bound a URL in
# MDX/markdown (quotes, angle brackets, a closing paren/bracket) so a URL inside
# `src="..."` or a markdown `![](...)` is captured without its delimiter. A
# handful of trailing sentence-punctuation chars are stripped afterwards.
_URL_RE = re.compile(r"""https?://[^\s"'<>)\]}]+""")
_URL_TRAILING = ".,;:!?"

# Path suffixes that mark a URL as an image reference (query string ignored).
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".avif", ".bmp", ".ico")


def _clean(url: str) -> str:
    return url.rstrip(_URL_TRAILING)


def _urls_in(text: str) -> List[str]:
    return [_clean(u) for u in _URL_RE.findall(text or "")]


def _is_image_url(url: str) -> bool:
    return urlsplit(url).path.lower().endswith(_IMAGE_EXTS)


def _dedupe(items: List[str]) -> List[str]:
    """First-seen order, no duplicates."""
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def substitute_media_handles(content: str, handle_map: Dict[str, str]) -> Tuple[str, List[str]]:
    """Replace every `media://N` token in `content` with handle_map['media://N']
    (the real URL recorded when the handle was issued this turn). Returns
    (substituted_content, unknown_handles): unknown_handles are tokens with no
    recorded mapping — a handle the model invented or corrupted — left verbatim
    in the returned content so the caller can reject the commit and name them."""
    unknown: List[str] = []

    def repl(match: re.Match) -> str:
        token = match.group(0)
        url = handle_map.get(token)
        if url is None:
            unknown.append(token)
            return token
        return url

    return _HANDLE_RE.sub(repl, content), _dedupe(unknown)


def hosts_of(urls) -> Set[str]:
    """The set of netlocs (host[:port]) across `urls`."""
    return {urlsplit(u).netloc for u in urls if urlsplit(u).netloc}


def find_unvetted_media_urls(
    new_content: str,
    prior_content: str,
    allowed_urls: Set[str],
    guarded_hosts: Set[str],
) -> List[str]:
    """Full URLs in `new_content` whose host is in `guarded_hosts` (a media
    host we served this turn) but which are neither in `allowed_urls` (the real
    URLs handed out this turn) nor already present verbatim in `prior_content`.
    Each such URL is a candidate mis-transcription — the commit is rejected
    listing them exactly. Empty guarded_hosts (no media searched this turn) =>
    nothing to guard."""
    if not guarded_hosts:
        return []
    prior_urls = set(_urls_in(prior_content))
    offenders = [
        url for url in _urls_in(new_content)
        if urlsplit(url).netloc in guarded_hosts
        and url not in allowed_urls
        and url not in prior_urls
    ]
    return _dedupe(offenders)


def new_external_image_urls(
    new_content: str,
    prior_content: str,
    exclude_hosts: Set[str],
) -> List[str]:
    """Image URLs newly introduced by this edit (present in new_content, absent
    from prior_content) whose host is NOT in `exclude_hosts`. Media-library
    hosts are excluded because the backstop already vets them; what's left are
    external images worth a liveness HEAD-check."""
    prior_urls = set(_urls_in(prior_content))
    fresh = [
        url for url in _urls_in(new_content)
        if url not in prior_urls
        and _is_image_url(url)
        and urlsplit(url).netloc not in exclude_hosts
    ]
    return _dedupe(fresh)


async def dead_image_urls(
    urls: List[str],
    head_status: Callable[[str], Awaitable[Optional[int]]],
) -> List[str]:
    """The subset of `urls` for which `head_status(url)` returns a DEFINITIVE
    404. head_status returns an HTTP status int, or None when liveness can't be
    determined (timeout, DNS failure, connection error). Any status other than
    404 — including None or a raised exception — is treated as live: this guard
    only ever rejects a URL proven dead, never one merely unreachable."""
    dead: List[str] = []
    for url in urls:
        try:
            status = await head_status(url)
        except Exception:
            status = None
        if status == 404:
            dead.append(url)
    return _dedupe(dead)
