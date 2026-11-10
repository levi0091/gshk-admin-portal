"""Print a director's drawn signature on the rendered ND2A / ND2B (e-signature-nd2).

The portal's own copy of the form carries the picture a director drew on the
Confirm & File page, in the boxes the form leaves for a signature. It is
stamped AFTER `kit.bake`, because baking removes every widget and the
signature areas have none: on ND2A's page 2 and on a Continuation Sheet B the
natural-person consent is a printed "Signed :" label and a rule with NOTHING
beside it, and on page 3 the form-level signature is the unwidgeted space above
the typed NAME box (`fill_22_P.3` / `fill_30_P.3`), which holds the name and
must not be overprinted. So the areas are MEASURED RECTS, constants below, pinned
by `tests/officer_changes/test_signature_printing.py` the way the NAR1 specimen
geometry is.

Coordinates are PyMuPDF's: points, y measured DOWN from the top edge, which is
how the rects were read off the template.

WHICH PERSON'S SIGNATURE GOES IN WHICH BOX is decided by what the page itself
prints, never by position. `compose()` hands back, for every output page, the
values it wrote; a consent box takes the signature whose (surname, other names)
equal the names printed on that very page, and the page-3 box the one whose
name equals the typed signatory. The form the client confirmed is frozen while
the entries it was built from can move afterwards (the receipt renders the
frozen XML against the live case), so a signature that matches no box is
REPORTED and printed nowhere, never put in the nearest one: a wrong signature
on a statutory copy is worse than a blank.

NOT CR'S. TPSI carries no image and e-filing still PIN-signs exactly as before;
this is the portal's copy and the paper for the manual route. A body-corporate
consent signer (an authorised person, not the appointee) is left blank.
"""
from __future__ import annotations

import io
import sys
from dataclasses import dataclass, field

from PIL import Image, ImageChops
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from services.officer_change_form import nd2a_map, nd2b_map
from services.officer_change_form.kit import CHECKBOX_ON

#: (x0, top, x1, bottom), PyMuPDF space. Each lies on its own page's measured
#: furniture; the test re-reads the template and fails a revision that moves it.
#:
#: ND2A page 2 -- the consent's rule runs x 137.8-492.1 at y 778.2; the consent
#: text above it ends at y 734.1.
ND2A_CONSENT_MAIN = (137.8, 738.0, 492.1, 777.4)
#: ND2A Continuation Sheet B -- same rule at y 789.2; the cell above it begins at
#: the frame's cross-line at y 758.0.
ND2A_CONSENT_SHEET_B = (137.8, 760.0, 492.1, 788.2)
#: ND2A page 3 -- between the section 5 text (ends y 738.1) and the top of the
#: typed name box (y 751.6). Only 12pt tall: the name box below is not ours.
ND2A_SIGNATURE_P3 = (123.0, 739.0, 328.6, 751.0)
#: ND2B page 3 -- between the page-count boxes (end y 741.8) and the top of the
#: typed name box (y 764.3).
ND2B_SIGNATURE_P3 = (121.3, 744.5, 326.9, 763.5)

#: A signature starts this far inside its area, as a typed value does inside its
#: box (`appearance._INSET`), and sits this far above the area's lower edge.
INSET = 9.4
LIFT = 1.0


def normalise(value) -> str:
    """Names compared as a person would: case and spacing aside."""
    return " ".join(str(value or "").split()).casefold()


@dataclass
class Signatures:
    """What the renderer may print, and what it could not.

    `consents` maps `(surname, other names)` -- as `nd2a_mapper.english_name`
    prints them -- to a PNG, for the incoming directors who signed. `signatory`
    is `(the typed signatory's name, PNG)` when the form's signatory is a natural
    person who signed. `problems` is filled by the renderer with every signature
    it did NOT print and why.
    """
    consents: dict[tuple[str, str], bytes] = field(default_factory=dict)
    signatory: tuple[str, bytes] | None = None
    problems: list[str] = field(default_factory=list)

    @staticmethod
    def key(surname, given) -> tuple[str, str]:
        return normalise(surname), normalise(given)

    def __bool__(self) -> bool:
        return bool(self.consents or self.signatory)


# -- the picture -------------------------------------------------------------------

def _ink_box(img: Image.Image):
    """The bounding box of what was drawn: a pad is mostly empty canvas, and a
    12pt box prints a signature legibly only when the margin is cropped away."""
    red, green, blue, alpha = img.split()
    visible = alpha.point(lambda a: 255 if a > 0 else 0)
    darkest = ImageChops.darker(ImageChops.darker(red, green), blue)
    not_white = darkest.point(lambda v: 255 if v < 250 else 0)
    return ImageChops.multiply(visible, not_white).getbbox()


def prepared(png: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    box = _ink_box(img)
    return img.crop(box) if box else img


def fit(width: float, height: float, area_w: float, area_h: float) -> tuple[float, float]:
    """Scale to the area keeping the aspect ratio, never beyond 1 pixel : 1 point."""
    scale = min(area_w / width, area_h / height, 1.0)
    return width * scale, height * scale


# -- where each signature goes -----------------------------------------------------

def _jobs(form_code: str, pages: list, signatures: Signatures) -> list[tuple[int, tuple, bytes]]:
    """`[(output page index, rect, png)]`, from what each page printed."""
    jobs: list[tuple[int, tuple, bytes]] = []
    used: set[tuple[str, str]] = set()
    if form_code == "Nd2a":
        for index, (template_page, values, _sheet) in enumerate(pages):
            block, rect = {nd2a_map.PAGE_MAIN_2: (nd2a_map.MAIN_2, ND2A_CONSENT_MAIN),
                           nd2a_map.PAGE_SHEET_B: (nd2a_map.SHEET_B, ND2A_CONSENT_SHEET_B),
                           }.get(template_page, (None, None))
            if block is None or values.get(block["cap_director"]) != CHECKBOX_ON:
                continue
            key = Signatures.key(values.get(block["surname_en"]),
                                 values.get(block["other_names_en"]))
            if key in signatures.consents:
                used.add(key)
                jobs.append((index, rect, signatures.consents[key]))
    for key in signatures.consents.keys() - used:
        signatures.problems.append(
            f"the signature of {' '.join(p for p in key if p)!r} matches no director's "
            "consent on this form, so it was not printed")

    if signatures.signatory:
        typed_name, png = signatures.signatory
        rect = {"Nd2a": ND2A_SIGNATURE_P3, "Nd2b": ND2B_SIGNATURE_P3}[form_code]
        field_name = (nd2a_map.MAIN_3 if form_code == "Nd2a" else nd2b_map.MAIN_3)["signed_name"]
        page_no = (nd2a_map.PAGE_MAIN_3 if form_code == "Nd2a" else nd2b_map.PAGE_MAIN_3)
        for index, (template_page, values, _sheet) in enumerate(pages):
            if template_page == page_no:
                if normalise(values.get(field_name)) == normalise(typed_name) and typed_name:
                    jobs.append((index, rect, png))
                else:
                    signatures.problems.append(
                        f"the signatory's signature is for {typed_name!r} but the form is "
                        f"signed by {values.get(field_name)!r}, so it was not printed")
                break
    return jobs


def stamp(pdf: bytes, form_code: str, pages: list, signatures: Signatures | None) -> bytes:
    """`pdf` with every signature that belongs on it drawn in; `pdf` itself,
    untouched, when there is nothing to draw. Never raises: a picture that will
    not draw is reported in `signatures.problems` and left off."""
    if not signatures:
        return pdf
    try:
        reader = PdfReader(io.BytesIO(pdf))
        if len(reader.pages) < len(pages):
            signatures.problems.append("the form's pages do not match its plan, so no "
                                       "signature was printed")
            return pdf
        jobs = _jobs(form_code, pages, signatures)
        if not jobs:
            return pdf
        writer = PdfWriter(clone_from=reader)
        for index, (x0, top, x1, bottom), png in jobs:
            page = writer.pages[index]
            width, height = float(page.mediabox.width), float(page.mediabox.height)
            try:
                img = prepared(png)
            except Exception as exc:  # noqa: BLE001 — one bad picture must not cost the form
                signatures.problems.append(f"a signature could not be read: {exc}")
                continue
            w, h = fit(img.width, img.height, (x1 - x0) - INSET, (bottom - top) - LIFT)
            buffer = io.BytesIO()
            overlay = canvas.Canvas(buffer, pagesize=(width, height))
            overlay.drawImage(ImageReader(img), x0 + INSET, height - bottom + LIFT,
                              width=w, height=h, mask="auto")
            overlay.save()
            buffer.seek(0)
            page.merge_page(PdfReader(buffer).pages[0])
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except Exception as exc:  # noqa: BLE001 — see the docstring
        signatures.problems.append(f"signatures could not be printed: {exc}")
        return pdf
    finally:
        for problem in signatures.problems:
            print(f"[officer_change_form.stamp] {problem}", file=sys.stderr)
