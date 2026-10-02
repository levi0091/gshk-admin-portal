"""CR's ND2A / ND2B form model: dict in, the inner XML of <cr:formModel> out.

The schemas are generated from CR's worksheet by `scripts/gen_nd2_schema.py`
and committed beside this module, exactly as NAR1's is — so the runtime needs no
Excel and a CR revision arrives as a reviewable diff.

Elements are emitted in SCHEMA order, never in dict order: CR's signature digest
is computed over the bytes we send, so one input must always give one output.
A bean dict may carry `"@id"`, which becomes the element's `id` attribute — the
hook a consent signature points at (`<cr:PinSign URI="#S1">`, spec §8).

`validate` checks length and characters only. Whether a field is required
depends on who the officer is (a natural person's `rsnCes`, a director's
`selectPersonId`), which the mappers know and the schema does not — the same
split NAR1 draws.
"""
from __future__ import annotations

import json
import pathlib
from functools import lru_cache

from services.tpsi.forms.nar1 import FormValidationError, escape_xml_text
from services.tpsi.forms.spec import Node, _build

_SCHEMAS = {"Nd2a": "nd2a_schema.json", "Nd2b": "nd2b_schema.json"}
_DIR = pathlib.Path(__file__).with_name("schema")


@lru_cache(maxsize=None)
def form_model(form_code: str) -> Node:
    if form_code not in _SCHEMAS:
        raise ValueError(f"no schema for form {form_code!r}")
    root = _build(json.loads((_DIR / _SCHEMAS[form_code]).read_text(encoding="utf8")))
    eform = next(c for c in root.children if c.name == "EForm")
    return next(c for c in eform.children if c.name == "formModel")


def _has_control_chars(value: str) -> bool:
    return any(ord(ch) < 32 for ch in value)


def _validate(node: Node, data: dict, where: str, errors: list[str]) -> None:
    by_name = {c.name: c for c in node.children}
    for key, value in data.items():
        if key.startswith("@"):
            continue
        child = by_name.get(key)
        path = f"{where}/{key}" if where else key
        if child is None:
            errors.append(f"{path}: not a field CR's form carries")
            continue
        if isinstance(value, list):
            item = child.children[0] if child.children else None
            for i, entry in enumerate(value, 1):
                if item is None or not isinstance(entry, dict):
                    errors.append(f"{path}[{i}]: not a list of beans")
                    continue
                _validate(item, entry, f"{path}/{item.name}[{i}]", errors)
        elif isinstance(value, dict):
            _validate(child, value, path, errors)
        elif value is not None:
            text = str(value).strip()
            if child.max_length and len(text) > child.max_length:
                errors.append(f"{path}: {len(text)} characters, CR allows "
                              f"{child.max_length}")
            if _has_control_chars(text):
                errors.append(f"{path}: contains a control character (a pasted tab "
                              "or line break)")


def validate(form_code: str, data: dict) -> list[str]:
    """Every length or character problem, not just the first."""
    errors: list[str] = []
    _validate(form_model(form_code), data, "", errors)
    return errors


def _emit(node: Node, data: dict) -> str:
    parts = []
    for child in node.children:
        if child.name not in data:
            continue
        value = data[child.name]
        if isinstance(value, list):
            if not value:
                continue
            item = child.children[0]
            inner = "".join(
                f"<cr:{item.name}"
                + (f' id="{escape_xml_text(str(entry["@id"]))}"' if entry.get("@id") else "")
                + f">{_emit(item, entry)}</cr:{item.name}>"
                for entry in value
            )
            parts.append(f"<cr:{child.name}>{inner}</cr:{child.name}>")
        elif isinstance(value, dict):
            inner = _emit(child, value)
            if inner:
                parts.append(f"<cr:{child.name}>{inner}</cr:{child.name}>")
        else:
            text = "" if value is None else str(value).strip()
            if text:
                parts.append(f"<cr:{child.name}>{escape_xml_text(text)}</cr:{child.name}>")
    return "".join(parts)


def build(form_code: str, data: dict) -> str:
    """Inner content of <cr:formModel>, ready for `soap.build_submission`.
    Raises `FormValidationError` listing every fault."""
    errors = validate(form_code, data)
    if errors:
        raise FormValidationError(errors)
    return _emit(form_model(form_code), data)
