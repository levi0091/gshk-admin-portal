"""The CR form contract — GENERATED, do not edit by hand.

Regenerate with `uv run python scripts/build_cr_form_contract.py`;
the decisions live in RULES there. `tests/test_cr_form_contract.py`
fails if any field on NAR1 or NNC1 is missing from this file.

294 fields across NAR1, NNC1.
"""

#: (form, xml path) -> (disposition, target-or-reason, mandatory, max_length)
FIELDS: dict[tuple[str, str], tuple[str, str, bool, int | None]] = {
    ('NAR1', 'submission/Eform/formModel/formCode'):
        ('form_instance', 'assigned by CR per submission', False, 20),
    ('NAR1', 'submission/Eform/formModel/language'):
        ('form_instance', 'filing language', True, 1),
    ('NAR1', 'submission/Eform/formModel/compNameE'):
        ('derived', "CR fills from the BR number after validation; entities.company_name is the profile's copy", False, 150),
    ('NAR1', 'submission/Eform/formModel/compNameC'):
        ('derived', 'as compNameE', False, 150),
    ('NAR1', 'submission/Eform/formModel/coyStatus'):
        ('mapped', 'entities.company_type', False, 1),
    ('NAR1', 'submission/Eform/formModel/brNo'):
        ('mapped', 'entities.br_number', True, 20),
    ('NAR1', 'submission/Eform/formModel/brName'):
        ('mapped', 'business_names.business_name', False, 150),
    ('NAR1', 'submission/Eform/formModel/nature'):
        ('mapped', 'entities.business_nature_code', False, 5),
    ('NAR1', 'submission/Eform/formModel/natureDesc'):
        ('derived', 'CR fills it from the code after web-form validation; we denormalise it from the seeded vocabulary so the facsimile PDF can print it', False, 160),
    ('NAR1', 'submission/Eform/formModel/yearAnnualReturn'):
        ('form_instance', 'which year this return covers', True, 4),
    ('NAR1', 'submission/Eform/formModel/dateReturnMadeUp'):
        ('form_instance', "the return's own made-up-to date", False, 10),
    ('NAR1', 'submission/Eform/formModel/dateReturnFrom'):
        ('form_instance', 'financial period of this return', True, 10),
    ('NAR1', 'submission/Eform/formModel/dateReturnTo'):
        ('form_instance', 'financial period of this return', True, 10),
    ('NAR1', 'submission/Eform/formModel/docReferenceNo'):
        ('form_instance', "CR's reference for a redelivered return", False, 20),
    ('NAR1', 'submission/Eform/formModel/roAddr/addrLangInd'):
        ('form_instance', "language of THIS filing's addresses; the profile stores one address, not one per language", True, 1),
    ('NAR1', 'submission/Eform/formModel/roAddr/flatFlrBlk'):
        ('mapped', 'addresses.line1', False, 60),
    ('NAR1', 'submission/Eform/formModel/roAddr/bldg'):
        ('mapped', 'addresses.line2', False, 60),
    ('NAR1', 'submission/Eform/formModel/roAddr/stEstLotVlg'):
        ('mapped', 'addresses.line3', False, 60),
    ('NAR1', 'submission/Eform/formModel/roAddr/dstCtyStatePostal'):
        ('mapped', 'addresses.city', False, 60),
    ('NAR1', 'submission/Eform/formModel/roAddr/ctryRegion'):
        ('mapped', 'addresses.country', True, 4),
    ('NAR1', 'submission/Eform/formModel/emailAddr'):
        ('unsourced', 'as email at (top)', False, 60),
    ('NAR1', 'submission/Eform/formModel/telNo'):
        ('mapped', 'contacts.contact_value', False, 8),
    ('NAR1', 'submission/Eform/formModel/totalAmountMortCharge'):
        ('mapped', 'entities.mortgages_total', False, 120),
    ('NAR1', 'submission/Eform/formModel/memberNumAtDateReturn'):
        ('derived', 'count of members at the return date, for companies with no share capital', False, 7),
    ('NAR1', 'submission/Eform/formModel/finStatAttachSpeRez'):
        ('form_instance', 'financial statement attachment', False, None),
    ('NAR1', 'submission/Eform/formModel/shareCapitals/shareCapital/clsOfShares'):
        ('mapped', 'share_classes.class_name', True, 100),
    ('NAR1', 'submission/Eform/formModel/shareCapitals/shareCapital/currency'):
        ('mapped', 'share_classes.currency', True, 3),
    ('NAR1', 'submission/Eform/formModel/shareCapitals/shareCapital/noOfShareIssuedOnThisCls'):
        ('mapped', 'share_classes.total_issued', True, 16),
    ('NAR1', 'submission/Eform/formModel/shareCapitals/shareCapital/issuedCapital'):
        ('mapped', 'share_classes.issued_amount', True, 16),
    ('NAR1', 'submission/Eform/formModel/shareCapitals/shareCapital/paidUpCapital'):
        ('mapped', 'share_classes.total_paid', True, 16),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/indvChiName'):
        ('mapped', 'persons.full_name_zh', False, 50),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/indvEngSname'):
        ('mapped', 'persons.surname', False, 50),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/indvEngOname'):
        ('mapped', 'persons.given_names', False, 110),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/indvPrevChiName'):
        ('mapped', 'persons.former_name_zh', False, 150),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/indvPrevEngName'):
        ('mapped', 'persons.former_name', False, 150),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/indvAlsChiName'):
        ('mapped', 'persons.alias_zh', False, 150),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/indvAlsEngName'):
        ('mapped', 'persons.alias_en', False, 150),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/stdAddress/addrLangInd'):
        ('form_instance', "language of THIS filing's addresses; the profile stores one address, not one per language", True, 60),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/stdAddress/flatFlrBlk'):
        ('mapped', 'addresses.line1', False, 60),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/stdAddress/bldg'):
        ('mapped', 'addresses.line2', False, 60),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/stdAddress/stEstLotVlg'):
        ('mapped', 'addresses.line3', False, 60),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/stdAddress/dstCtyStatePostal'):
        ('mapped', 'addresses.city', False, 60),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/stdAddress/ctryRegion'):
        ('mapped', 'addresses.country', True, 4),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/indvEmailAddr'):
        ('mapped', 'persons.email', False, 60),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/indvHkidNo'):
        ('derived', "CR's PARTIAL id: first half of the HKID, rounded up (A123456(7) -> A123)", False, 8),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/indvPptIssCtry'):
        ('mapped', 'person_identity_documents.issuing_country', False, 4),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/indvPptNo'):
        ('derived', "CR's PARTIAL passport number, as indvHkidNo", False, 25),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/tcspNo'):
        ('unsourced', "an individual secretary's own TCSP licence; no persons column holds it and Viewpoint's only %tcsp% matches are workflow-template flags", False, 20),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/exempted'):
        ('unsourced', 'as tcspNo on an individual secretary', False, 1),
    ('NAR1', 'submission/Eform/formModel/indSecList/indSec/reason'):
        ('unsourced', 'as tcspNo on an individual secretary', False, 350),
    ('NAR1', 'submission/Eform/formModel/corpSecList/corpSec/corpChiName'):
        ('mapped', 'entities.company_name_zh', False, 50),
    ('NAR1', 'submission/Eform/formModel/corpSecList/corpSec/corpEngName'):
        ('mapped', 'entities.company_name', False, 150),
    ('NAR1', 'submission/Eform/formModel/corpSecList/corpSec/stdAddress/addrLangInd'):
        ('form_instance', "language of THIS filing's addresses; the profile stores one address, not one per language", True, 60),
    ('NAR1', 'submission/Eform/formModel/corpSecList/corpSec/stdAddress/flatFlrBlk'):
        ('mapped', 'addresses.line1', False, 60),
    ('NAR1', 'submission/Eform/formModel/corpSecList/corpSec/stdAddress/bldg'):
        ('mapped', 'addresses.line2', False, 60),
    ('NAR1', 'submission/Eform/formModel/corpSecList/corpSec/stdAddress/stEstLotVlg'):
        ('mapped', 'addresses.line3', False, 60),
    ('NAR1', 'submission/Eform/formModel/corpSecList/corpSec/stdAddress/dstCtyStatePostal'):
        ('mapped', 'addresses.city', False, 60),
    ('NAR1', 'submission/Eform/formModel/corpSecList/corpSec/stdAddress/ctryRegion'):
        ('mapped', 'addresses.country', True, 4),
    ('NAR1', 'submission/Eform/formModel/corpSecList/corpSec/corpEmailAddr'):
        ('mapped', 'entities.email', False, 60),
    ('NAR1', 'submission/Eform/formModel/corpSecList/corpSec/corpBrNo'):
        ('mapped', 'entities.br_number', False, 20),
    ('NAR1', 'submission/Eform/formModel/corpSecList/corpSec/corpTcspNo'):
        ('mapped', 'entities.tcsp_licence_no', False, 20),
    ('NAR1', 'submission/Eform/formModel/corpSecList/corpSec/exempted'):
        ('derived', 'true exactly when tcsp_exemption_reason is set', False, 1),
    ('NAR1', 'submission/Eform/formModel/corpSecList/corpSec/reason'):
        ('mapped', 'entities.tcsp_exemption_reason', False, 350),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/dirInd'):
        ('derived', "true when the entity_officers row has role='director'", False, 1),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/altDirInd'):
        ('unsourced', "alternate directors: Viewpoint's only %alternate% columns are meeting-attendance codes", False, 1),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/altTo'):
        ('unsourced', 'as altDirInd', False, 72),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/indvChiName'):
        ('mapped', 'persons.full_name_zh', False, 50),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/indvEngSname'):
        ('mapped', 'persons.surname', False, 50),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/indvEngOname'):
        ('mapped', 'persons.given_names', False, 110),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/indvPrevChiName'):
        ('mapped', 'persons.former_name_zh', False, 150),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/indvPrevEngName'):
        ('mapped', 'persons.former_name', False, 150),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/indvAlsChiName'):
        ('mapped', 'persons.alias_zh', False, 150),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/indvAlsEngName'):
        ('mapped', 'persons.alias_en', False, 150),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/stdAddress/addrLangInd'):
        ('form_instance', "language of THIS filing's addresses; the profile stores one address, not one per language", True, 60),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/stdAddress/flatFlrBlk'):
        ('mapped', 'addresses.line1', False, 60),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/stdAddress/bldg'):
        ('mapped', 'addresses.line2', False, 60),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/stdAddress/stEstLotVlg'):
        ('mapped', 'addresses.line3', False, 60),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/stdAddress/dstCtyStatePostal'):
        ('mapped', 'addresses.city', False, 60),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/stdAddress/ctryRegion'):
        ('mapped', 'addresses.country', True, 4),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/indvEmailAddr'):
        ('mapped', 'persons.email', False, 60),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/indvHkidNo'):
        ('derived', "CR's PARTIAL id: first half of the HKID, rounded up (A123456(7) -> A123)", False, 8),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/indvPptIssCtry'):
        ('mapped', 'person_identity_documents.issuing_country', False, 4),
    ('NAR1', 'submission/Eform/formModel/indDirList/indDir/indvPptNo'):
        ('derived', "CR's PARTIAL passport number, as indvHkidNo", False, 25),
    ('NAR1', 'submission/Eform/formModel/corpDirList/corpDir/dirInd'):
        ('derived', "true when the entity_officers row has role='director'", False, 1),
    ('NAR1', 'submission/Eform/formModel/corpDirList/corpDir/altDirInd'):
        ('unsourced', "alternate directors: Viewpoint's only %alternate% columns are meeting-attendance codes", False, 1),
    ('NAR1', 'submission/Eform/formModel/corpDirList/corpDir/altTo'):
        ('unsourced', 'as altDirInd', False, 72),
    ('NAR1', 'submission/Eform/formModel/corpDirList/corpDir/corpChiName'):
        ('mapped', 'entities.company_name_zh', False, 50),
    ('NAR1', 'submission/Eform/formModel/corpDirList/corpDir/corpEngName'):
        ('mapped', 'entities.company_name', False, 150),
    ('NAR1', 'submission/Eform/formModel/corpDirList/corpDir/stdAddress/addrLangInd'):
        ('form_instance', "language of THIS filing's addresses; the profile stores one address, not one per language", True, 60),
    ('NAR1', 'submission/Eform/formModel/corpDirList/corpDir/stdAddress/flatFlrBlk'):
        ('mapped', 'addresses.line1', False, 60),
    ('NAR1', 'submission/Eform/formModel/corpDirList/corpDir/stdAddress/bldg'):
        ('mapped', 'addresses.line2', False, 60),
    ('NAR1', 'submission/Eform/formModel/corpDirList/corpDir/stdAddress/stEstLotVlg'):
        ('mapped', 'addresses.line3', False, 60),
    ('NAR1', 'submission/Eform/formModel/corpDirList/corpDir/stdAddress/dstCtyStatePostal'):
        ('mapped', 'addresses.city', False, 60),
    ('NAR1', 'submission/Eform/formModel/corpDirList/corpDir/stdAddress/ctryRegion'):
        ('mapped', 'addresses.country', True, 4),
    ('NAR1', 'submission/Eform/formModel/corpDirList/corpDir/corpEmailAddr'):
        ('mapped', 'entities.email', False, 60),
    ('NAR1', 'submission/Eform/formModel/corpDirList/corpDir/corpBrNo'):
        ('mapped', 'entities.br_number', False, 20),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/indvChiName'):
        ('mapped', 'persons.full_name_zh', False, 50),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/indvEngSname'):
        ('mapped', 'persons.surname', False, 50),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/indvEngOname'):
        ('mapped', 'persons.given_names', False, 110),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/indvPrevChiName'):
        ('mapped', 'persons.former_name_zh', False, 150),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/indvPrevEngName'):
        ('mapped', 'persons.former_name', False, 150),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/indvAlsChiName'):
        ('mapped', 'persons.alias_zh', False, 150),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/indvAlsEngName'):
        ('mapped', 'persons.alias_en', False, 150),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/stdAddress/addrLangInd'):
        ('form_instance', "language of THIS filing's addresses; the profile stores one address, not one per language", True, 60),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/stdAddress/flatFlrBlk'):
        ('mapped', 'addresses.line1', False, 60),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/stdAddress/bldg'):
        ('mapped', 'addresses.line2', False, 60),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/stdAddress/stEstLotVlg'):
        ('mapped', 'addresses.line3', False, 60),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/stdAddress/dstCtyStatePostal'):
        ('mapped', 'addresses.city', False, 60),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/stdAddress/ctryRegion'):
        ('mapped', 'addresses.country', True, 4),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/indvEmailAddr'):
        ('mapped', 'persons.email', False, 60),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/indvHkidNo'):
        ('derived', "CR's PARTIAL id: first half of the HKID, rounded up (A123456(7) -> A123)", False, 8),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/indvPptIssCtry'):
        ('mapped', 'person_identity_documents.issuing_country', False, 4),
    ('NAR1', 'submission/Eform/formModel/resDirList/resDir/indvPptNo'):
        ('derived', "CR's PARTIAL passport number, as indvHkidNo", False, 25),
    ('NAR1', 'submission/Eform/formModel/shareholderListedInSch1'):
        ('form_instance', 'which schedule carries the members', True, 1),
    ('NAR1', 'submission/Eform/formModel/shareholderListedInSch2'):
        ('form_instance', 'which schedule carries the members', True, 1),
    ('NAR1', 'submission/Eform/formModel/shareholderListedInCdrom'):
        ('form_instance', 'which schedule carries the members', True, 1),
    ('NAR1', 'submission/Eform/formModel/attachSpeRez'):
        ('form_instance', 'allottee spreadsheet attachment', False, None),
    ('NAR1', 'submission/Eform/formModel/companyRecord'):
        ('mapped', 'entity_record_locations.record_type', False, 456),
    ('NAR1', 'submission/Eform/formModel/address'):
        ('mapped', 'entity_record_locations.address_id', False, 696),
    ('NAR1', 'submission/Eform/formModel/associatedPersonId'):
        ('form_instance', 'individual signing for a body corporate', False, 16),
    ('NAR1', 'submission/Eform/formModel/associatedPersonName'):
        ('form_instance', 'individual signing for a body corporate', False, 150),
    ('NAR1', 'submission/Eform/formModel/associatedCapacityDesc'):
        ('form_instance', 'individual signing for a body corporate', False, 500),
    ('NAR1', 'submission/Eform/formModel/selectAssoBrNo'):
        ('form_instance', 'BR of the signing body corporate', False, 20),
    ('NAR1', 'submission/Eform/formModel/selectPersonId'):
        ('form_instance', "signatory's e-Service user id", True, 16),
    ('NAR1', 'submission/Eform/formModel/selectPersonName'):
        ('form_instance', 'signatory name', True, 150),
    ('NAR1', 'submission/Eform/formModel/selectCapacityDesc'):
        ('form_instance', 'signing capacity, per case', True, 500),
    ('NAR1', 'submission/Eform/formModel/signatoryDate'):
        ('form_instance', 'when this return was signed', True, 10),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/clsOfShares'):
        ('mapped', 'share_classes.class_name', True, 100),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/shareHolderGrps/shareHolderGrp/sharesAlloted'):
        ('mapped', 'shareholdings.shares_held', True, 16),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/shareHolderGrps/shareHolderGrp/shType'):
        ('mapped', 'shareholdings.party_type', True, 1),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/allotteeType'):
        ('mapped', 'shareholdings.party_type', True, 1),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/indvChiName'):
        ('mapped', 'persons.full_name_zh', False, 50),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/indvSurname'):
        ('mapped', 'persons.surname', False, 50),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/indvOtherName'):
        ('mapped', 'persons.given_names', False, 110),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/corpChiName'):
        ('mapped', 'entities.company_name_zh', False, 50),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/corpEngName'):
        ('mapped', 'entities.company_name', False, 150),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/allotteeAddr/addrLangInd'):
        ('form_instance', "language of THIS filing's addresses; the profile stores one address, not one per language", True, 60),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/allotteeAddr/flatFlrBlk'):
        ('mapped', 'addresses.line1', False, 60),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/allotteeAddr/bldg'):
        ('mapped', 'addresses.line2', False, 60),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/allotteeAddr/stEstLotVlg'):
        ('mapped', 'addresses.line3', False, 60),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/allotteeAddr/dstCtyStatePostal'):
        ('mapped', 'addresses.city', False, 60),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/allotteeAddr/ctryRegion'):
        ('mapped', 'addresses.country', True, 4),
    ('NAR1', 'submission/Eform/formModel/schedule1/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/remarks'):
        ('form_instance', 'free text about one allotment on one return', False, 100),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/clsOfShares'):
        ('mapped', 'share_classes.class_name', False, 100),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/shareHolderGrps/shareHolderGrp/sharesAlloted'):
        ('mapped', 'shareholdings.shares_held', True, 16),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/shareHolderGrps/shareHolderGrp/perOfShares'):
        ('derived', "this holding's shares over the class total", True, 3),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/shareHolderGrps/shareHolderGrp/shType'):
        ('mapped', 'shareholdings.party_type', True, 1),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/indvChiName'):
        ('mapped', 'persons.full_name_zh', False, 50),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/indvSurname'):
        ('mapped', 'persons.surname', False, 50),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/indvOtherName'):
        ('mapped', 'persons.given_names', False, 110),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/corpChiName'):
        ('mapped', 'entities.company_name_zh', False, 50),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/corpEngName'):
        ('mapped', 'entities.company_name', False, 150),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/allotteeAddr/addrLangInd'):
        ('form_instance', "language of THIS filing's addresses; the profile stores one address, not one per language", True, 60),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/allotteeAddr/flatFlrBlk'):
        ('mapped', 'addresses.line1', False, 60),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/allotteeAddr/bldg'):
        ('mapped', 'addresses.line2', False, 60),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/allotteeAddr/stEstLotVlg'):
        ('mapped', 'addresses.line3', False, 60),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/allotteeAddr/dstCtyStatePostal'):
        ('mapped', 'addresses.city', False, 60),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/allotteeAddr/ctryRegion'):
        ('mapped', 'addresses.country', True, 4),
    ('NAR1', 'submission/Eform/formModel/schedule2/shares/shareHolderGrps/shareHolderGrp/allotteeRec/allottee/remarks'):
        ('form_instance', 'free text about one allotment on one return', False, 100),
    ('NAR1', 'submission/EFormSignatures/Signature'):
        ('form_instance', 'CR XML signature', False, 4000),
    ('NAR1', 'submission/EFormSignatures/PinSign/UserCredentialHash'):
        ('form_instance', 'PIN-signing credential; never stored', False, 500),
    ('NAR1', 'submission/EFormSignatures/PinSign/UserSignature'):
        ('form_instance', 'PIN signature; never stored', False, 200),
    ('NAR1', 'submission/EFormSignatures/PinSign/EncryptionKey'):
        ('form_instance', 'PIN-signing key; never stored', False, 500),
    ('NAR1', 'submission/depositAccountNo'):
        ('form_instance', 'CR deposit account charged', False, 12),
    ('NNC1', 'submission/Eform/formModel/formCode'):
        ('form_instance', 'assigned by CR per submission', False, 20),
    ('NNC1', 'submission/Eform/formModel/language'):
        ('form_instance', 'filing language', True, 1),
    ('NNC1', 'submission/Eform/formModel/intendedEngName'):
        ('mapped', 'entities.company_name', False, 150),
    ('NNC1', 'submission/Eform/formModel/intendedChiName'):
        ('mapped', 'entities.company_name_zh', False, 150),
    ('NNC1', 'submission/Eform/formModel/coyStatus'):
        ('mapped', 'entities.company_type', True, 1),
    ('NNC1', 'submission/Eform/formModel/aaLang'):
        ('form_instance', 'articles language for this NNC1', True, 1),
    ('NNC1', 'submission/Eform/formModel/sampleAA'):
        ('form_instance', "whether CR's model articles are adopted", False, 1),
    ('NNC1', 'submission/Eform/formModel/proposedCoySecure'):
        ('form_instance', 'NNC1 delivery option', True, 5),
    ('NNC1', 'submission/Eform/formModel/fileEncode256'):
        ('form_instance', 'attachment digest', False, None),
    ('NNC1', 'submission/Eform/formModel/bnCode'):
        ('mapped', 'entities.business_nature_code', False, 20),
    ('NNC1', 'submission/Eform/formModel/bnDesc'):
        ('derived', 'as natureDesc', False, 150),
    ('NNC1', 'submission/Eform/formModel/stdAddress/flatFlrBlk'):
        ('mapped', 'addresses.line1', False, 60),
    ('NNC1', 'submission/Eform/formModel/stdAddress/bldg'):
        ('mapped', 'addresses.line2', False, 60),
    ('NNC1', 'submission/Eform/formModel/stdAddress/stEstLotVlg'):
        ('mapped', 'addresses.line3', False, 60),
    ('NNC1', 'submission/Eform/formModel/stdAddress/dstCtyStatePostal'):
        ('mapped', 'addresses.city', False, 60),
    ('NNC1', 'submission/Eform/formModel/stdAddress/ctryRegion'):
        ('mapped', 'addresses.country', True, 4),
    ('NNC1', 'submission/Eform/formModel/email'):
        ('unsourced', 'company-level email; no entity-level Email column in Entity, CR_Entity or RefMaster', False, 60),
    ('NNC1', 'submission/Eform/formModel/telNo'):
        ('mapped', 'contacts.contact_value', False, 8),
    ('NNC1', 'submission/Eform/formModel/shareCapitals/shareCapital/classOfShare'):
        ('mapped', 'share_classes.class_name', True, 100),
    ('NNC1', 'submission/Eform/formModel/shareCapitals/shareCapital/amt'):
        ('mapped', 'shareholdings.amount_paid', True, 12),
    ('NNC1', 'submission/Eform/formModel/shareCapitals/shareCapital/currCode'):
        ('mapped', 'share_classes.currency', True, 3),
    ('NNC1', 'submission/Eform/formModel/shareCapitals/shareCapital/issuedShareCapital'):
        ('mapped', 'share_classes.issued_amount', True, 14),
    ('NNC1', 'submission/Eform/formModel/shareCapitals/shareCapital/paidUpShareCapital'):
        ('mapped', 'share_classes.total_paid', True, 14),
    ('NNC1', 'submission/Eform/formModel/shareCapitals/shareCapital/remainUnpaid'):
        ('unsourced', 'no Viewpoint column matches %unpaid% in 1,563 tables; NNC1-mandatory, so the NNC1 build (R3) must answer it', True, 14),
    ('NNC1', 'submission/Eform/formModel/shareCapitals/shareCapital/particluarOfRights'):
        ('unsourced', "no Viewpoint column matches %rights%. CR's spelling, preserved", False, 350),
    ('NNC1', 'submission/Eform/formModel/shareHolderList/shareHolder/personType'):
        ('mapped', 'shareholdings.party_type', True, 1),
    ('NNC1', 'submission/Eform/formModel/shareHolderList/shareHolder/chiName'):
        ('mapped', 'persons.full_name_zh', False, 50),
    ('NNC1', 'submission/Eform/formModel/shareHolderList/shareHolder/engSurName'):
        ('mapped', 'persons.surname', False, 50),
    ('NNC1', 'submission/Eform/formModel/shareHolderList/shareHolder/engOtherName'):
        ('mapped', 'persons.given_names', False, 110),
    ('NNC1', 'submission/Eform/formModel/shareHolderList/shareHolder/engName'):
        ('mapped', 'entities.company_name', False, 150),
    ('NNC1', 'submission/Eform/formModel/shareHolderList/shareHolder/stdAddress/flatFlrBlk'):
        ('mapped', 'addresses.line1', False, 60),
    ('NNC1', 'submission/Eform/formModel/shareHolderList/shareHolder/stdAddress/bldg'):
        ('mapped', 'addresses.line2', False, 60),
    ('NNC1', 'submission/Eform/formModel/shareHolderList/shareHolder/stdAddress/stEstLotVlg'):
        ('mapped', 'addresses.line3', False, 60),
    ('NNC1', 'submission/Eform/formModel/shareHolderList/shareHolder/stdAddress/dstCtyStatePostal'):
        ('mapped', 'addresses.city', False, 60),
    ('NNC1', 'submission/Eform/formModel/shareHolderList/shareHolder/stdAddress/ctryRegion'):
        ('mapped', 'addresses.country', True, 4),
    ('NNC1', 'submission/Eform/formModel/shareHolderList/shareHolder/shareCapitalList/shareCapital/classOfShare'):
        ('mapped', 'share_classes.class_name', True, 100),
    ('NNC1', 'submission/Eform/formModel/shareHolderList/shareHolder/shareCapitalList/shareCapital/totalNo'):
        ('mapped', 'shareholdings.shares_held', True, 12),
    ('NNC1', 'submission/Eform/formModel/shareHolderList/shareHolder/shareCapitalList/shareCapital/currCode'):
        ('mapped', 'share_classes.currency', True, 3),
    ('NNC1', 'submission/Eform/formModel/shareHolderList/shareHolder/shareCapitalList/shareCapital/amt'):
        ('mapped', 'shareholdings.amount_paid', True, 14),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/chiName'):
        ('mapped', 'persons.full_name_zh', False, 50),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/surNameEng'):
        ('mapped', 'persons.surname', False, 50),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/otherNameEng'):
        ('mapped', 'persons.given_names', False, 110),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/prevNameChi'):
        ('mapped', 'persons.former_name_zh', False, 150),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/prevNameEng'):
        ('mapped', 'persons.former_name', False, 150),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/aliasNameChi'):
        ('mapped', 'persons.alias_zh', False, 150),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/aliasNameEng'):
        ('mapped', 'persons.alias_en', False, 150),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/correspondingAddress/flatFlrBlk'):
        ('mapped', 'addresses.line1', False, 60),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/correspondingAddress/bldg'):
        ('mapped', 'addresses.line2', False, 60),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/correspondingAddress/stEstLotVlg'):
        ('mapped', 'addresses.line3', False, 60),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/correspondingAddress/dstCtyStatePostal'):
        ('mapped', 'addresses.city', False, 60),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/correspondingAddress/ctryRegion'):
        ('mapped', 'addresses.country', True, 4),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/email'):
        ('mapped', 'persons.email', False, 60),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/hkid'):
        ('mapped', 'person_identity_documents.id_number', False, 8),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/hkidChkDtg'):
        ('derived', 'the parenthesised check digit of person_identity_documents.id_number', False, 1),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/passportCtry'):
        ('mapped', 'person_identity_documents.issuing_country', False, 4),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/passportNo'):
        ('mapped', 'person_identity_documents.id_number', False, 25),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/tcspNo'):
        ('unsourced', "an individual secretary's own TCSP licence; no persons column holds it and Viewpoint's only %tcsp% matches are workflow-template flags", False, 20),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/exempted'):
        ('unsourced', 'as tcspNo on an individual secretary', False, 1),
    ('NNC1', 'submission/Eform/formModel/indSecList/indSec/reason'):
        ('unsourced', 'as tcspNo on an individual secretary', False, 350),
    ('NNC1', 'submission/Eform/formModel/corpSecList/corpSec/chiName'):
        ('mapped', 'persons.full_name_zh', False, 50),
    ('NNC1', 'submission/Eform/formModel/corpSecList/corpSec/engName'):
        ('mapped', 'entities.company_name', False, 150),
    ('NNC1', 'submission/Eform/formModel/corpSecList/corpSec/correspondingAddress/flatFlrBlk'):
        ('mapped', 'addresses.line1', False, 60),
    ('NNC1', 'submission/Eform/formModel/corpSecList/corpSec/correspondingAddress/bldg'):
        ('mapped', 'addresses.line2', False, 60),
    ('NNC1', 'submission/Eform/formModel/corpSecList/corpSec/correspondingAddress/stEstLotVlg'):
        ('mapped', 'addresses.line3', False, 60),
    ('NNC1', 'submission/Eform/formModel/corpSecList/corpSec/correspondingAddress/dstCtyStatePostal'):
        ('mapped', 'addresses.city', False, 60),
    ('NNC1', 'submission/Eform/formModel/corpSecList/corpSec/correspondingAddress/ctryRegion'):
        ('mapped', 'addresses.country', True, 4),
    ('NNC1', 'submission/Eform/formModel/corpSecList/corpSec/email'):
        ('mapped', 'entities.email', False, 60),
    ('NNC1', 'submission/Eform/formModel/corpSecList/corpSec/ubino'):
        ('mapped', 'entities.br_number', False, 20),
    ('NNC1', 'submission/Eform/formModel/corpSecList/corpSec/tcspNo'):
        ('mapped', 'entities.tcsp_licence_no', False, 20),
    ('NNC1', 'submission/Eform/formModel/corpSecList/corpSec/exempted'):
        ('derived', 'true exactly when tcsp_exemption_reason is set', False, 1),
    ('NNC1', 'submission/Eform/formModel/corpSecList/corpSec/reason'):
        ('mapped', 'entities.tcsp_exemption_reason', False, 350),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/chiName'):
        ('mapped', 'persons.full_name_zh', False, 50),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/surNameEng'):
        ('mapped', 'persons.surname', False, 50),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/otherNameEng'):
        ('mapped', 'persons.given_names', False, 110),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/prevNameChi'):
        ('mapped', 'persons.former_name_zh', False, 150),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/prevNameEng'):
        ('mapped', 'persons.former_name', False, 150),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/aliasNameChi'):
        ('mapped', 'persons.alias_zh', False, 150),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/aliasNameEng'):
        ('mapped', 'persons.alias_en', False, 150),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/correspondingAddress/flatFlrBlk'):
        ('mapped', 'addresses.line1', False, 60),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/correspondingAddress/bldg'):
        ('mapped', 'addresses.line2', False, 60),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/correspondingAddress/stEstLotVlg'):
        ('mapped', 'addresses.line3', False, 60),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/correspondingAddress/dstCtyStatePostal'):
        ('mapped', 'addresses.city', False, 60),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/correspondingAddress/ctryRegion'):
        ('mapped', 'addresses.country', True, 4),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/email'):
        ('mapped', 'persons.email', False, 60),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/hkid'):
        ('mapped', 'person_identity_documents.id_number', False, 8),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/hkidChkDtg'):
        ('derived', 'the parenthesised check digit of person_identity_documents.id_number', False, 1),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/passportCtry'):
        ('mapped', 'person_identity_documents.issuing_country', False, 4),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/passportNo'):
        ('mapped', 'person_identity_documents.id_number', False, 25),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/consentSigned'):
        ('form_instance', 'consent to act, given for one incorporation', False, 1),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/selectPersonId'):
        ('form_instance', "signatory's e-Service user id", False, 16),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/selectPersonName'):
        ('form_instance', 'signatory name', False, 150),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/selectCapacityDesc'):
        ('form_instance', 'signing capacity, per case', False, 500),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/stdAddress/flatFlrBlk'):
        ('mapped', 'addresses.line1', False, 60),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/stdAddress/bldg'):
        ('mapped', 'addresses.line2', False, 60),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/stdAddress/stEstLotVlg'):
        ('mapped', 'addresses.line3', False, 60),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/stdAddress/dstCtyStatePostal'):
        ('mapped', 'addresses.city', False, 60),
    ('NNC1', 'submission/Eform/formModel/indDirList/indDir/stdAddress/ctryRegion'):
        ('mapped', 'addresses.country', True, 4),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/chiName'):
        ('mapped', 'persons.full_name_zh', False, 50),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/engName'):
        ('mapped', 'entities.company_name', False, 150),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/correspondingAddress/flatFlrBlk'):
        ('mapped', 'addresses.line1', False, 60),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/correspondingAddress/bldg'):
        ('mapped', 'addresses.line2', False, 60),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/correspondingAddress/stEstLotVlg'):
        ('mapped', 'addresses.line3', False, 60),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/correspondingAddress/dstCtyStatePostal'):
        ('mapped', 'addresses.city', False, 60),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/correspondingAddress/ctryRegion'):
        ('mapped', 'addresses.country', True, 4),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/email'):
        ('mapped', 'entities.email', False, 60),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/ubino'):
        ('mapped', 'entities.br_number', False, 20),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/consentSigned'):
        ('form_instance', 'consent to act, given for one incorporation', False, 1),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/associatedPersonId'):
        ('form_instance', 'individual signing for a body corporate', False, 16),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/associatedPersonName'):
        ('form_instance', 'individual signing for a body corporate', False, 150),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/associatedCapacityDesc'):
        ('form_instance', 'individual signing for a body corporate', False, 500),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/selectAssoBrNo'):
        ('form_instance', 'BR of the signing body corporate', False, 20),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/selectPersonName'):
        ('form_instance', 'signatory name', True, 150),
    ('NNC1', 'submission/Eform/formModel/corpDirList/corpDir/selectCapacityDesc'):
        ('form_instance', 'signing capacity, per case', True, 500),
    ('NNC1', 'submission/Eform/formModel/associatedPersonId'):
        ('form_instance', 'individual signing for a body corporate', False, 16),
    ('NNC1', 'submission/Eform/formModel/associatedPersonName'):
        ('form_instance', 'individual signing for a body corporate', False, 150),
    ('NNC1', 'submission/Eform/formModel/associatedCapacityDesc'):
        ('form_instance', 'individual signing for a body corporate', False, 500),
    ('NNC1', 'submission/Eform/formModel/selectAssoBrNo'):
        ('form_instance', 'BR of the signing body corporate', False, 20),
    ('NNC1', 'submission/Eform/formModel/selectPersonId'):
        ('form_instance', "signatory's e-Service user id", True, 16),
    ('NNC1', 'submission/Eform/formModel/selectPersonName'):
        ('form_instance', 'signatory name', True, 150),
    ('NNC1', 'submission/Eform/formModel/selectCapacityDesc'):
        ('form_instance', 'signing capacity, per case', True, 500),
    ('NNC1', 'submission/Eform/formModel/signatoryDate'):
        ('form_instance', 'when this return was signed', True, 10),
    ('NNC1', 'submission/Eform/formModel/brcYear'):
        ('form_instance', 'BR certificate term bought with this filing', True, 1),
    ('NNC1', 'submission/Eform/formDataSignatures/PinSign/UserCredentialHash'):
        ('form_instance', 'PIN-signing credential; never stored', False, 500),
    ('NNC1', 'submission/Eform/formDataSignatures/PinSign/UserSignature'):
        ('form_instance', 'PIN signature; never stored', False, 200),
    ('NNC1', 'submission/Eform/formDataSignatures/PinSign/EncryptionKey'):
        ('form_instance', 'PIN-signing key; never stored', False, 500),
    ('NNC1', 'submission/EFormSignatures/Signature'):
        ('form_instance', 'CR XML signature', False, 4000),
    ('NNC1', 'submission/EFormSignatures/PinSign/UserCredentialHash'):
        ('form_instance', 'PIN-signing credential; never stored', False, 500),
    ('NNC1', 'submission/EFormSignatures/PinSign/UserSignature'):
        ('form_instance', 'PIN signature; never stored', False, 200),
    ('NNC1', 'submission/EFormSignatures/PinSign/EncryptionKey'):
        ('form_instance', 'PIN-signing key; never stored', False, 500),
    ('NNC1', 'submission/depositAccountNo'):
        ('form_instance', 'CR deposit account charged', False, 12),
}


def disposition_for(form: str, path: str):
    """The disposition of one CR field, or None if nobody has ruled."""
    entry = FIELDS.get((form, path))
    return entry[0] if entry else None


def entry_for(form: str, path: str):
    """The full contract entry, or None."""
    return FIELDS.get((form, path))
