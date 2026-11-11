"""Read the YAML-style front-matter block written by the digest builder."""
from __future__ import annotations

import json


def parse_front_matter(text: str) -> dict[str, object]:
    """Return the front-matter of a digest as a dict.

    Values are strings, except `keywords` (list of str). Returns {} if the text
    has no front-matter block.
    """
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        return {}
    out: dict[str, object] = {}
    for line in lines[1:]:
        if line == "---":
            return out
        key, sep, value = line.partition(": ")
        if not sep:
            continue
        out[key] = json.loads(value) if value.startswith("[") else value
    return {}  # unterminated block
