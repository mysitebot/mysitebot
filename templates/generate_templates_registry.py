#!/usr/bin/env python3
"""Regenerate the layout `code` snapshots inside templates_registry.json.

The registry (templates_registry.json, next to this script) is the hand-curated
metadata the marketing site's template gallery consumes (names, taglines,
preview sections, editable fields). The one part of it that is DERIVED — the
`code` field of each layout, an MDX snapshot of the layout's content pages —
drifts whenever templates/layouts/* change, so it is generated here instead of
hand-synced.

Run after editing any layout:

    python3 projects/agent/templates/generate_templates_registry.py

Rules (match the historical snapshot format):
  * single-page layouts -> the raw index.mdx content
  * multi-page layouts  -> each file prefixed with a `# content/pages/<name>`
    header, files joined by a blank line, index.mdx first then alphabetical.
"""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = TEMPLATES_DIR / "templates_registry.json"
LAYOUTS_DIR = TEMPLATES_DIR / "layouts"


def _layout_code(layout_id: str) -> str | None:
    pages_dir = LAYOUTS_DIR / layout_id / "content" / "pages"
    if not pages_dir.is_dir():
        return None
    files = sorted(
        pages_dir.rglob("*.mdx"),
        key=lambda p: (p.relative_to(pages_dir) != Path("index.mdx"), str(p.relative_to(pages_dir))),
    )
    if not files:
        return None
    if len(files) == 1:
        return files[0].read_text().rstrip("\n")
    chunks = []
    for f in files:
        rel = f.relative_to(pages_dir)
        chunks.append(f"# content/pages/{rel}\n{f.read_text().rstrip()}")
    return "\n\n".join(chunks)


def main() -> int:
    registry = json.loads(REGISTRY_PATH.read_text())
    changed = 0
    for layout in registry.get("layouts", []):
        code = _layout_code(layout["id"])
        if code is None:
            print(f"WARNING: no pages found for layout {layout['id']!r}; leaving code as-is")
            continue
        if layout.get("code") != code:
            layout["code"] = code
            changed += 1
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {REGISTRY_PATH} ({changed} layout code snapshot(s) refreshed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
