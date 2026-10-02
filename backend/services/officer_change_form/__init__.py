"""CR's ND2A and ND2B, filled from the form model and flattened (spec §7).

`render` is what anybody is shown or sent: CR's own template pages, every value
drawn in the embedded faces at NAR1's measured sizes, every continuation and PI
sheet the change list needs, and no form field left in the file.
`render_fields` is the same document before baking, for tests that ask which
value went in which box — never send it.

`form_xml` is CR's form model: the inner XML `officer_changes.form_xml.build`
emits (`tpsi_filings.request_xml`), or the submission CR returns validated.
`company_name` is passed in because CR fills `compNameE` only after validation;
on a validated form the XML's own name is used when none is given.
"""
from __future__ import annotations

from services.nar1_form import fill as nar1_fill
from services.officer_change_form import kit

FORM_CODES = ("Nd2a", "Nd2b")
FormFillError = kit.FormFillError


def _module(form_code: str):
    if form_code == "Nd2a":
        from services.officer_change_form import nd2a
        return nd2a
    if form_code == "Nd2b":
        from services.officer_change_form import nd2b
        return nd2b
    raise FormFillError(f"no renderer for form {form_code!r}")


def _model(form_xml: str) -> dict:
    try:
        return nar1_fill.parse_validated_xml(form_xml)
    except nar1_fill.FormFillError as exc:
        raise FormFillError(str(exc)) from exc


def _name(model: dict, company_name: str | None) -> str:
    if company_name and company_name.strip():
        return company_name.strip()
    return "  ".join(p for p in (nar1_fill._get(model, "compNameE"),
                                 nar1_fill._get(model, "compNameC")) if p)


def _composed(form_code, form_xml, *, company_name, submitted_on, presenter, public_only):
    module = _module(form_code)
    if not module.TEMPLATE.exists():
        raise FormFillError(f"CR's blank form is missing: {module.TEMPLATE}")
    model = _model(form_xml)
    strike = kit.strike_value(module.TEMPLATE)
    pages = module.compose(model, company_name=_name(model, company_name),
                           submitted_on=submitted_on, presenter=presenter,
                           public_only=public_only, strike=strike)
    return module, pages, strike


def render_fields(form_code: str, form_xml: str, *, section5_confirmed: bool = False,
                  submitted_on="", presenter: dict | None = None,
                  public_only: bool = False, company_name: str | None = None) -> bytes:
    """The same document before baking, widgets intact. Tests only — never
    sent to anybody. `section5_confirmed` is accepted for signature parity:
    ND2A's section 5 is a printed statement with no box (see nd2a_map)."""
    module, pages, _strike = _composed(form_code, form_xml, company_name=company_name,
                                       submitted_on=submitted_on, presenter=presenter,
                                       public_only=public_only)
    return kit.fill(module.TEMPLATE, [(page, values) for page, values, _s in pages])


def render(form_code: str, form_xml: str, *, section5_confirmed: bool = False,
           submitted_on="", presenter: dict | None = None,
           public_only: bool = False, company_name: str | None = None) -> bytes:
    """The flat PDF."""
    module, pages, strike = _composed(form_code, form_xml, company_name=company_name,
                                      submitted_on=submitted_on, presenter=presenter,
                                      public_only=public_only)
    filled = kit.fill(module.TEMPLATE, [(page, values) for page, values, _s in pages])
    return kit.bake(filled, sizes=module.m.FIELD_SIZES,
                    regular=module.m.REGULAR_WEIGHT_FIELDS,
                    centred=module.m.CENTRED_FIELDS, strike=strike)


def page_plan(form_code: str, form_xml: str, *, public_only: bool = False) -> list[dict]:
    """`[{"sheet", "template_page", "subject"}]` in output order."""
    module, pages, _strike = _composed(form_code, form_xml, company_name=None,
                                       submitted_on="", presenter=None,
                                       public_only=public_only)
    return [{"sheet": sheet, "template_page": page,
             "subject": module.subject(values) if hasattr(module, "subject") else ""}
            for page, values, sheet in pages]
