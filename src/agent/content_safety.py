import posixpath


def is_safe_content_path(file_path: str) -> bool:
    """
    Validates that the file path strictly resides within the content/ directory.
    Purely LEXICAL on purpose: callers join this path onto a per-project
    workspace directory, so resolving against the process CWD would validate
    the wrong root — and os.path.join discards the project dir entirely for an
    absolute file_path, which would then land outside every workspace.
    Absolute paths and any '..' segment (even one that would normalize back
    inside content/) are rejected outright, because the RAW path is what gets
    joined downstream.
    """
    if not file_path:
        return False
    normalized = file_path.replace("\\", "/")
    if posixpath.isabs(normalized):
        return False
    if ".." in normalized.split("/"):
        return False
    return posixpath.normpath(normalized).startswith("content/")


def check_content_for_cookies(content: str, file_path: str = "") -> str | None:
    """
    Programmatically monitors and blocks any code/content from using or collecting cookies.
    Allows descriptive references to 'cookies' in markdown text (e.g. 'We do not collect cookies')
    but strictly blocks programmatic cookie access, storage manipulation, or script injections.
    """
    content_lower = content.lower()

    # 1. Strict programmatic cookie access indicators.
    # Only match clearly programmatic patterns; plain words like "analytics" must remain
    # legal in copy text (and the default settings.yaml contains an `analytics:` block).
    # Keep in sync with the `forbidden` list in
    # templates/astro-basic/src/content/config.ts (the build-time frontmatter guard).
    cookie_indicators = [
        "document.cookie",
        "cookiestore",
        "set-cookie",
        "set_cookie",
        "cookies.set",
        "cookies.get",
        "cookies.delete",
        "gtag(",
        "gtag.js",
        "googletagmanager",
        "google-analytics.com",
    ]
    for marker in cookie_indicators:
        if marker in content_lower:
            return f"Forbidden cookie-accessing code/reference found: '{marker}'"

    # 2. Prevent script injections in markdown/HTML or config that contain tracking code
    if "<script" in content_lower:
        import re
        script_blocks = re.findall(r"<script\b[^>]*>(.*?)</script>", content_lower, re.DOTALL)
        for block in script_blocks:
            if any(t in block for t in ["cookie", "gtag", "analytics", "fbq(", "pixel"]):
                return "Script block contains forbidden references to cookies or tracking."

        # Also check script src attribute for tracking or cookie services
        src_matches = re.findall(r'src=["\']([^"\']*)["\']', content_lower)
        for src in src_matches:
            if any(t in src for t in ["cookie", "analytics", "gtag", "fbevents", "pixel"]):
                return f"Forbidden script source found: '{src}' (tracking/cookie setting suspected)"

    return None
