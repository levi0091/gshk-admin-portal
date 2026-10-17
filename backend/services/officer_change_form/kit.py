"""The mechanics ND2A and ND2B share with each other and with NAR1.

Everything here is template-agnostic. NAR1's renderer (`nar1_form/fill.py`)
solved each of these problems first and its reasoning is not repeated; the
functions it already exposes are reused, and the two it binds to its own
template (`_add_page`, `_fill`) are restated here with the template passed in.

  * a page copy RENAMES its widgets (`<name>__p<index>`), because an AcroForm
    field is identified across the whole document — two copies of Continuation
    Sheet A must be two fields, not one field rendered twice;
  * values are written into the widgets, then `appearance.bake` draws them as
    page content in the embedded faces and REMOVES the form: the shipped PDF
    carries no field, so no viewer can draw a second copy of any value;
  * typography is NAR1's measured set — 10pt Tinos Bold for every value, 14pt
    for the header BR number, 12pt for the company name, the presenter's block
    regular, left-aligned 9.4pt inside the box unless CR centres that box.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject, TextStringObject

from services.nar1_form import appearance
from services.nar1_form import field_map as nar1_fm
from services.nar1_form import fill as nar1_fill

logging.getLogger("pypdf.generic._appearance_stream").setLevel(logging.ERROR)

FORM_DIR = Path(__file__).resolve().parent / "form"
CHECKBOX_ON = nar1_fm.CHECKBOX_ON
NONE_GIVEN = nar1_fill.NONE_GIVEN
DEFAULT_PRESENTER = nar1_fill.DEFAULT_PRESENTER
split_date = nar1_fill.split_date
signature_date = nar1_fill.signature_date
signature_capacity_office = nar1_fill.signature_capacity_office
widget_name = nar1_fill.widget_name


class FormFillError(RuntimeError):
    """The form cannot be rendered faithfully — never a partial PDF."""


def strike_value(template: Path) -> str:
    """The option string that means "delete this word", read off the template
    itself: CR's dropdowns carry exactly two options, a blank and the rule."""
    reader = PdfReader(str(template))
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            parent = obj.get("/Parent")
            opts = obj.get("/Opt") or (parent.get_object().get("/Opt") if parent else None)
            if opts:
                marks = [str(o) for o in opts if str(o).strip()]
                if marks:
                    return marks[0]
    raise FormFillError(f"{template.name} carries no strike-through option")


def add_page(writer: PdfWriter, template: Path, template_page: int, suffix: str) -> dict:
    """Append one copy of a template page; return {original name: name here}.
    `nar1_fill._add_page` with the template passed in — see its docstring."""
    source = PdfReader(str(template))
    source_page = source.pages[template_page - 1]
    source_annots = list(source_page.get("/Annots") or [])
    writer.add_page(source_page)
    copied = list(writer.pages[-1].get("/Annots") or [])
    if len(copied) != len(source_annots):
        raise FormFillError(f"page {template_page} copied with {len(copied)} widgets "
                            f"but the template has {len(source_annots)}")
    fields = writer._root_object["/AcroForm"]["/Fields"]
    mapping = {}
    for source_annot, copied_annot in zip(source_annots, copied):
        original = nar1_fill._qualified_name(source_annot.get_object())
        if not original:
            continue
        obj = copied_annot.get_object()
        parent = source_annot.get_object().get("/Parent")
        if parent is not None:
            inherited = parent.get_object()
            for key in nar1_fill._INHERITED:
                if key in inherited and key not in obj:
                    obj[NameObject(key)] = inherited[key]
        if "/Parent" in obj:
            del obj["/Parent"]
        renamed = f"{original}{suffix}"
        obj[NameObject("/T")] = TextStringObject(renamed)
        mapping[original] = renamed
        fields.append(copied_annot)
    return mapping


def fill(template: Path, pages: list[tuple[int, dict]]) -> bytes:
    """Write `[(template_page, {field: value})]` onto copies of `template`, as
    form fields. NOT a document to send: `bake` it."""
    reader = PdfReader(str(template))
    writer = PdfWriter()
    acroform = reader.trailer["/Root"]["/AcroForm"].clone(writer)
    acroform[NameObject("/Fields")] = ArrayObject()
    writer._root_object[NameObject("/AcroForm")] = writer._add_object(acroform)
    for index, (template_page, values) in enumerate(pages):
        mapping = add_page(writer, template, template_page, widget_name(index, ""))
        values = {k: v for k, v in values.items() if v not in (None, "")}
        missing = set(values) - set(mapping)
        if missing:
            raise FormFillError(f"page {template_page} does not carry {sorted(missing)}; "
                                "the field map and the composer disagree")
        if values:
            writer.update_page_form_field_values(
                writer.pages[-1], {mapping[k]: v for k, v in values.items()},
                auto_regenerate=False)
    writer.compress_identical_objects()
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def bake(filled: bytes, *, sizes: dict, regular, centred, strike: str) -> bytes:
    try:
        return appearance.bake(filled, sizes=sizes, regular=regular, centred=centred,
                               strike=strike)
    except appearance.AppearanceError as exc:
        raise FormFillError(str(exc)) from exc


def presenter_reference(prefix: str, year: str, company: str) -> str:
    """`<FORM>/<year>/<company>`, shortened on a word boundary to fit the
    one-line Reference box at NAR1's 7pt floor (`fill._presenter_reference`)."""
    stem = f"{prefix}/{year}/"
    name = (company or "").strip()
    if not name:
        return stem.rstrip("/")
    if nar1_fill._reference_fits(stem + name):
        return stem + name
    words = name.split()
    while len(words) > 1:
        words.pop()
        candidate = f"{stem}{' '.join(words)}..."
        if nar1_fill._reference_fits(candidate):
            return candidate
    word = words[0]
    while word:
        word = word[:-1]
        if nar1_fill._reference_fits(f"{stem}{word}..."):
            return f"{stem}{word}..."
    return stem.rstrip("/")


def date_parts(block: dict, value: str) -> dict:
    dd, mm, yyyy = split_date(value or "")
    return {block["date_dd"]: dd, block["date_mm"]: mm, block["date_yyyy"]: yyyy}


def count(value: int) -> str:
    """A sheet count as CR prints one: the number, or nothing when it is 0."""
    return str(value) if value else ""
