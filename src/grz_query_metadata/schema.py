"""Reading the declared enums out of a GRZ JSON Schema.

The survey counts what it sees, so an enum value that never occurs is simply
absent from the report. To fill those gaps in, the aggregation walks the schema
to the same metadata paths the survey used (see
:mod:`grz_query_metadata.fields`) and reads the enum declared there.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .fields import split_segment


def _pointer(root: Any, frag: str) -> Any:
    node = root
    for part in frag.strip("/").split("/"):
        if not part:
            continue
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[part] if isinstance(node, dict) else node[int(part)]
    return node


def deref(node: Any, root: dict, base: Path) -> Any:
    """Follow $ref, local or to a sibling vocabulary file.

    Raises ValueError after ten chained references — a chain that long means a
    reference cycle, and returning the unresolved node would silently read as
    "no enum declared here".
    """
    for _ in range(10):
        if not (isinstance(node, dict) and "$ref" in node):
            return node
        ref = node["$ref"]
        target, _, frag = ref.partition("#")
        if not target:  # local: "#/$defs/..."
            node = _pointer(root, frag)
        else:  # file: "vocabularies/x.json"
            with open(base / target, encoding="utf-8") as fh:
                sub = json.load(fh)
            node = _pointer(sub, frag) if frag else sub
    raise ValueError(f"more than 10 chained $refs (reference cycle?) at {node.get('$ref')!r}")


def declared_enum(root: dict, base: Path, path: str) -> list[str] | None:
    """Walk a metadata path such as donors[]/labData[]/libraryType into the
    schema and return the enum declared there, or None if there isn't one."""
    node: Any = root
    for seg in path.split("/"):
        key, is_array = split_segment(seg)
        node = deref(node, root, base)
        if not isinstance(node, dict):
            return None
        found = (node.get("properties") or {}).get(key)
        if found is None:  # may sit inside allOf/anyOf/oneOf
            for comb in ("allOf", "anyOf", "oneOf"):
                for branch in node.get(comb) or []:
                    branch = deref(branch, root, base)
                    if isinstance(branch, dict) and key in (branch.get("properties") or {}):
                        found = branch["properties"][key]
                        break
                if found is not None:
                    break
        if found is None:
            return None
        node = found
        if is_array:
            node = deref(node, root, base)
            if not isinstance(node, dict) or "items" not in node:
                return None
            node = node["items"]
    node = deref(node, root, base)
    enum = node.get("enum") if isinstance(node, dict) else None
    return [str(v) for v in enum] if isinstance(enum, list) else None


def enum_paths(root: dict, base: Path) -> Iterator[str]:
    """Yield every metadata path at which the schema declares an enum.

    The reverse direction of :func:`declared_enum`: instead of asking what a
    known path declares, discover which paths declare anything at all. The
    aggregation compares the result against the surveyed paths, so a schema
    that grows a new enum the survey does not cover produces a warning instead
    of a silently incomplete usage picture.
    """
    yield from _enum_paths(root, root, base, "", 0)


def _enum_paths(node: Any, root: dict, base: Path, prefix: str, depth: int) -> Iterator[str]:
    if depth > 12:  # deeper than any real metadata document
        return
    node = deref(node, root, base)
    if not isinstance(node, dict):
        return
    # Properties may sit on the node itself or inside composition branches.
    branches = [node]
    for comb in ("allOf", "anyOf", "oneOf"):
        branches += [deref(b, root, base) for b in node.get(comb) or []]
    for branch in branches:
        if not isinstance(branch, dict):
            continue
        for key, child in (branch.get("properties") or {}).items():
            child = deref(child, root, base)
            segment = key
            if isinstance(child, dict) and "items" in child:  # an array: descend into its items
                segment = key + "[]"
                child = deref(child["items"], root, base)
            path = f"{prefix}/{segment}" if prefix else segment
            if isinstance(child, dict) and isinstance(child.get("enum"), list):
                yield path
            else:
                yield from _enum_paths(child, root, base, path, depth + 1)
