"""PBI-41: field-label dictionary for decoding Viewpoint audit events.

Viewpoint packs every change into EventLog.EventString as a key=value blob,
keyed by raw DB column names (DateLastAnRe, AdNrSR, IncorpNr). Rendering those
to a user is useless. Viewpoint's own UI dictionary (lng_VpSysFields_ENG) maps
column -> caption; those captions are lifted here, so the audit trail says
"Last Annual Return" and not "DateLastAnRe".

Only the 188 fields that ever actually change in the live EventLog are covered;
of those, the Viewpoint internal document/checklist flags (*chk*, VPC.*) are
deliberately absent and are suppressed in code -- they are what made the trail
unreadable in the first place.

Revision ID: 014
Revises: 013
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None

FIELD_LABELS = {
    'DateEffective': 'Effective Date',
    'FQNumber': 'Form Reference',
    'GeneratedOn': 'Generated On',
    'IdType': 'Identity Document Type',
    'ReportName': 'Report',
    'State': 'State/Province',
    'TransDescr': 'Transaction',
    'DateANR': 'Annual Return Date',
    'EntName': 'Company Name',
    'FQnumber': 'Form Reference',
    'FormName': 'Form',
    'IdNumber': 'Identity Document Number',
    'NrShare': 'Number of Shares',
    'OfficerTitle': 'Officer Title',
    'ShareClass': 'Share Class',
    'Active': 'Active',
    'AdCode': 'Additional Text',
    'AdFmCode': 'Address Format',
    'AdLine': 'Address Line',
    'AdNrBA': 'Business Address',
    'AdNrMA': 'Mailing Address',
    'AdNrRA': 'Residential Address',
    'AdNrRC': 'Correspondence Address',
    'AdNrRO': 'Registered Office of Master File',
    'AdNrS1': 'Copy of Permitted Indemnity Provision',
    'AdNrS2': 'Copy of Management Contract',
    'AdNrS3': 'Register of Particulars Referred to in section 384',
    'AdNrSA': 'Copies of Instruments Creating Charges',
    'AdNrSB': 'Principal Place of Business',
    'AdNrSC': 'Register of Charges',
    'AdNrSD': 'Register of Debenture Holders',
    'AdNrSG': 'Register of Company Secretaries',
    'AdNrSH': 'Register of Directors',
    'AdNrSI': 'Minute Book',
    'AdNrSM': 'Register of Members',
    'AdNrSO': 'Register of Directors/Secretaries',
    'AdNrSQ': 'Significant Controllers Register',
    'AdNrSR': 'Registered Office of Company',
    'AdNrSS': 'Location of Common Seal',
    'AdNrST': 'Location of Duplicate Seal',
    'AdNrSU': 'Company Stamp',
    'AddrCode': 'Party',
    'AddrNr': 'Address Card',
    'Address': 'Address',
    'Address2': 'Address 2',
    'Address3': 'Address 3',
    'Address4': 'Address 4',
    'Address5': 'Address 5',
    'AdminCode': 'Administrator',
    'Aliases': 'Aliases',
    'Allotc': 'Allotment (called)',
    'Alloto': 'Allotment (outstanding)',
    'AppliedChnsName': 'Chinese Name(s)',
    'AppliedName': 'Name(s) Requested',
    'BAddrNr': 'Business Address',
    'BenOwner': 'Beneficial Owner',
    'BusName': 'Business Name',
    'BusRegNr': 'Registration Number',
    'BusRegType': 'Type',
    'CA': 'Accounting',
    'CL': 'Client/Group',
    'CP': 'Identity Details/Register',
    'CS': 'Entity Administration',
    'CapAmt': 'Capital Amount',
    'CapCur': 'Capital Currency',
    'Capital': 'Share Capital',
    'ChangeStatus': 'Status',
    'ChineseBusName': 'Chinese Business Name',
    'ChnsFormerGivenNames': 'Chinese Former Given Names',
    'ChnsGivenName': 'Chinese Given Name',
    'ChnsName': 'Chinese Name',
    'City': 'City',
    'CityNr': 'City',
    'Contact': 'Contact',
    'ContactEB': 'Contact',
    'Country': 'Country',
    'Customized': 'Customised',
    'DateApplied': 'Date Applied',
    'DateAppoint': 'Date Appointed',
    'DateCessation': 'Cessation Date',
    'DateConfirmed': 'Effective Date',
    'DateDueAGM': 'AGM - Date Due',
    'DateDueAnRe': 'Annual Return - Date Due',
    'DateEntered': 'Date Entered',
    'DateExpire': 'Expiry Date',
    'DateLastAGM': 'AGM - Date Last',
    'DateLastAnRe': 'Annual Return - Date Last',
    'DateNextAGM': 'AGM - Date Next',
    'DateNextAnRe': 'Annual Return - Date Next',
    'DateRegistration': 'Registration Date',
    'DateRenew': 'Renewal Date',
    'DateResign': 'Date Resigned',
    'DateSigned': 'Signed',
    'Description': 'Description',
    'Effective': 'Effective Date',
    'Email': 'E-mail Address',
    'EmployerMf': 'Company/Employer',
    'EntClient': 'Client/Group',
    'EntType': 'Entity Type',
    'ExchRate': 'Exchange Rate',
    'FieldDetails': 'Note/Errors',
    'FirstOf': 'First Director?',
    'Freeze': 'Freeze Share Class',
    'FromDate': 'From Date',
    'Gender': 'Gender',
    'GivenNames': 'Given Names',
    'IDcardDateIssue': 'Date of Issue',
    'IDcardNr': 'ID Card Number',
    'IdCode': 'Identity Document Number',
    'IncorpDate': 'Date of Incorporation',
    'IncorpNr': 'Incorporation Number',
    'IncorpPlace': 'Jurisdiction',
    'Initials': 'Initials/First Name',
    'IsStatutory': 'Statutory',
    'KY': 'CDD Required',
    'KYC_NextReview': 'Date Next Review',
    'KYC_Reviewed': 'Date Last Reviewed',
    'KeyInfo': 'Key Information',
    'MA_Purpose': 'Purpose of Company',
    'MFLink1': 'Associated Master File',
    'MFLinkCaption1': 'Caption',
    'Name': 'Name',
    'NameFormat': 'Use Name Format',
    'Nationality': 'Nationality',
    'NationalityOrigin': 'Nationality of Origin',
    'Note': 'Note',
    'OC': 'Statutory/Trust/Foundation Officer',
    'Occupation': 'Occupation',
    'OfficerText': 'Officer Title',
    'OfficerType': 'Officer Type',
    'PR': 'Relation',
    'PasDateExpire': 'Date of Expiry',
    'PasDateIssue': 'Date of Issue',
    'PasPlaceIssue': 'Passport Place of Issue',
    'PassportNr': 'Passport No.',
    'Position': 'Position',
    'PostalCode': 'Postcode [PC]',
    'PostalPos': 'Position postal code in address',
    'PrincipleBNR': 'Is Principal?',
    'RM': 'Time & Billing flag',
    'ReasonResign': 'Reason for Resignation',
    'RefType': 'Master File Type',
    'ReminderDate': 'Reminder Date',
    'SH': 'Shareholder/Partner/Interest Holder',
    'SearchName': 'Search Name',
    'ShareClassName': 'Class Name',
    'Stat': 'Status',
    'Status': 'Entity Status',
    'SubStatus': 'Entity Sub-Status',
    'SuperVisor': 'Supervisor',
    'TR': 'Supplier (Purchase Ledger)',
    'Title': 'Title',
    'ToDate': 'To Date',
    'TransDate': 'Transaction Date',
    'TransferDate': 'Effective Date',
    'Ucode': 'User Code',
    'UdCode': 'User Table Code 1',
    'UpdateVals': 'Update To',
    'UpdatedFields': 'Description from Tag Values',
    'UseCertNrs': 'Use Certificate Numbers',
    'UserText1': 'Principal Activities',
    'VotesPerShare': 'Votes per Share',
}



def upgrade() -> None:
    op.create_table(
        "audit_field_labels",
        sa.Column("field", sa.Text, primary_key=True),
        sa.Column("label", sa.Text, nullable=False),
    )
    op.bulk_insert(
        sa.table("audit_field_labels", sa.column("field", sa.Text), sa.column("label", sa.Text)),
        [{"field": f, "label": l} for f, l in FIELD_LABELS.items()],
    )
    # Human-readable summary of what changed, derived from EventString.
    op.add_column("audit_log", sa.Column("changed_fields", postgresql.JSONB, nullable=True))

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                GRANT SELECT ON audit_field_labels TO authenticated;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
                GRANT SELECT ON audit_field_labels TO service_role;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_column("audit_log", "changed_fields")
    op.drop_table("audit_field_labels")
