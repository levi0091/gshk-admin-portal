from etl.reconciliation import ReconciliationReport


def _base_class_name(row: dict) -> str:
    name = (row.get("ShareClassName") or "").strip()
    return name or "Ordinary"


def transform_share_classes(
    rows: list[dict],
    entity_id_by_vp_key: dict[str, str],
    report: ReconciliationReport,
) -> list[dict]:
    """VP Share_Capital rows -> share_classes insert dicts (batch).

    Resolves entity_id (drops+logs unresolved). Disambiguates class_name so the
    target UNIQUE(entity_id, class_name) holds: when an entity has more than one
    class resolving to the same base name, the VP class code is appended.
    """
    # First pass: count base-name occurrences per EntCode to detect collisions.
    name_counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row["EntCode"], _base_class_name(row))
        name_counts[key] = name_counts.get(key, 0) + 1

    out: list[dict] = []
    for row in rows:
        entcode = row["EntCode"]
        entity_id = entity_id_by_vp_key.get(entcode)
        vp_key = f"{entcode}:{row['ShareClass']}"
        if entity_id is None:
            report.record_error("share_classes", vp_key, f"unresolved entity_id for EntCode={entcode}")
            continue
        base = _base_class_name(row)
        ambiguous = name_counts[(entcode, base)] > 1
        class_name = f"{base} ({row['ShareClass']})" if ambiguous else base
        out.append({
            "vp_source_key": vp_key,
            "entity_id": entity_id,
            "class_name": class_name,
            "currency": (row.get("Currency") or "HKD"),
            "nominal_value": row.get("NomValShare"),
            "votes_per_share": row.get("VotesPerShare"),
            "total_issued": row.get("Issued"),
            "total_paid": row.get("PaidCap"),
        })
    return out


def transform_business_name(row: dict, entity_id_by_vp_key: dict[str, str], report: ReconciliationReport) -> dict | None:
    """VP BusNames row -> business_names insert dict (singular).

    Resolves entity_id (drops+logs unresolved).
    """
    entcode = row["EntCode"]
    vp_key = f"{entcode}:{row['SeqNr']}"
    entity_id = entity_id_by_vp_key.get(entcode)
    if entity_id is None:
        report.record_error("business_names", vp_key, f"unresolved entity_id for EntCode={entcode}")
        return None
    return {
        "vp_source_key": vp_key,
        "entity_id": entity_id,
        "br_number": row.get("BusRegNr"),
        "business_name": row.get("BusName"),
        "business_name_zh": row.get("ChineseBusName"),
        "registration_date": row.get("DateRegistration"),
        "renewal_date": row.get("DateRenew"),
        "cessation_date": row.get("DateCessation"),
        "status": row.get("Status"),
    }


def transform_entity_name_change(row: dict, entity_id_by_vp_key: dict[str, str], report: ReconciliationReport) -> dict | None:
    """VP EntNameChanges row -> entity_name_changes insert dict (singular).

    Resolves entity_id (drops+logs unresolved).
    """
    entcode = row["EntCode"]
    vp_key = f"{entcode}:{row['SeqNr']}"
    entity_id = entity_id_by_vp_key.get(entcode)
    if entity_id is None:
        report.record_error("entity_name_changes", vp_key, f"unresolved entity_id for EntCode={entcode}")
        return None
    return {
        "vp_source_key": vp_key,
        "entity_id": entity_id,
        "old_name": row.get("OldName"),
        "old_name_zh": row.get("OldChnsName"),
        "new_name": row.get("NewName"),
        "new_name_zh": row.get("NewChnsName"),
        "applied_date": row.get("DateApplied"),
        "confirmed_date": row.get("DateConfirmed"),
    }


def transform_share_transaction(
    row: dict,
    entity_id_by_vp_key: dict[str, str],
    person_id_by_vp_key: dict[str, str],
    refcode_type_by_vp_key: dict[str, str],
    share_class_id_by_vp_key: dict[str, str],
    report: ReconciliationReport,
) -> dict | None:
    """Share_Transactions row -> share_transactions insert dict (full ledger).
    entity_id required (drop+log if unresolved); share_class_id nullable;
    person_id only for individual holders (ISSUE/corporate -> None, no error)."""
    entcode = row["EntCode"]
    vp_key = f"{entcode}:{row['IssueNr']}"
    entity_id = entity_id_by_vp_key.get(entcode)
    if entity_id is None:
        report.record_error("share_transactions", vp_key, f"unresolved entity_id for EntCode={entcode}")
        return None

    share_class_id = share_class_id_by_vp_key.get(f"{entcode}:{row.get('ShareClass')}")

    addr = row.get("AddrCode")
    person_id = None
    if addr and addr != "ISSUE" and refcode_type_by_vp_key.get(addr) == "I":
        person_id = person_id_by_vp_key.get(addr)

    cert = row.get("CertificateNr")
    return {
        "vp_source_key": vp_key,
        "entity_id": entity_id,
        "share_class_id": share_class_id,
        "person_id": person_id,
        "transaction_type": row.get("TransType"),
        "transaction_date": row.get("TransDate"),
        "shares": row.get("NrShare"),
        "balance": row.get("BalanceShare"),
        "issue_price": row.get("IssuePrice"),
        "certificate_no": str(cert) if cert is not None else None,
    }


def transform_share_certificate(
    row: dict,
    entity_id_by_vp_key: dict[str, str],
    person_id_by_vp_key: dict[str, str],
    refcode_type_by_vp_key: dict[str, str],
    share_class_id_by_vp_key: dict[str, str],
    report: ReconciliationReport,
) -> dict | None:
    """Share_Certificates row -> share_certificates insert dict."""
    entcode = row.get("EntCode")
    vp_key = str(row["SeqNr"])
    entity_id = entity_id_by_vp_key.get(entcode)
    if entity_id is None:
        report.record_error("share_certificates", vp_key, f"unresolved entity_id for EntCode={entcode}")
        return None

    share_class_id = share_class_id_by_vp_key.get(f"{entcode}:{row.get('ShareClass')}")

    addr = row.get("AddrCode")
    person_id = None
    if addr and addr != "ISSUE" and refcode_type_by_vp_key.get(addr) == "I":
        person_id = person_id_by_vp_key.get(addr)

    cert = row.get("CertificateNr")
    return {
        "vp_source_key": vp_key,
        "entity_id": entity_id,
        "share_class_id": share_class_id,
        "person_id": person_id,
        "certificate_no": str(cert) if cert is not None else None,
        "shares": row.get("NrShare"),
        "issue_date": row.get("IssueDate"),
        "cancelled_date": row.get("CancelDate"),
        "document_id": None,
    }


def derive_shareholdings(
    transaction_rows: list[dict],
    entity_id_by_vp_key: dict[str, str],
    person_id_by_vp_key: dict[str, str],
    refcode_type_by_vp_key: dict[str, str],
    share_class_id_by_vp_key: dict[str, str],
    report: ReconciliationReport,
) -> list[dict]:
    """Derive current shareholdings from the raw Share_Transactions ledger,
    mirroring VP's C_MemberBase view: posted, non-ISSUE rows grouped by
    (EntCode, AddrCode, ShareClass); shares_held = SUM(BalanceShare),
    amount_paid = SUM(Paid * BalanceShare), is_current = shares_held > 0.
    share_class_id is NOT NULL in the target, so a group whose class is
    unresolved is dropped and logged."""
    groups: dict[tuple[str, str, str], dict] = {}
    for row in transaction_rows:
        if not row.get("Posted") or row.get("AddrCode") == "ISSUE":
            continue
        addr = row.get("AddrCode")
        if not addr:
            continue
        key = (row["EntCode"], addr, row.get("ShareClass"))
        agg = groups.setdefault(key, {"shares_held": 0, "amount_paid": 0})
        bal = row.get("BalanceShare") or 0
        paid = row.get("Paid") or 0
        agg["shares_held"] += bal
        agg["amount_paid"] += paid * bal

    out: list[dict] = []
    for (entcode, addr, shareclass), agg in groups.items():
        vp_key = f"{entcode}:{addr}:{shareclass}"
        entity_id = entity_id_by_vp_key.get(entcode)
        if entity_id is None:
            report.record_error("shareholdings", vp_key, f"unresolved entity_id for EntCode={entcode}")
            continue
        share_class_id = share_class_id_by_vp_key.get(f"{entcode}:{shareclass}")
        if share_class_id is None:
            report.record_error("shareholdings", vp_key, f"unresolved share_class_id for {entcode}:{shareclass}")
            continue
        is_individual = refcode_type_by_vp_key.get(addr) == "I"
        person_id = person_id_by_vp_key.get(addr) if is_individual else None
        if is_individual and person_id is None:
            report.record_error("shareholdings", vp_key, f"unresolved person_id for AddrCode={addr}")
        out.append({
            "vp_source_key": vp_key,
            "entity_id": entity_id,
            "share_class_id": share_class_id,
            "person_id": person_id,
            "party_type": "individual" if is_individual else "corporate",
            "corporate_name": None if is_individual else addr,
            "shares_held": agg["shares_held"],
            "amount_paid": agg["amount_paid"],
            "is_current": agg["shares_held"] > 0,
        })
    return out
