"""NAR1 form XML — build and validate.

Pure functions: dict in, string out, no I/O. That is what makes the riskiest
form logic testable without CR, which matters because the TEST form APIs are
open only Mon-Fri 10:00-16:00 HKT.

The NAR1 body is NESTED and cr:-prefixed. Structure comes from the schema tree
(services/tpsi/forms/spec.py, generated from CR's parameter worksheet and
reconciled against CR's shipped examples), so this module never hardcodes a
field list:

    scalar    -> "brNo": "00000001"          -> <cr:brNo>00000001</cr:brNo>
    container -> "roAddr": {...}             -> <cr:roAddr>...</cr:roAddr>
    repeating -> "shareCapitals": [{...}, …] -> <cr:shareCapitals>
                                                  <cr:shareCapital>…
                                                  <cr:shareCapital>…
                                                </cr:shareCapitals>

Encoding rules from the spec's "Important Notes":
  - '&' must be escaped to '&amp;'
  - no control characters (including Tab)
  - max length counts CHARACTERS, not bytes
  - N.A. word sets are case-insensitive; the English-NAME set excludes bare 'NA'

CR's validate step checks format and completeness only. Semantic mismatches are
rejected AFTER submission — after the fee is taken — so this validation is
necessary but never sufficient.
"""
from services.tpsi.forms.spec import Node, find, load_nar1_schema, repeating_containers

_ROOT_PATH = "EForm/formModel"

# Re-exported so tests can assert against the schema itself, not a copy of it.
SCHEMA_FIND = find

_NA_WORDS = {"n.a.", "na", "n/a", "nil", "not applicable", "none"}
# Bare "NA" can be a genuine fragment of an English name, so it is excluded there.
_NA_WORDS_ENGLISH_NAME = _NA_WORDS - {"na"}


def escape_xml_text(value: str) -> str:
    """& first — escaping it after the others would double-escape them."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def is_na_value(value: str, english_name: bool = False) -> bool:
    words = _NA_WORDS_ENGLISH_NAME if english_name else _NA_WORDS
    return value.strip().lower() in words


def _has_control_chars(value: str) -> bool:
    return any(ord(c) < 32 and c not in "\r\n" for c in value)


def _node_for(path: str) -> Node | None:
    return find(f"{_ROOT_PATH}/{path}" if path else _ROOT_PATH)


def _is_repeating(path: str) -> bool:
    return f"{_ROOT_PATH}/{path}" in repeating_containers()


def _validate_level(data: dict, path: str, errors: list[str]) -> None:
    parent = _node_for(path)
    if parent is None:
        return
    known = {c.name for c in parent.children}

    for key, value in data.items():
        where = f"{path}/{key}" if path else key
        if key not in known:
            errors.append(f"{where}: not a NAR1 XML element")
            continue

        node = next(c for c in parent.children if c.name == key)
        is_container = bool(node.children)

        if isinstance(value, list):
            if not _is_repeating(where):
                errors.append(f"{where}: not a repeating element, got a list")
                continue
            item = node.children[0]
            for entry in value:
                if not isinstance(entry, dict):
                    errors.append(f"{where}: list entries must be objects")
                    continue
                _validate_level(entry, f"{where}/{item.name}", errors)
            continue

        if isinstance(value, dict):
            if not is_container:
                errors.append(f"{where}: is a scalar element, got an object")
                continue
            _validate_level(value, where, errors)
            continue

        if is_container:
            errors.append(f"{where}: is a container element, got a scalar")
            continue

        text = "" if value is None else str(value)
        if not text:
            continue
        if _has_control_chars(text):
            errors.append(f"{where}: contains a control character (including Tab)")
        # Characters, not bytes — CR counts characters, and a 100-character
        # Chinese name is 300 UTF-8 bytes.
        if node.max_length and len(text) > node.max_length:
            errors.append(
                f"{where}: length {len(text)} exceeds the maximum {node.max_length}"
            )


def validate(data: dict) -> list[str]:
    """Every problem, not just the first — CR returns a full fault list and so
    should we, or the user fixes one field per round trip."""
    errors: list[str] = []
    _validate_level(data, "", errors)
    return errors


def _build_level(data: dict, path: str) -> str:
    """Emit children in SCHEMA order, not caller-dict order.

    Determinism matters: CR's signature digest is computed over the document we
    send, so the same input must always produce the same bytes.
    """
    parent = _node_for(path)
    if parent is None:
        return ""

    parts: list[str] = []
    for node in parent.children:
        if node.name not in data:
            continue
        value = data[node.name]
        where = f"{path}/{node.name}" if path else node.name

        if isinstance(value, list):
            if not value:
                continue  # omit an empty container entirely
            item = node.children[0]
            inner = "".join(
                f"<cr:{item.name}>"
                f"{_build_level(entry, f'{where}/{item.name}')}"
                f"</cr:{item.name}>"
                for entry in value
            )
            parts.append(f"<cr:{node.name}>{inner}</cr:{node.name}>")
        elif isinstance(value, dict):
            inner = _build_level(value, where)
            if inner:
                parts.append(f"<cr:{node.name}>{inner}</cr:{node.name}>")
        else:
            text = "" if value is None else str(value).strip()
            if not text:
                continue  # CR treats absent and blank alike
            parts.append(f"<cr:{node.name}>{escape_xml_text(text)}</cr:{node.name}>")
    return "".join(parts)


def build_nar1_xml(data: dict) -> str:
    """Inner content of <cr:formModel>, ready for soap.build_submission()."""
    errors = validate(data)
    if errors:
        raise ValueError("NAR1 validation failed: " + "; ".join(errors))
    load_nar1_schema()  # fail fast if the committed schema is missing
    return _build_level(data, "")
