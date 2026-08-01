"""Loads the committed NAR1 XML schema tree.

Generated from CR's §7.2 worksheet by scripts/gen_nar1_schema.py, reconciled
against CR's shipped example instances, and committed as nar1_schema.json.
Regenerate and re-commit when CR issues a new worksheet — never hand-edit the
JSON, and never add a name to it that CR's examples do not use.

This is a TREE, not a flat dictionary, because the NAR1 XML is nested:
addresses are containers (roAddr, stdAddress), officers and share classes are
repeating lists (indSecList/indSec, shareCapitals/shareCapital), and Schedule 1
nests five levels deep.
"""
import json
import pathlib
from dataclasses import dataclass, field
from functools import lru_cache

_PATH = pathlib.Path(__file__).with_name("nar1_schema.json")


@dataclass(frozen=True)
class Node:
    name: str
    depth: int
    data_type: str
    mandatory: bool
    max_length: int | None
    remark: str
    children: list["Node"] = field(default_factory=list)


def _build(raw: dict) -> Node:
    return Node(
        name=raw["name"],
        depth=raw["depth"],
        data_type=raw.get("data_type", ""),
        mandatory=raw.get("mandatory", False),
        max_length=raw.get("max_length"),
        remark=raw.get("remark", ""),
        children=[_build(c) for c in raw.get("children", [])],
    )


@lru_cache(maxsize=1)
def load_nar1_schema() -> Node:
    return _build(json.loads(_PATH.read_text(encoding="utf8")))


def find(path: str) -> Node | None:
    """Resolve a slash-delimited path below <submission>."""
    node = load_nar1_schema()
    for part in path.split("/"):
        node = next((c for c in node.children if c.name == part), None)
        if node is None:
            return None
    return node


def leaf_paths() -> list[str]:
    out: list[str] = []

    def walk(node: Node, prefix: str) -> None:
        for child in node.children:
            path = f"{prefix}/{child.name}" if prefix else child.name
            if child.children:
                walk(child, path)
            else:
                out.append(path)

    walk(load_nar1_schema(), "")
    return out


@lru_cache(maxsize=1)
def repeating_containers() -> frozenset[str]:
    """Containers whose single child is the repeating item.

    CR's pattern is a plural wrapper holding one repeated singular child:
    shareCapitals/shareCapital, indSecList/indSec, corpDirList/corpDir,
    shares/share, allotteeRec/allottee. Detected structurally rather than from
    a hardcoded list, so a new worksheet needs no code change here.
    """
    out: set[str] = set()

    def walk(node: Node, prefix: str) -> None:
        for child in node.children:
            path = f"{prefix}/{child.name}" if prefix else child.name
            if len(child.children) == 1 and child.children[0].children:
                out.add(path)
            walk(child, path)

    walk(load_nar1_schema(), "")
    return frozenset(out)
