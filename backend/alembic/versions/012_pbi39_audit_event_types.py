"""PBI-39: audit event-type registry + consistent audit context

Revision ID: 012
Revises: 011
Create Date: 2026-07-11

The audit trail could not consistently answer "what action, on which company,
old -> new, by whom":

  * Imported Viewpoint rows carried only an instance-specific description
    ("Master File Details of Miss Ilze TSERKEZIS Changed"), so the same action
    read as a different action on every row and could not be grouped or filtered.
  * Native G-FlowDesk events carried no company name, and party/document events
    recorded no before/after values at all.

This adds ONE event-type registry used by BOTH sources, and denormalizes the
company and actor onto every row so the trail is searchable and sortable without
a join (and stays readable after a company is deleted).

audit_event_types is seeded with the 85 Viewpoint event codes actually present in
the imported EventLog - names taken from Viewpoint's own Events lookup and baked
in as literals, so this migration needs no Viewpoint connection - plus the native
G-FlowDesk actions. Viewpoint does not cover everything G-FlowDesk will do, so
new native actions get added here as they appear. This table is the registry.
"""
from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


# G-FlowDesk actions that Viewpoint has NO equivalent for. Everything else
# reuses Viewpoint's own code (see services/audit_events.py) so the same action
# groups together regardless of which system recorded it.
_NATIVE = [
    ("GF_FLAGS_CHANGED", "Client / Corporate-Party Flags Changed", "entity"),
    ("GF_SHAREHOLDER_REMOVED", "Shareholder Removed", "party"),
    ("GF_DOC_UPLOADED", "Document Uploaded", "document"),
    ("GF_DOC_VERSION", "Document Version Added", "document"),
    ("GF_DOC_DELETED", "Document Deleted", "document"),
    ("DOCUMENT_GENERATED", "Document Generated", "document"),
    ("AML_STATUS_CHANGED", "AML Status Changed", "entity"),
    ("EMAIL_SENT", "Email Sent", "entity"),
    ("TPSI_SUBMISSION_ATTEMPTED", "TPSI Submission Attempted", "tpsi"),
    ("TPSI_SUBMISSION_SUCCESS", "TPSI Submission Succeeded", "tpsi"),
    ("TPSI_SUBMISSION_FAILED", "TPSI Submission Failed", "tpsi"),
    ("CLIENT_APPROVAL_RECEIVED", "Client Approval Received", "entity"),
    ("LEGACY_VP_EVENT", "Viewpoint Event", "legacy"),
]

# Viewpoint codes present in the imported EventLog, with Viewpoint's own generic
# action names (Events.Name) - generic by design, never per-record.
_VIEWPOINT = [
    ('ACDU', 'CDD - Edit'),
    ('ACF', 'Annual Accounts File'),
    ('ADC', 'Change Master File Details'),
    ('ADI', 'Master File - Inactivated'),
    ('ADN', 'New Master File'),
    ('ADR', 'Master File - Re-activated'),
    ('AEC', 'Entity File Sub-Status - Changed'),
    ('AGM', 'Annual General Meeting'),
    ('AGN', 'AGM Notice'),
    ('ANR', 'Annual Return'),
    ('AUD', 'Annual Audit'),
    ('BNC', 'Registration Changed'),
    ('BND', 'Delete Registration'),
    ('BNE', 'Cease Registration'),
    ('BNN', 'New Registration'),
    ('BNR', 'Registration Renewal'),
    ('CAC', 'Entity Account Information Changed'),
    ('CGC', 'Entity General Info. Changed'),
    ('CHN', 'Charge - New'),
    ('CIN', 'Entity Incorporation'),
    ('CMA', 'Entity M&A Information Changed'),
    ('CNC', 'Entity Name Change Edit'),
    ('CND', 'Entity Name Change - Deleted'),
    ('CNN', 'Entity Name - Application'),
    ('CNP', 'Entity Name - Confirmed'),
    ('COC', 'Change Entity Statutory Information'),
    ('CPC', 'Change Compliance Details'),
    ('CPN', 'New Compliance Details'),
    ('DLFC', 'Form Library - Copy'),
    ('DLFE', 'Form Library - Edit'),
    ('EFN', 'Entity Relation Appointment'),
    ('EGM', 'Extraordinary General Meeting'),
    ('EITE', 'Identity/AEOI Register Types-Edit'),
    ('ESC', 'Entity Status Changed'),
    ('FLRW', 'File Review - Run'),
    ('FQD', 'Form Queue - Delete'),
    ('FQE', 'Form Queue - Properties Edit'),
    ('FQF', 'Form Queue - File'),
    ('FQFE', 'Form Queue - Edit'),
    ('FQS', 'Form Queue - Sign'),
    ('GACD', 'Address Card - Delete'),
    ('GACE', 'Address Card - Edit'),
    ('GACN', 'Address Card - New'),
    ('GBRV', 'Global Review'),
    ('IDRD', 'Identity Register - Delete'),
    ('IDRE', 'Identity Register-  Edit'),
    ('IDRN', 'Identity Register - New'),
    ('LOCA', 'Localise Script - Execute'),
    ('LRM', 'Change Location of Register or Other Document'),
    ('LRO', 'Change Location of Registered Office'),
    ('OFA', 'Statutory Officer (Director/Secretary) Appointment'),
    ('OFC', 'Statutory Officer (Director/Secr) Changed/Edit'),
    ('OFD', 'Statutory Officer (Director/Secr) Deleted'),
    ('OFF', 'Statutory Officer (First Dir/Sec)  Appointment'),
    ('OFP', 'Officer/Relation - Change of Particulars'),
    ('OFR', 'Statutory Officer (Director/Secr) Resignation'),
    ('OOA', 'Statutory Officer (Others) Appointment'),
    ('OOR', 'Statutory Officer (Others) Resignation'),
    ('OWCN', 'Owners & Controllers - New'),
    ('PSZ', 'Partner - Delete Transaction'),
    ('SCRG', 'Custom Report - Generate'),
    ('SDEF', 'System Defaults (Entity/Forms) - Edit'),
    ('SDGM', 'System Defaults (General/Master File) - Edit'),
    ('SFMG', 'Form Generation'),
    ('SHA', 'Share Issue'),
    ('SHB', 'Share - Set Beneficial Owner'),
    ('SHD', 'Share Class - Edit'),
    ('SHE', 'Share Certificate - Edit'),
    ('SHH', 'Share - Authorisation'),
    ('SHM', 'Share - Edit Transaction'),
    ('SHN', 'Share - New Certificate Issued'),
    ('SHP', 'Share Class - Capital Change'),
    ('SHR', 'Share Capital - Reduction/Cancellation'),
    ('SHT', 'Share Transfer'),
    ('SHZ', 'Share - Delete Transaction'),
    ('SMP', 'Shareholders - Change of Particulars'),
    ('STATUS', 'Status Changed'),
    ('STBS', 'Troubleshooting'),
    ('SUMA', 'User Matrix warning acknowledged'),
    ('SUPE', 'User Id - Password update-reset'),
    ('SUSD', 'User Id - Delete'),
    ('SUSN', 'User Id - New'),
    ('SWRG', 'Word Report Generation'),
    ('URRR', 'User/Workgroup Reassign by record'),
    ('URRT', 'User/Workgroup Reassign by type')
]


def _values(rows):
    return ", ".join(
        "(" + ", ".join("'" + str(v).replace("'", "''") + "'" for v in r) + ")"
        for r in rows
    )


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.audit_event_types (
          code       TEXT PRIMARY KEY,
          name       TEXT NOT NULL,
          category   TEXT,
          origin     TEXT NOT NULL DEFAULT 'viewpoint'
                     CHECK (origin IN ('viewpoint', 'g_flowdesk')),
          is_active  BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    native = _values([(c, n, cat, "g_flowdesk") for c, n, cat in _NATIVE])
    op.execute(
        "INSERT INTO public.audit_event_types (code, name, category, origin) "
        "VALUES " + native + " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name"
    )

    viewpoint = _values([(c, n, "viewpoint") for c, n in _VIEWPOINT])
    op.execute(
        "INSERT INTO public.audit_event_types (code, name, origin) "
        "VALUES " + viewpoint + " ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name"
    )

    # Denormalized context: every row answers who / what / which company on its
    # own. company_name survives deletion of the company it refers to.
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS action_label TEXT")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS company_name TEXT")

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_log_company_name "
        "ON public.audit_log (company_name)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_log_action_label "
        "ON public.audit_log (action_label)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.idx_audit_log_action_label")
    op.execute("DROP INDEX IF EXISTS public.idx_audit_log_company_name")
    op.execute("ALTER TABLE public.audit_log DROP COLUMN IF EXISTS company_name")
    op.execute("ALTER TABLE public.audit_log DROP COLUMN IF EXISTS action_label")
    op.execute("DROP TABLE IF EXISTS public.audit_event_types")
