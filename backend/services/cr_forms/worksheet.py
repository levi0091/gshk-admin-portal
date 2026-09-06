"""Read CR's TPSI worksheet into a flat field inventory.

WHY THIS PARSES A SPREADSHEET. CR publishes the field-level spec for every form
as `Worksheet in TPSI API Interface v1.0.14.xlsx`, and it is the only artefact
that states, per field, whether CR *requires* it and how long it may be. The
API `.docx` does not (its embedded examples are wrong), and
`NAR1_Data_Specification.v1.4.xls` describes CR's **web UI** fields rather than
the XML, so it must never be built from.

WHERE THE FILE LIVES. `tests/fixtures/cr-examples/`, with CR's other shipped
artefacts. It is a **spec input**, not a runtime asset: nothing in the running
service reads it. `scripts/build_cr_form_contract.py` reads it to generate
`contract.py`, and the contract is what ships — so a CR revision arrives as a
reviewable diff instead of silently changing behaviour under the app. This is
the same split as `services/nar1_form/field_map.py` and CR's blank PDF.

THE SHAPE. The "Parameter name" block is an indented tree: the *column* a name
sits in is its depth in the XML, and a row is a leaf exactly when it carries a
Type. So `hkid` under `indDirList/indDir` is one field and `indDirList` is not
a field at all. Reading the sheet as a flat list of names would silently merge
the four `ctryRegion`s — registered office, shareholder, director, secretary —
into one, which is how an address ends up filed against the wrong party.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import openpyxl

#: CR's worksheet, committed alongside its other shipped artefacts.
WORKSHEET_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests" / "fixtures" / "cr-examples"
    / "Worksheet in TPSI API Interface v1.0.14.xlsx"
)

#: The column that marks a row as a leaf. Everything left of it is the
#: indented name tree; everything right of it describes the field.
_TYPE_HEADER = "Type"


@dataclass(frozen=True)
class FormField:
    """One leaf field of one CR form."""

    form: str
    #: Slash-joined ancestry, e.g. `submission/Eform/indDirList/indDir/hkid`.
    #: This — not `name` — identifies a field: `ctryRegion` occurs four times.
    path: str
    name: str
    type: str
    mandatory: bool
    max_length: Optional[int]
    remark: str


def _int_or_none(value) -> Optional[int]:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def load_fields(form: str, path: Optional[Path] = None) -> list[FormField]:
    """Every leaf field of `form` ("NAR1", "NNC1", "NNC1G", …), in sheet order."""
    workbook = openpyxl.load_workbook(path or WORKSHEET_PATH,
                                      read_only=True, data_only=True)
    try:
        sheet = workbook[form]
        rows = sheet.iter_rows(values_only=True)
        header = list(next(rows))
        type_col = header.index(_TYPE_HEADER)

        ancestry: dict[int, str] = {}
        fields: list[FormField] = []
        for row in rows:
            depth = next(
                (i for i in range(type_col) if row[i] not in (None, "")), None
            )
            if depth is None:
                continue
            # A name at depth N closes every branch deeper than N.
            ancestry = {d: v for d, v in ancestry.items() if d < depth}
            ancestry[depth] = str(row[depth]).strip()

            if row[type_col] in (None, ""):
                continue    # a container, not a field
            fields.append(FormField(
                form=form,
                path="/".join(ancestry[d] for d in sorted(ancestry)),
                name=ancestry[depth],
                type=str(row[type_col]).strip(),
                mandatory=str(row[type_col + 1] or "").strip().upper() == "Y",
                max_length=_int_or_none(row[type_col + 2]),
                remark=str(row[type_col + 3] or "").strip(),
            ))
        return fields
    finally:
        workbook.close()
