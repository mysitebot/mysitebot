"""Shared MDX/JSX expression scanning primitives.

The agent's content validator and the api's section editor both scan the same
MDX dialect; the brace matcher is the piece where a divergence is dangerous —
if one side treats a ``}`` inside a JS string/template-literal/comment as
closing the expression and the other doesn't, they disagree about where a tag
ends, and content one side validated is not the content the other edits.
This module is the single implementation both import.
"""


def js_aware_brace_end(text: str, start: int) -> int:
    """
    Given ``text[start] == '{'``, return the index of the matching closing
    ``}`` for the JS expression beginning there — treating single/double-
    quoted strings, backtick-delimited spans, and ``//`` / ``/* */`` comments
    as opaque, so a brace character inside any of them can never affect
    nesting depth. Returns ``len(text)`` if the braces never balance
    (unterminated).

    Without this, a naive brace counter would end the "expression" early at
    a ``}`` embedded inside a JS string/template literal/comment, silently
    dropping the real remaining tail of the expression from the scan —
    exactly the shape every injection payload needs to slip an executable
    tail past validation unseen.
    """
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            quote = ch
            i += 1
            while i < n:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch == "`":
            i += 1
            while i < n:
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if text[i] == "`":
                    i += 1
                    break
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i = min(i + 2, n)
            continue
        if ch == "{":
            depth += 1
            i += 1
            continue
        if ch == "}":
            depth -= 1
            i += 1
            if depth <= 0:
                return i - 1
            continue
        i += 1
    return n
