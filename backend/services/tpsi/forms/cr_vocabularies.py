"""CR's controlled vocabularies for the NAR1 — countries and signing capacities.

PROVENANCE
    Workbook : docs/Web Form Example/Worksheet in TPSI API Interface v1.0.14.xlsx
    Version  : worksheet v1.0.14 (the version shipped with the TPSI API pack)
    Sheets   : "Country & Region"        -> _COUNTRY_ROWS   (250 data rows)
               "Capacity (Individual)"   -> CAPACITY_INDIVIDUAL
               "Capacity (Body Coporate)" -> CAPACITY_BODY_CORPORATE
                 ^ CR's own sheet name, misspelt in the workbook. Kept verbatim
                   so anyone re-extracting finds the sheet.
    Extracted 2026-08-17 with openpyxl (already a dev dependency) and re-verified
    row-for-row by tests/tpsi/test_nar1_mapper.py, which re-reads the workbook.

WHY A COMMITTED TABLE AND NOT AN ISO LIBRARY
    CR's list is NOT plain ISO 3166-1 alpha-3. Three codes are CR's own:

        GBR1  GUERNSEY        (ISO would say GGY)
        GBR2  JERSEY          (ISO would say JEY)
        GBR3  ISLE OF MAN     (ISO would say IMN)

    That is why ctryRegion is max_length 4 rather than 3. A generic ISO library
    emits GGY / JEY / IMN and CR rejects them, so this sheet — not a library —
    is the authority on what CR accepts. (XKS / REPUBLIC OF KOSOVO is also
    outside the ISO 3166-1 standard proper, but it is the code Windows and .NET
    use for XK, so it is not a CR invention.)

    The alpha-2 column is what G-FlowDesk actually stores: DEV's `addresses`
    table holds ISO alpha-2 ("VN", "AE", "GB") in 100% of its non-blank rows.
    Every alpha-2 here is carried on the same line as the CR code it resolves
    to, so an alpha-2 cannot name a code CR does not have — the mapping is
    structural, not a second table that can drift. It was cross-checked against
    .NET's System.Globalization.RegionInfo (an independent offline source, used
    for verification only — no dependency added): zero disagreements over the
    244 rows .NET covers.

    GG -> GBR1, JE -> GBR2, IM -> GBR3. Never GBR.
"""

#: (CR code, CR English description, ISO 3166-1 alpha-2). Verbatim from the
#: "Country & Region" sheet; the Chinese description column is not used because
#: the NAR1 is filed with language "E".
_COUNTRY_ROWS: tuple[tuple[str, str, str], ...] = (
    ("ABW", "ARUBA", "AW"),
    ("AFG", "AFGHANISTAN", "AF"),
    ("AGO", "ANGOLA", "AO"),
    ("AIA", "ANGUILLA", "AI"),
    ("ALA", "ALAND ISLANDS", "AX"),
    ("ALB", "ALBANIA", "AL"),
    ("AND", "ANDORRA", "AD"),
    ("ARE", "UNITED ARAB EMIRATES", "AE"),
    ("ARG", "ARGENTINA", "AR"),
    ("ARM", "ARMENIA", "AM"),
    ("ASM", "AMERICAN SAMOA", "AS"),
    ("ATA", "ANTARCTICA", "AQ"),
    ("ATF", "FRENCH SOUTHERN TERRITORIES", "TF"),
    ("ATG", "ANTIGUA AND BARBUDA", "AG"),
    ("AUS", "AUSTRALIA", "AU"),
    ("AUT", "AUSTRIA", "AT"),
    ("AZE", "AZERBAIJAN", "AZ"),
    ("BDI", "BURUNDI", "BI"),
    ("BEL", "BELGIUM", "BE"),
    ("BEN", "BENIN", "BJ"),
    ("BES", "BONAIRE, SINT EUSTATIUS AND SABA", "BQ"),
    ("BFA", "BURKINA FASO", "BF"),
    ("BGD", "BANGLADESH", "BD"),
    ("BGR", "BULGARIA", "BG"),
    ("BHR", "BAHRAIN", "BH"),
    ("BHS", "BAHAMAS", "BS"),
    ("BIH", "BOSNIA AND HERZEGOVINA", "BA"),
    ("BLM", "SAINT BARTHELEMY", "BL"),
    ("BLR", "BELARUS", "BY"),
    ("BLZ", "BELIZE", "BZ"),
    ("BMU", "BERMUDA", "BM"),
    ("BOL", "BOLIVIA", "BO"),
    ("BRA", "BRAZIL", "BR"),
    ("BRB", "BARBADOS", "BB"),
    ("BRN", "BRUNEI DARUSSALAM", "BN"),
    ("BTN", "BHUTAN", "BT"),
    ("BVT", "BOUVET ISLAND", "BV"),
    ("BWA", "BOTSWANA", "BW"),
    ("CAF", "CENTRAL AFRICAN REPUBLIC", "CF"),
    ("CAN", "CANADA", "CA"),
    ("CCK", "COCOS (KEELING) ISLANDS", "CC"),
    ("CHE", "SWITZERLAND", "CH"),
    ("CHL", "CHILE", "CL"),
    ("CHN", "CHINA", "CN"),
    ("CIV", "COTE D'IVOIRE", "CI"),
    ("CMR", "CAMEROON", "CM"),
    ("COD", "DEMOCRATIC REPUBLIC OF THE CONGO", "CD"),
    ("COG", "CONGO", "CG"),
    ("COK", "COOK ISLANDS", "CK"),
    ("COL", "COLOMBIA", "CO"),
    ("COM", "COMOROS", "KM"),
    ("CPV", "CAPE VERDE", "CV"),
    ("CRI", "COSTA RICA", "CR"),
    ("CUB", "CUBA", "CU"),
    ("CUW", "CURACAO", "CW"),
    ("CXR", "CHRISTMAS ISLAND", "CX"),
    ("CYM", "CAYMAN ISLANDS", "KY"),
    ("CYP", "CYPRUS", "CY"),
    ("CZE", "CZECH REPUBLIC", "CZ"),
    ("DEU", "GERMANY", "DE"),
    ("DJI", "DJIBOUTI", "DJ"),
    ("DMA", "DOMINICA", "DM"),
    ("DNK", "DENMARK", "DK"),
    ("DOM", "DOMINICAN REPUBLIC", "DO"),
    ("DZA", "ALGERIA", "DZ"),
    ("ECU", "ECUADOR", "EC"),
    ("EGY", "EGYPT", "EG"),
    ("ERI", "ERITREA", "ER"),
    ("ESH", "WESTERN SAHARA", "EH"),
    ("ESP", "SPAIN", "ES"),
    ("EST", "ESTONIA", "EE"),
    ("ETH", "ETHIOPIA", "ET"),
    ("FIN", "FINLAND", "FI"),
    ("FJI", "FIJI", "FJ"),
    ("FLK", "FALKLAND ISLANDS (MALVINAS)", "FK"),
    ("FRA", "FRANCE", "FR"),
    ("FRO", "FAROE ISLANDS", "FO"),
    ("FSM", "FEDERATED STATES OF MICRONESIA", "FM"),
    ("GAB", "GABON", "GA"),
    ("GBR", "UNITED KINGDOM", "GB"),
    ("GBR1", "GUERNSEY", "GG"),
    ("GBR2", "JERSEY", "JE"),
    ("GBR3", "ISLE OF MAN", "IM"),
    ("GEO", "GEORGIA", "GE"),
    ("GHA", "GHANA", "GH"),
    ("GIB", "GIBRALTAR", "GI"),
    ("GIN", "GUINEA", "GN"),
    ("GLP", "GUADELOUPE", "GP"),
    ("GMB", "GAMBIA", "GM"),
    ("GNB", "GUINEA-BISSAU", "GW"),
    ("GNQ", "EQUATORIAL GUINEA", "GQ"),
    ("GRC", "GREECE", "GR"),
    ("GRD", "GRENADA", "GD"),
    ("GRL", "GREENLAND", "GL"),
    ("GTM", "GUATEMALA", "GT"),
    ("GUF", "FRENCH GUIANA", "GF"),
    ("GUM", "GUAM", "GU"),
    ("GUY", "GUYANA", "GY"),
    ("HKG", "HONG KONG", "HK"),
    ("HMD", "HEARD ISLAND AND MCDONALD ISLANDS", "HM"),
    ("HND", "HONDURAS", "HN"),
    ("HRV", "CROATIA", "HR"),
    ("HTI", "HAITI", "HT"),
    ("HUN", "HUNGARY", "HU"),
    ("IDN", "INDONESIA", "ID"),
    ("IND", "INDIA", "IN"),
    ("IOT", "BRITISH INDIAN OCEAN TERRITORY", "IO"),
    ("IRL", "IRELAND", "IE"),
    ("IRN", "ISLAMIC REPUBLIC OF IRAN", "IR"),
    ("IRQ", "IRAQ", "IQ"),
    ("ISL", "ICELAND", "IS"),
    ("ISR", "ISRAEL", "IL"),
    ("ITA", "ITALY", "IT"),
    ("JAM", "JAMAICA", "JM"),
    ("JOR", "JORDAN", "JO"),
    ("JPN", "JAPAN", "JP"),
    ("KAZ", "KAZAKHSTAN", "KZ"),
    ("KEN", "KENYA", "KE"),
    ("KGZ", "KYRGYZSTAN", "KG"),
    ("KHM", "CAMBODIA", "KH"),
    ("KIR", "KIRIBATI", "KI"),
    ("KNA", "SAINT KITTS AND NEVIS", "KN"),
    ("KOR", "REPUBLIC OF KOREA", "KR"),
    ("KWT", "KUWAIT", "KW"),
    ("LAO", "LAO PEOPLE'S DEMOCRATIC REPUBLIC", "LA"),
    ("LBN", "LEBANON", "LB"),
    ("LBR", "LIBERIA", "LR"),
    ("LBY", "LIBYA", "LY"),
    ("LCA", "SAINT LUCIA", "LC"),
    ("LIE", "LIECHTENSTEIN", "LI"),
    ("LKA", "SRI LANKA", "LK"),
    ("LSO", "LESOTHO", "LS"),
    ("LTU", "LITHUANIA", "LT"),
    ("LUX", "LUXEMBOURG", "LU"),
    ("LVA", "LATVIA", "LV"),
    ("MAC", "MACAU", "MO"),
    ("MAF", "SAINT MARTIN", "MF"),
    ("MAR", "MOROCCO", "MA"),
    ("MCO", "MONACO", "MC"),
    ("MDA", "REPUBLIC OF MOLDOVA", "MD"),
    ("MDG", "MADAGASCAR", "MG"),
    ("MDV", "MALDIVES", "MV"),
    ("MEX", "MEXICO", "MX"),
    ("MHL", "MARSHALL ISLANDS", "MH"),
    ("MKD", "MACEDONIA", "MK"),
    ("MLI", "MALI", "ML"),
    ("MLT", "MALTA", "MT"),
    ("MMR", "MYANMAR", "MM"),
    ("MNE", "MONTENEGRO", "ME"),
    ("MNG", "MONGOLIA", "MN"),
    ("MNP", "NORTHERN MARIANA ISLANDS", "MP"),
    ("MOZ", "MOZAMBIQUE", "MZ"),
    ("MRT", "MAURITANIA", "MR"),
    ("MSR", "MONTSERRAT", "MS"),
    ("MTQ", "MARTINIQUE", "MQ"),
    ("MUS", "MAURITIUS", "MU"),
    ("MWI", "MALAWI", "MW"),
    ("MYS", "MALAYSIA", "MY"),
    ("MYT", "MAYOTTE", "YT"),
    ("NAM", "NAMIBIA", "NA"),
    ("NCL", "NEW CALEDONIA", "NC"),
    ("NER", "NIGER", "NE"),
    ("NFK", "NORFOLK ISLAND", "NF"),
    ("NGA", "NIGERIA", "NG"),
    ("NIC", "NICARAGUA", "NI"),
    ("NIU", "NIUE", "NU"),
    ("NLD", "NETHERLANDS", "NL"),
    ("NOR", "NORWAY", "NO"),
    ("NPL", "NEPAL", "NP"),
    ("NRU", "NAURU", "NR"),
    ("NZL", "NEW ZEALAND", "NZ"),
    ("OMN", "OMAN", "OM"),
    ("PAK", "PAKISTAN", "PK"),
    ("PAN", "PANAMA", "PA"),
    ("PCN", "PITCAIRN", "PN"),
    ("PER", "PERU", "PE"),
    ("PHL", "PHILIPPINES", "PH"),
    ("PLW", "PALAU", "PW"),
    ("PNG", "PAPUA NEW GUINEA", "PG"),
    ("POL", "POLAND", "PL"),
    ("PRI", "PUERTO RICO", "PR"),
    ("PRK", "DEMOCRATIC PEOPLE'S REPUBLIC OF KOREA", "KP"),
    ("PRT", "PORTUGAL", "PT"),
    ("PRY", "PARAGUAY", "PY"),
    ("PSE", "PALESTINIAN TERRITORY, OCCUPIED", "PS"),
    ("PYF", "FRENCH POLYNESIA", "PF"),
    ("QAT", "QATAR", "QA"),
    ("REU", "REUNION", "RE"),
    ("ROU", "ROMANIA", "RO"),
    ("RUS", "RUSSIAN FEDERATION", "RU"),
    ("RWA", "RWANDA", "RW"),
    ("SAU", "SAUDI ARABIA", "SA"),
    ("SDN", "SUDAN", "SD"),
    ("SEN", "SENEGAL", "SN"),
    ("SGP", "SINGAPORE", "SG"),
    ("SGS", "SOUTH GEORGIA AND THE SOUTH SANDWICH ISLANDS", "GS"),
    ("SHN", "SAINT HELENA", "SH"),
    ("SJM", "SVALBARD AND JAN MAYEN", "SJ"),
    ("SLB", "SOLOMON ISLANDS", "SB"),
    ("SLE", "SIERRA LEONE", "SL"),
    ("SLV", "EL SALVADOR", "SV"),
    ("SMR", "SAN MARINO", "SM"),
    ("SOM", "SOMALIA", "SO"),
    ("SPM", "SAINT PIERRE AND MIQUELON", "PM"),
    ("SRB", "SERBIA", "RS"),
    ("SSD", "REPUBLIC OF SOUTH SUDAN", "SS"),
    ("STP", "SAO TOME AND PRINCIPE", "ST"),
    ("SUR", "SURINAME", "SR"),
    ("SVK", "SLOVAKIA", "SK"),
    ("SVN", "SLOVENIA", "SI"),
    ("SWE", "SWEDEN", "SE"),
    ("SWZ", "SWAZILAND", "SZ"),
    ("SXM", "SINT MAARTEN", "SX"),
    ("SYC", "SEYCHELLES", "SC"),
    ("SYR", "SYRIAN ARAB REPUBLIC", "SY"),
    ("TCA", "TURKS AND CAICOS ISLANDS", "TC"),
    ("TCD", "CHAD", "TD"),
    ("TGO", "TOGO", "TG"),
    ("THA", "THAILAND", "TH"),
    ("TJK", "TAJIKISTAN", "TJ"),
    ("TKL", "TOKELAU", "TK"),
    ("TKM", "TURKMENISTAN", "TM"),
    ("TLS", "TIMOR-LESTE", "TL"),
    ("TON", "TONGA", "TO"),
    ("TTO", "TRINIDAD AND TOBAGO", "TT"),
    ("TUN", "TUNISIA", "TN"),
    ("TUR", "TURKEY", "TR"),
    ("TUV", "TUVALU", "TV"),
    ("TWN", "TAIWAN", "TW"),
    ("TZA", "UNITED REPUBLIC OF TANZANIA", "TZ"),
    ("UGA", "UGANDA", "UG"),
    ("UKR", "UKRAINE", "UA"),
    ("UMI", "UNITED STATES MINOR OUTLYING ISLANDS", "UM"),
    ("URY", "URUGUAY", "UY"),
    ("USA", "UNITED STATES", "US"),
    ("UZB", "UZBEKISTAN", "UZ"),
    ("VAT", "HOLY SEE (VATICAN CITY STATE)", "VA"),
    ("VCT", "SAINT VINCENT AND THE GRENADINES", "VC"),
    ("VEN", "VENEZUELA", "VE"),
    ("VGB", "BRITISH VIRGIN ISLANDS", "VG"),
    ("VIR", "U.S. VIRGIN ISLANDS", "VI"),
    ("VNM", "VIET NAM", "VN"),
    ("VUT", "VANUATU", "VU"),
    ("WLF", "WALLIS AND FUTUNA", "WF"),
    ("WSM", "SAMOA", "WS"),
    ("XKS", "REPUBLIC OF KOSOVO", "XK"),
    ("YEM", "YEMEN", "YE"),
    ("ZAF", "SOUTH AFRICA", "ZA"),
    ("ZMB", "ZAMBIA", "ZM"),
    ("ZWE", "ZIMBABWE", "ZW"),
)

#: The codes CR invented. Called out so nobody "corrects" them to ISO alpha-3.
NON_ISO_COUNTRY_CODES = frozenset({"GBR1", "GBR2", "GBR3"})

#: Hong Kong, the only value CR accepts for the three "Must be HKG" nodes.
HKG = "HKG"

#: Hand-written synonyms that are neither a CR code, an alpha-2, nor CR's own
#: English description. Kept because older G-FlowDesk / Viewpoint rows may still
#: carry them — every key here was already in nar1_mapper._COUNTRY_CODES before
#: this table replaced it, so none of them is a new guess.
#:
#: "KOREA" is ambiguous between KOR and PRK. It resolved to KOR before this
#: table existed and still does; dropping it would start refusing data that used
#: to map, which is not what this change is for. Flagged rather than silently
#: kept: if CR ever rejects one, this is the line to delete.
_ALIASES: dict[str, str] = {
    "PRC": "CHN",
    "MACAO": "MAC",
    "SOUTHKOREA": "KOR",
    "KOREA": "KOR",
    "UNITEDSTATESOFAMERICA": "USA",
    "UK": "GBR",
    "BRITAIN": "GBR",
    "BVI": "VGB",
}


def _normalise(value: str) -> str:
    """Case, spacing and punctuation folded away.

    CR writes "VIET NAM", G-FlowDesk writes "Vietnam"; CR writes
    "U.S. VIRGIN ISLANDS", data entry writes "US Virgin Islands". Both sides go
    through this, so the two forms meet. Verified collision-free across all 250
    descriptions by test.
    """
    return "".join(c for c in value.upper() if c.isalnum())


def _build() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Derive the lookup indexes, refusing to load a table that cannot be one.

    A ValueError here is a broken data file, caught at import rather than at a
    chargeable CR submission. Not `assert` — `python -O` strips those.
    """
    codes: dict[str, str] = {}
    by_alpha2: dict[str, str] = {}
    by_description: dict[str, str] = {}
    for code, english, alpha2 in _COUNTRY_ROWS:
        if code in codes:
            raise ValueError(f"cr_vocabularies: duplicate CR code {code!r}")
        if alpha2 in by_alpha2:
            raise ValueError(
                f"cr_vocabularies: alpha-2 {alpha2!r} claimed by both "
                f"{by_alpha2[alpha2]!r} and {code!r}"
            )
        key = _normalise(english)
        if key in by_description:
            raise ValueError(
                f"cr_vocabularies: description {english!r} collides with "
                f"{by_description[key]!r} once normalised"
            )
        codes[code] = english
        by_alpha2[alpha2] = code
        by_description[key] = code
    for alias, code in _ALIASES.items():
        if code not in codes:
            raise ValueError(
                f"cr_vocabularies: alias {alias!r} points at {code!r}, which is "
                "not a code CR's Country & Region sheet carries"
            )
    return codes, by_alpha2, by_description


CR_COUNTRY_CODES, _BY_ALPHA2, _BY_DESCRIPTION = _build()

#: alpha-2 -> CR code, the form G-FlowDesk actually stores. Public because that
#: is the mapping the review asked to be able to assert over.
ALPHA2_TO_CR_CODE: dict[str, str] = dict(_BY_ALPHA2)


def resolve_country(value: str | None) -> str | None:
    """A country as G-FlowDesk records it -> CR's ctryRegion code, or None.

    None means "CR has no code for this", never a guess: a plausible-looking
    wrong code is worse than a refusal, because CR takes the fee first.

    Resolution order:
      1. already a CR code            "HKG", "GBR1"
      2. ISO alpha-2                  "VN" -> VNM, "GG" -> GBR1 (never GBR)
      3. CR's own English description "VIET NAM", "Vietnam", "viet nam"
      4. a hand-written alias         "UK", "BVI", "PRC"
    """
    if not value:
        return None
    raw = value.strip().upper()
    if raw in CR_COUNTRY_CODES:
        return raw
    key = _normalise(value)
    if len(key) == 2 and key in _BY_ALPHA2:
        return _BY_ALPHA2[key]
    if key in _BY_DESCRIPTION:
        return _BY_DESCRIPTION[key]
    return _ALIASES.get(key)


#: selectCapacityDesc, "Capacity (Individual)" sheet, NAR1-relevant rows only.
#: The sheet's trailing "for ND4" section (Resigning Director, Resigning Company
#: Secretary) belongs to form ND4 and is deliberately excluded.
#: CR's HONG KONG DISTRICT codes — the "District" sheet, 125 rows.
#:
#: PROVEN LIVE 2026-08-27. `dstCtyStatePostal` is a CONTROLLED CODE for a Hong
#: Kong address, not free text. Sending the district NAME "WAN CHAI" was
#: refused four times over (once per address) with
#:     ERR_ES_FORM_INVALID_VALUE: Please input valid District.
#: while "CENTRAL" in the same document passed — because "CENTRAL" happens to
#: BE its own code and "WAN CHAI" is spelt "WANCHAI".
#:
#: The code is derivable: uppercase the English description and drop every
#: non-alphanumeric character. Verified against all 125 rows with zero
#: exceptions, which is why `_district_key` normalises rather than carrying a
#: second name->code table that could drift. The set is still committed so an
#: unknown value is REFUSED here, with the offending text named, instead of
#: being sent to CR to be rejected one round trip later.
DISTRICT_CODES = frozenset({
    'ABERDEEN', 'ADMIRALTY', 'APLEICHAU', 'BEACONHILL', 'BRAEMARHILL',
    'CAUSEWAYBAY', 'CENTRAL', 'CHAIWAN', 'CHEUNGCHAU', 'CHEUNGMUKTAU',
    'CHEUNGSHAWAN', 'CHUNGHOMKOK', 'CLEARWATERBAY', 'DIAMONDHILL', 'FANLING',
    'FOTAN', 'HANGHAU', 'HAPPYVALLEY', 'HATSUEN', 'HOMANTIN', 'HUNGHOM',
    'HUNGSHUIKIU', 'JARDINESLOOKOUT', 'JORDANVALLEY', 'KAITAK', 'KAMTIN',
    'KEILINGHA', 'KENNEDYTOWN', 'KINGSPARK', 'KOWLOONBAY', 'KOWLOONCITY',
    'KOWLOONTONG', 'KWAICHUNG', 'KWUNTONG', 'LAICHIKOK', 'LAMMAISLAND',
    'LAMTEI', 'LAMTIN', 'LANTAUISLAND', 'LAUFAUSHAN', 'LOKFU', 'LOKMACHAU',
    'LUENWOHUI', 'LUKKENG', 'MALIUSHUI', 'MAONSHAN', 'MATAUKOK', 'MATAUWAI',
    'MAWAN', 'MAYAUTONG', 'MEIFOO', 'MIDLEVELS', 'MONGKOK', 'NGAUCHIWAN',
    'NGAUTAUKOK', 'NORTHPOINT', 'PATHEUNG', 'PEAK', 'PENGCHAU', 'PINGSHEK',
    'POKFULAM', 'QUARRYBAY', 'REPULSEBAY', 'SAIKUNG', 'SAIWANHO',
    'SAIYINGPUN', 'SANPOKONG', 'SANTIN', 'SAUMAUPING', 'SHAMSHUIPO',
    'SHAMTSENG', 'SHATAUKOK', 'SHATIN', 'SHAUKEIWAN', 'SHEKKIPMEI',
    'SHEKKONG', 'SHEKO', 'SHEKTONGTSUI', 'SHEKWUHUI', 'SHEUNGKWAICHUNG',
    'SHEUNGSHUI', 'SHEUNGWAN', 'SHOUSONHILL', 'SHUENWAN', 'SIUSAIWAN',
    'SOKONPO', 'SOKWUNWAT', 'STANLEY', 'STONECUTTERSISLAND', 'SUNNYBAY',
    'TAIHANG', 'TAIKOKTSUI', 'TAILAMCHUNG', 'TAIMEITUK', 'TAIMONGTSAI',
    'TAIPO', 'TAIPOKAU', 'TAIPOMARKET', 'TAITAM', 'TAIWAI', 'TAIWOPING',
    'TINGKAU', 'TINHAU', 'TINSHUIWAI', 'TIUKENGLENG', 'TOKWAWAN',
    'TSEUNGKWANO', 'TSIMSHATSUI', 'TSINGLUNGTAU', 'TSINGYI', 'TSUENWAN',
    'TSZWANSHAN', 'TUENMUN', 'TUNGTAU', 'WANCHAI', 'WANGTAUHOM',
    'WESTKOWLOONCULTURALDISTRICT', 'WONGCHUKHANG', 'WONGTAISIN', 'WUKAISHA',
    'WUKAUTANG', 'YAUMATEI', 'YAUTONG', 'YAUYATTSUEN', 'YUENLONG',
})


def _district_key(value: str) -> str:
    return "".join(c for c in value.upper() if c.isalnum())


def resolve_district(value: str | None) -> str | None:
    """A stored district name -> CR's District code, or None if CR has no such
    district.

    Hong Kong addresses ONLY. Everywhere else `dstCtyStatePostal` is free text
    (city / state / postcode), which is why `_address` consults this only when
    the region resolves to HKG.
    """
    if not value:
        return None
    key = _district_key(str(value))
    return key if key in DISTRICT_CODES else None


CAPACITY_INDIVIDUAL = frozenset({
    "Authorized Representative",
    "Director",
    "Reserve Director",
    "Company Secretary",
    "Authorized Person",
})

#: selectCapacityDesc, "Capacity (Body Coporate)" sheet, NAR1-relevant rows only
#: (its "for ND4" section is likewise excluded).
#:
#: A body corporate does not sign — a natural person signs on its behalf, which
#: is what every value here spells out, and it is why selectPersonId's remark
#: reads "Empty if sign by Body Corporate". None of the Individual values is
#: valid for a body-corporate signatory: "Company Secretary" is an Individual
#: value only.
CAPACITY_BODY_CORPORATE = frozenset({
    "Authorized Representative of the Authorized Representative (Body Corporate)",
    "Authorized Representative of the Director (Body Corporate)",
    "Authorized Representative of the Company Secretary (Body Corporate)",
    "Director of the Authorized Representative (Body Corporate)",
    "Director of the Director (Body Corporate)",
    "Director of the Company Secretary (Body Corporate)",
    "Reserve Director of the Authorized Representative (Body Corporate)",
    "Reserve Director of the Director (Body Corporate)",
    "Reserve Director of the Company Secretary (Body Corporate)",
    "Company Secretary of the Authorized Representative (Body Corporate)",
    "Company Secretary of the Director (Body Corporate)",
    "Company Secretary of the Company Secretary (Body Corporate)",
    "Authorized Person of the Authorized Representative (Body Corporate)",
    "Authorized Person of the Director (Body Corporate)",
    "Authorized Person of the Company Secretary (Body Corporate)",
})

#: What a body-corporate signatory means in practice at GSHK (Levi 2026-08-31).
#:
#: Every real GSHK client has GSHK Ltd as its company secretary, and a GSHK
#: director signs on that body corporate's behalf — so this one value fits the
#: entire book. `scripts/nar1_regression.py` has assumed exactly this string
#: since the regression was written; making it the default only stops the
#: operator retyping the same answer on every case.
#:
#: It is a DEFAULT, not a constant: the picker still offers all 15 values and a
#: stored choice always wins.
DEFAULT_CAPACITY_BODY_CORPORATE = "Director of the Company Secretary (Body Corporate)"


def default_capacity(*, is_corporate: bool) -> str | None:
    """The capacity to assume when the operator has not chosen one.

    Only for a body corporate. CR keeps two separate vocabularies, and an
    individual signatory carrying a "(Body Corporate)" capacity is a
    misstatement `_check_capacity` would rightly refuse — so an individual
    gets no default and, as before, must be answered explicitly.
    """
    return DEFAULT_CAPACITY_BODY_CORPORATE if is_corporate else None
