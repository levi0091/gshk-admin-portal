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
