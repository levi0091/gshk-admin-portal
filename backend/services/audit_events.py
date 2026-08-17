"""Event codes for the audit trail — one vocabulary shared with Viewpoint.

A G-FlowDesk action reuses Viewpoint's own event code wherever Viewpoint has an
equivalent operation, so "Change Master File Details" means the same thing and
groups together whether it happened in Viewpoint in 2019 or in G-FlowDesk today.
Codes are only invented where Viewpoint has no equivalent (documents, the
client/corporate-party flags, TPSI).

`audit_log.event_code` is therefore the shared key across both sources, and
`audit_event_types` (migration 012) is the registry that gives each code its
generic action name. `action_type` remains the internal canonical type.

Which Viewpoint folder a company/person field belongs to decides the code — that
is exactly how Viewpoint logs it (ADC vs COC vs CMA vs CGC vs LRO).
"""
from typing import Optional

# ---- Viewpoint codes reused by G-FlowDesk ---------------------------------
VP_NEW_MASTER_FILE = "ADN"    # New Master File            (company / person created)
VP_MASTER_DETAILS = "ADC"     # Change Master File Details (names, contact)
VP_STATUTORY = "COC"          # Change Entity Statutory Information
VP_MA_DATES = "CMA"           # Entity M&A Information Changed (AR / AGM / AoA)
VP_GENERAL = "CGC"            # Entity General Info. Changed
VP_REG_OFFICE = "LRO"         # Change Location of Registered Office
VP_COMPLIANCE = "CPC"         # Change Compliance Details  (person KYC fields)

VP_OFFICER_APPOINT = "OFA"    # Statutory Officer (Director/Secretary) Appointment
VP_OFFICER_CHANGE = "OFC"     # Statutory Officer (Director/Secr) Changed/Edit
VP_OFFICER_DELETE = "OFD"     # Statutory Officer (Director/Secr) Deleted

VP_OWNER_NEW = "OCAN"         # Owners & Controllers Actions - New
VP_OWNER_EDIT = "OCAE"        # Owners & Controllers Actions - Edit
VP_OWNER_DELETE = "OCAD"      # Owners & Controllers Actions - Delete

VP_SHARE_ISSUE = "SHA"        # Share Issue
VP_SHAREHOLDER_CHANGE = "SMP"  # Shareholders - Change of Particulars

# ---- G-FlowDesk-only codes (Viewpoint has no equivalent) -------------------
GF_SHAREHOLDER_REMOVED = "GF_SHAREHOLDER_REMOVED"
GF_FLAGS_CHANGED = "GF_FLAGS_CHANGED"
GF_DOC_UPLOADED = "GF_DOC_UPLOADED"
GF_DOC_VERSION = "GF_DOC_VERSION"
GF_DOC_DELETED = "GF_DOC_DELETED"

# ---- TPSI codes (CR e-Filing transport) ------------------------------------
#   Their own family rather than the GF_ prefix: TPSI is a distinct source
#   system, and that should read at a glance in the audit UI.
TPSI_AUTH = "TPSI_AUTH"
TPSI_FILING_CREATED = "TPSI_FILING_CREATED"
TPSI_VALIDATE = "TPSI_VALIDATE"
TPSI_SIGN = "TPSI_SIGN"
TPSI_EDRIVE = "TPSI_EDRIVE"
TPSI_PREVIEWED = "TPSI_PREVIEWED"
# Submit-lifecycle events reuse the TPSI_SUBMISSION_* codes migration 012
# already seeded — that family is CLAUDE.md-mandated (PBI-11 audit event
# table) and wired into the frontend label maps (AuditTrailTab.jsx,
# AuditLogPage.jsx). Exposed here under the same names, not a TPSI_SUBMIT_*
# near-duplicate, so later tasks import one canonical constant.
TPSI_SUBMISSION_ATTEMPTED = "TPSI_SUBMISSION_ATTEMPTED"
TPSI_SUBMISSION_SUCCESS = "TPSI_SUBMISSION_SUCCESS"
TPSI_SUBMISSION_FAILED = "TPSI_SUBMISSION_FAILED"
TPSI_BALANCE_CHECK = "TPSI_BALANCE_CHECK"
TPSI_STATUS = "TPSI_STATUS"
TPSI_CRED_SET = "TPSI_CRED_SET"
TPSI_CRED_ROTATE = "TPSI_CRED_ROTATE"
TPSI_PW_CHANGE = "TPSI_PW_CHANGE"
TPSI_CRED_CONFIG = "TPSI_CRED_CONFIG"

# ---- NAR1 case-workflow codes (BE-4) ---------------------------------------
#   Named, not invented: CASE_STATUS_CHANGED, CASE_FIELD_UPDATED and
#   AML_STATUS_CHANGED are the action_type values CLAUDE.md's PBI-11 audit
#   table already mandates, and all three are seeded in audit_event_types --
#   confirmed live against DEV (2026-08-16) via a direct REST query, which
#   also returned the other three PBI-11 codes (DOCUMENT_GENERATED,
#   EMAIL_SENT, CLIENT_APPROVAL_RECEIVED). NOTE: this repo's checked-in copy
#   of alembic/versions/012_pbi39_audit_event_types.py does NOT contain
#   CASE_STATUS_CHANGED or CASE_FIELD_UPDATED in its _NATIVE list, and no
#   other migration file inserts them either -- DEV has rows no migration in
#   this checkout accounts for. Flagged to Levi as a migration-history/DEV
#   drift question; not a blocker for this task, since the values only need
#   to match what is live.
CASE_STATUS_CHANGED = "CASE_STATUS_CHANGED"
CASE_FIELD_UPDATED = "CASE_FIELD_UPDATED"
AML_STATUS_CHANGED = "AML_STATUS_CHANGED"

# ---- Document generation (BE-2) --------------------------------------------
#   CLAUDE.md's PBI-11 table mandates this action_type for "any document (AoA,
#   FWR, NNC1, CoI, NAR1) generated". Already seeded in audit_event_types by
#   migration 012 (_NATIVE list, "Document Generated"/document), so exposing it
#   here needs no new migration -- it only gives callers one canonical constant
#   instead of a string literal per call site.
DOCUMENT_GENERATED = "DOCUMENT_GENERATED"

# Company field -> the Viewpoint folder that owns it.
_COMPANY_FIELD_CODES = {
    # Master file (names)
    "company_name": VP_MASTER_DETAILS,
    "company_name_zh": VP_MASTER_DETAILS,
    "previous_name": VP_MASTER_DETAILS,
    "name_language": VP_MASTER_DETAILS,
    # Statutory folder
    "br_number": VP_STATUTORY,
    "cr_number": VP_STATUTORY,
    "company_type": VP_STATUTORY,
    "incorporation_date": VP_STATUTORY,
    "incorporation_place": VP_STATUTORY,
    "tcsp_licence_no": VP_STATUTORY,
    "tcsp_exemption_reason": VP_STATUTORY,
    "date_name_changed": VP_STATUTORY,
    # M&A / dates folder
    "ar_last_date": VP_MA_DATES,
    "ar_next_date": VP_MA_DATES,
    "ar_due_date": VP_MA_DATES,
    "agm_next_date": VP_MA_DATES,
    "aoa_director_min": VP_MA_DATES,
    "aoa_director_max": VP_MA_DATES,
    "aoa_agm_waived": VP_MA_DATES,
    # Registered office
    "registered_address_id": VP_REG_OFFICE,
    # General folder
    "case_notes": VP_GENERAL,
    "assigned_to": VP_GENERAL,
    "active_workflow": VP_GENERAL,
    "status": VP_GENERAL,
}

# Person field -> Viewpoint folder. KYC/compliance fields are logged as CPC in
# Viewpoint; names and contact details as ADC.
_PERSON_FIELD_CODES = {
    "full_name": VP_MASTER_DETAILS,
    "given_names": VP_MASTER_DETAILS,
    "surname": VP_MASTER_DETAILS,
    "full_name_zh": VP_MASTER_DETAILS,
    "former_name": VP_MASTER_DETAILS,
    "email": VP_MASTER_DETAILS,
    "phone": VP_MASTER_DETAILS,
    "residential_address_id": VP_MASTER_DETAILS,
    "date_of_birth": VP_COMPLIANCE,
    "gender": VP_COMPLIANCE,
    "nationality": VP_COMPLIANCE,
    "nationality_code": VP_COMPLIANCE,
    "nationality_origin": VP_COMPLIANCE,
    "occupation": VP_COMPLIANCE,
    "place_of_birth": VP_COMPLIANCE,
    "marital_status": VP_COMPLIANCE,
    "date_of_death": VP_COMPLIANCE,
}

# (relation, operation) -> code. Officers and secretaries are both statutory
# officers in Viewpoint, so they share the OF* codes.
_PARTY_CODES = {
    ("officers", "link"): VP_OFFICER_APPOINT,
    ("officers", "update"): VP_OFFICER_CHANGE,
    ("officers", "unlink"): VP_OFFICER_DELETE,
    ("secretaries", "link"): VP_OFFICER_APPOINT,
    ("secretaries", "update"): VP_OFFICER_CHANGE,
    ("secretaries", "unlink"): VP_OFFICER_DELETE,
    ("beneficial-owners", "link"): VP_OWNER_NEW,
    ("beneficial-owners", "update"): VP_OWNER_EDIT,
    ("beneficial-owners", "unlink"): VP_OWNER_DELETE,
    ("shareholders", "link"): VP_SHARE_ISSUE,
    ("shareholders", "update"): VP_SHAREHOLDER_CHANGE,
    # Viewpoint has no "member removed" event — shareholders leave via share
    # transfers, which G-FlowDesk does not model yet.
    ("shareholders", "unlink"): GF_SHAREHOLDER_REMOVED,
}


def company_field_code(field: str) -> str:
    return _COMPANY_FIELD_CODES.get(field, VP_GENERAL)


def person_field_code(field: str) -> str:
    return _PERSON_FIELD_CODES.get(field, VP_MASTER_DETAILS)


def party_code(relation: str, operation: str) -> Optional[str]:
    return _PARTY_CODES.get((relation, operation))
