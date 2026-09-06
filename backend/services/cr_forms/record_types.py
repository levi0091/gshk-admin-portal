"""The registers NAR1 section 16 asks a company to locate.

CR asks where each statutory register is *kept*. Viewpoint already recorded
that, as address assignments carrying its own two-character type codes, so the
codes are Viewpoint's and the labels are CR's question.

**Viewpoint's address types cover more than registers, and the extra ones are
deliberately not here:**

  excluded  ``SR``, ``SB``   the company's own registered office and principal
                             place of business. Those are addresses OF the
                             company, not places where records are kept, and
                             section 16 does not ask about them.
  excluded  ``SS``, ``ST``, ``SU``  common seal, small seal, chop. Physical
                             objects. A company that keeps its seal in a safe
                             has not answered a question about registers.

This lives in `services/` rather than in the ETL because three callers need
the same list and a second copy is exactly the drift this PRD was written to
stop: `etl/backfill_cr_form_fields.py` seeds from it, the companies router
validates writes against it, and the profile screen labels rows with it.

Order is the order the screen renders — the registers CR asks about most
often first, not alphabetical by a code nobody reads.
"""

#: code -> the register as CR names it. Ordered.
RECORD_TYPES: tuple[tuple[str, str], ...] = (
    ("SO", "Register of Directors/Secretaries"),
    ("SH", "Register of Directors"),
    ("SG", "Register of Company Secretaries"),
    ("SM", "Register of Members"),
    ("SQ", "Significant Controllers Register"),
    ("SC", "Register of Charges"),
    ("SD", "Register of Debenture Holders"),
    ("SI", "Minute Book"),
    ("SP", "Location of Accounting Records"),
    ("SA", "Copies of Instruments Creating Charges"),
    ("S1", "Copy of Permitted Indemnity Provision"),
    ("S2", "Copy of Management Contract"),
    ("S3", "Register of Particulars Referred to in s.653P"),
)

#: The codes alone, in render order.
RECORD_TYPE_CODES: tuple[str, ...] = tuple(code for code, _ in RECORD_TYPES)

LABELS: dict[str, str] = dict(RECORD_TYPES)


def label_for(code: str) -> str:
    """CR's name for a register, falling back to the raw code.

    Falls back rather than raising: Viewpoint may hold a type this list has
    not caught up with, and a row rendering as ``SX`` is a great deal better
    than a profile that will not load.
    """
    return LABELS.get(code, code)


def is_known(code: str) -> bool:
    return code in LABELS
