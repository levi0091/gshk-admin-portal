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


def _is_repeating_wrapper(node: "Node") -> bool:
    """CR's repeating pattern: a wrapper holding one repeated child, whose name
    the wrapper's own name extends.

        shareCapitals/shareCapital   indSecList/indSec   corpDirList/corpDir
        shares/share                 shareHolderGrps/shareHolderGrp
        allotteeRec/allottee

    The name relationship is the load-bearing part. Detecting on structure alone
    ("one child, and that child has children") is too loose: `schedule1` has a
    single `shares` child, so it would be misread as repeating, and the builder
    would then emit one `<share>` where CR sent two — silently losing every
    share class after the first.
    """
    if len(node.children) != 1:
        return False
    child = node.children[0]
    return bool(child.children) and node.name.startswith(child.name)


@lru_cache(maxsize=1)
def repeating_containers() -> frozenset[str]:
    """Paths of the repeating wrappers, derived from the schema rather than a
    hardcoded list, so a new worksheet needs no code change here."""
    out: set[str] = set()

    def walk(node: Node, prefix: str) -> None:
        for child in node.children:
            path = f"{prefix}/{child.name}" if prefix else child.name
            if _is_repeating_wrapper(child):
                out.add(path)
            walk(child, path)

    walk(load_nar1_schema(), "")
    return frozenset(out)
