"""
Regenerates SECTIONS.md from the actual Astro section components.

The agent's system prompt embeds SECTIONS.md as its component reference, so the
documentation must always match the template. Run this whenever a component in
astro-basic/src/components/sections/ is added or changed:

    python templates/generate_sections_doc.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SECTIONS_DIR = ROOT / "astro-basic" / "src" / "components" / "sections"
OUTPUT = ROOT / "SECTIONS.md"
SCHEMA_OUTPUT = ROOT / "sections-schema.json"

HEADER = """# Section Reference Guide

This guide is the dynamic source of truth for all available UI sections.
Generated from `astro-basic/src/components/sections/` by `templates/generate_sections_doc.py` — do not edit by hand.
"""


def extract_frontmatter(source: str) -> str:
    match = re.match(r"^---\s*\n(.*?)\n---", source, re.DOTALL)
    return match.group(1) if match else source


def extract_description(frontmatter: str) -> str:
    """Takes the JSDoc block immediately preceding `interface Props`."""
    idx = frontmatter.find("interface Props")
    if idx == -1:
        return ""
    blocks = re.findall(r"/\*\*(.*?)\*/", frontmatter[:idx], re.DOTALL)
    if not blocks:
        return ""
    lines = [re.sub(r"^\s*\*\s?", "", ln).strip() for ln in blocks[-1].splitlines()]
    return " ".join(ln for ln in lines if ln)


def extract_props_block(frontmatter: str) -> str:
    """Returns the balanced body of `interface Props { ... }`."""
    idx = frontmatter.find("interface Props")
    if idx == -1:
        return ""
    start = frontmatter.find("{", idx)
    if start == -1:
        return ""
    depth = 0
    for pos in range(start, len(frontmatter)):
        if frontmatter[pos] == "{":
            depth += 1
        elif frontmatter[pos] == "}":
            depth -= 1
            if depth == 0:
                return frontmatter[start + 1:pos]
    return ""


def _split_top_level(props_block: str):
    """Splits the Props body into top-level `doc + name: type` segments on ';'.

    Characters inside a `/* ... */` doc comment are treated as literal text: a
    ';' (or a bracket) inside a JSDoc description must not be mistaken for a prop
    boundary, or the prop it documents is silently dropped from the reference.
    """
    segments = []
    depth = 0
    in_comment = False
    current = []
    i = 0
    n = len(props_block)
    while i < n:
        ch = props_block[i]
        if in_comment:
            current.append(ch)
            if ch == "*" and i + 1 < n and props_block[i + 1] == "/":
                current.append("/")
                i += 2
                in_comment = False
                continue
            i += 1
            continue
        if ch == "/" and i + 1 < n and props_block[i + 1] == "*":
            current.append("/*")
            i += 2
            in_comment = True
            continue
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth = max(depth - 1, 0)
        if ch == ";" and depth == 0:
            segments.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        segments.append(tail)
    return segments


def _clean_doc(doc_block: str) -> str:
    lines = [re.sub(r"^\s*\*\s?", "", ln).strip() for ln in doc_block.splitlines()]
    return " ".join(ln for ln in lines if ln)


def _compact_type(type_text: str) -> str:
    compact = re.sub(r"\s+", " ", type_text).strip()
    return compact if len(compact) <= 220 else compact[:217] + "..."


_ENUM_RE = re.compile(r"^\s*'[^']*'(\s*\|\s*'[^']*')*\s*$")
_LITERAL_RE = re.compile(r"'([^']*)'")


def _compact_no_truncate(type_text: str) -> str:
    """Whitespace-compacted type WITHOUT the 220-char truncation _compact_type
    applies for the markdown table (schema consumers need the full type)."""
    return re.sub(r"\s+", " ", type_text.strip().rstrip(";").strip())


def _split_object_fields(body: str):
    """Yields (name, required, type_text) for `{ a: string; b?: number }` bodies."""
    for segment in _split_top_level(body):
        seg = re.sub(r"/\*\*.*?\*/", "", segment, flags=re.DOTALL).strip()
        match = re.match(r"(\w+)(\??)\s*:\s*(.*)", seg, re.DOTALL)
        if match:
            name, optional, type_text = match.groups()
            yield name, optional != "?", _compact_no_truncate(type_text)


def _leaf_kind(type_text: str):
    """Classify a leaf field type; returns dict or None when not a leaf."""
    t = type_text.strip()
    if t == "string":
        return {"kind": "string"}
    if t == "boolean":
        return {"kind": "boolean"}
    if t == "number":
        return {"kind": "number"}
    if _ENUM_RE.match(t):
        return {"kind": "enum", "values": _LITERAL_RE.findall(t)}
    return None


def classify_type(type_text: str):
    """Map a Props type string to a form-control kind (spec §3 table)."""
    t = _compact_no_truncate(type_text)
    leaf = _leaf_kind(t)
    if leaf:
        return leaf
    if t in ("string[]", "Array<string>"):
        return {"kind": "string_list"}
    inner = None
    if t.startswith("Array<{") and t.endswith("}>"):
        inner = t[len("Array<{"):-len("}>")]
    elif t.startswith("{") and t.endswith("}[]"):
        inner = t[1:-len("}[]")]
    is_list = inner is not None
    if inner is None and t.startswith("{") and t.endswith("}"):
        inner = t[1:-1]
    if inner is not None:
        fields = []
        for name, required, ftype in _split_object_fields(inner):
            fleaf = _leaf_kind(ftype)
            if fleaf is None:
                return {"kind": "unknown"}
            fields.append({"name": name, "required": required, **fleaf})
        if not fields:
            return {"kind": "unknown"}
        if not is_list:
            names = {f["name"] for f in fields}
            if names == {"src", "alt"}:
                return {"kind": "image"}
            return {"kind": "object", "fields": fields}
        return {"kind": "object_list", "fields": fields}
    return {"kind": "unknown"}


def extract_props(props_block: str, compact=_compact_type):
    """Yields (name, required, type, doc) for every top-level Props property.

    `compact` controls type-string compaction: the markdown table truncates
    long types (`_compact_type`) while the JSON schema keeps them in full
    (`_compact_no_truncate`, passed by `write_schema`).
    """
    props = []
    for segment in _split_top_level(props_block):
        docs = re.findall(r"/\*\*(.*?)\*/", segment, re.DOTALL)
        body = re.sub(r"/\*\*.*?\*/", "", segment, flags=re.DOTALL)
        body = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("//"))
        match = re.match(r"\s*(\w+)(\??)\s*:\s*(.*)", body.strip(), re.DOTALL)
        if not match:
            continue
        name, optional, type_text = match.groups()
        doc = _clean_doc(docs[-1]) if docs else ""
        props.append((name, optional != "?", compact(type_text), doc))
    return props


def write_schema(files) -> None:
    """Builds sections-schema.json from `files`, a sequence of
    (name, description, props_block) already extracted once by `main`."""
    sections = {}
    for name, description, props_block in files:
        props = []
        for prop_name, required, type_text, doc in extract_props(props_block, compact=_compact_no_truncate):
            props.append({"name": prop_name, "required": required, "type": type_text,
                          "description": doc, **classify_type(type_text)})
        sections[name] = {"description": description, "props": props}
    SCHEMA_OUTPUT.write_text(
        json.dumps({"version": 1, "sections": sections}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"Wrote {SCHEMA_OUTPUT} ({len(sections)} sections)")


def main() -> None:
    parts = [HEADER]
    collected = []
    for astro_file in sorted(SECTIONS_DIR.glob("*.astro")):
        name = astro_file.stem
        frontmatter = extract_frontmatter(astro_file.read_text(encoding="utf-8"))
        description = extract_description(frontmatter)
        props_block = extract_props_block(frontmatter)
        collected.append((name, description, props_block))
        props = extract_props(props_block)

        parts.append(f"\n## `<{name} />`")
        if description:
            parts.append(description)
        if props:
            parts.append("\n| Property | Required | Type | Description |")
            parts.append("| :--- | :--- | :--- | :--- |")
            for prop_name, required, type_text, doc in props:
                type_cell = type_text.replace("|", "\\|")
                parts.append(f"| `{prop_name}` | {'yes' if required else 'no'} | `{type_cell}` | {doc or '—'} |")
        parts.append("\n---")

    OUTPUT.write_text("\n".join(parts).rstrip("-\n ") + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT} ({len(collected)} sections)")
    write_schema(collected)


if __name__ == "__main__":
    main()
