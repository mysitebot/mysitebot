"""Builds the Astro template in a temp workspace so collection schemas and
getStaticPaths can be asserted from pytest.

The template ships no JS test runner on purpose — every devDependency added
here would be copied into every customer repo — so a real `npm run build` is
the test seam for anything Astro actually evaluates at build time.
"""
import os
import shutil
import subprocess
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "astro-basic"
_SKIP = shutil.ignore_patterns("node_modules", "dist", ".astro")


def build_site(dest: Path, *, posts: dict[str, str] | None = None,
               pages: dict[str, str] | None = None,
               env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Copies the template to `dest`, overlays content, and builds.

    node_modules is symlinked rather than installed — the same trick
    cloudflare_workspace.sync_workspace uses in production.
    """
    shutil.copytree(TEMPLATE, dest, ignore=_SKIP)
    os.symlink(TEMPLATE / "node_modules", dest / "node_modules")

    if pages is not None:
        shutil.rmtree(dest / "content" / "pages")
        (dest / "content" / "pages").mkdir(parents=True)
        for name, body in pages.items():
            (dest / "content" / "pages" / name).write_text(body)

    if posts:
        (dest / "content" / "posts").mkdir(parents=True, exist_ok=True)
        for name, body in posts.items():
            (dest / "content" / "posts" / name).write_text(body)

    return subprocess.run(
        ["npm", "run", "build"], cwd=dest, capture_output=True, text=True,
        timeout=300, env={**os.environ, "ASTRO_BASE": "/", **(env or {})})


def post_file(title: str, date: str, **frontmatter) -> str:
    """Renders a post .mdx. Extra kwargs become extra frontmatter lines."""
    lines = [f'title: "{title}"', f"date: {date}"]
    for key, value in frontmatter.items():
        if isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, list):
            inner = ", ".join(f'"{v}"' for v in value)
            lines.append(f"{key}: [{inner}]")
        else:
            lines.append(f'{key}: "{value}"')
    body = "\n".join(lines)
    return f"---\n{body}\n---\n\nBody of {title}.\n"
