"""Non-destructive migration checks for the File2Base demo.

The preflight stage reads the source data and predicts migration risks without
creating or overwriting a database. Scores and recommendations remain heuristic.
"""
from __future__ import annotations

from typing import Any

from engine.analyzer import _text, read_business_file, slugify


def _column_profile(table: dict[str, Any], normalized_name: str | None) -> dict[str, Any] | None:
    if not normalized_name:
        return None
    return next((c for c in table.get("columns", []) if c.get("name") == normalized_name), None)


def _db_table_names(tables: list[dict[str, Any]], overrides: dict[str, str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for table in tables:
        base = slugify(overrides.get(table["table_name"], table["table_name"]), "business_table")
        final = base
        suffix = 2
        while final in used:
            final = f"{base}_{suffix}"
            suffix += 1
        used.add(final)
        mapping[table["table_name"]] = final
    return mapping


def build_migration_preflight(
    analysis: dict[str, Any],
    approved_relation_ids: list[int],
    table_name_overrides: dict[str, str] | None = None,
    primary_key_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return a JSON-serializable migration plan. This function has no DB side effects."""
    overrides = table_name_overrides or {}
    pk_overrides = primary_key_overrides or {}
    selected_ids = {int(value) for value in approved_relation_ids}
    tables = analysis.get("tables", [])
    by_id = {table["id"]: table for table in tables}
    by_name = {table["table_name"]: table for table in tables}
    data_by_id = {table["id"]: read_business_file(table["path"]) for table in tables}
    final_names = _db_table_names(tables, overrides)

    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    table_checks: list[dict[str, Any]] = []
    total_rows = 0
    conversion_warnings = 0

    for table in tables:
        data = data_by_id[table["id"]]
        total_rows += len(data)
        requested_pk = pk_overrides.get(table["table_name"])
        if requested_pk == "__generated__":
            pk = None
        elif requested_pk:
            pk = requested_pk
        else:
            pk = table.get("primary_key")
        pk_profile = _column_profile(table, pk)
        missing_pk = 0
        duplicate_pk = 0
        if pk_profile:
            original = pk_profile["original_name"]
            raw_values = [_text(value) for value in data[original]]
            nonempty = [value for value in raw_values if value != ""]
            missing_pk = len(raw_values) - len(nonempty)
            folded = [value.casefold() for value in nonempty]
            duplicate_pk = len(folded) - len(set(folded))
            if missing_pk or duplicate_pk:
                blockers.append({
                    "title": f"{table['filename']}: primary-key candidate is not safe",
                    "detail": f"{pk_profile['original_name']} has {missing_pk} blank and {duplicate_pk} duplicate value(s). Choose a safer key or use a generated row ID before migration.",
                })
        else:
            warnings.append({
                "title": f"{table['filename']}: generated row ID required",
                "detail": "No source column passed the key checks. File2Base will add a generated identifier; this does not create business-level identity across files.",
            })

        type_warning_count = 0
        for col in table.get("columns", []):
            if col.get("sql_type") not in {"INTEGER", "REAL"}:
                continue
            values = data[col["original_name"]]
            for value in values:
                text = _text(value)
                if not text:
                    continue
                try:
                    number = float(text.replace(",", "").replace("₹", "").replace("$", "").strip())
                    if col["sql_type"] == "INTEGER" and not number.is_integer():
                        type_warning_count += 1
                except ValueError:
                    type_warning_count += 1
        conversion_warnings += type_warning_count
        if type_warning_count:
            warnings.append({
                "title": f"{table['filename']}: values need type review",
                "detail": f"{type_warning_count} value(s) in numeric columns do not cleanly match the proposed type. The prototype preserves these as SQLite-compatible values where possible; review the resulting table after migration.",
            })
        if table.get("duplicate_rows", 0):
            warnings.append({
                "title": f"{table['filename']}: duplicate rows detected",
                "detail": f"{table['duplicate_rows']} exact duplicate row(s) were detected. They will not be silently deleted; decide later whether they are legitimate repeats.",
            })

        table_checks.append({
            "source_name": table["filename"],
            "table_name": final_names[table["table_name"]],
            "row_count": len(data),
            "column_count": len(table.get("columns", [])),
            "primary_key": pk_profile["original_name"] if pk_profile else None,
            "primary_key_name": pk_profile["name"] if pk_profile else None,
            "missing_primary_key_values": missing_pk,
            "duplicate_primary_key_values": duplicate_pk,
            "generated_key": not bool(pk_profile),
            "duplicate_rows": int(table.get("duplicate_rows", 0)),
            "type_warning_count": type_warning_count,
        })

    relationship_checks: list[dict[str, Any]] = []
    for rel in analysis.get("relationships", []):
        if int(rel.get("suggestion_id", -1)) not in selected_ids:
            continue
        src = by_name.get(rel["source_table"])
        tgt = by_name.get(rel["target_table"])
        if not src or not tgt:
            warnings.append({"title": "Relationship could not be resolved", "detail": "The referenced table was not found in the current schema proposal. This link will be skipped."})
            continue
        src_col = _column_profile(src, rel.get("source_column"))
        tgt_col = _column_profile(tgt, rel.get("target_column"))
        if not src_col or not tgt_col:
            warnings.append({"title": "Relationship needs manual review", "detail": f"Could not map {rel.get('source_table')}.{rel.get('source_column')} to its source header. It will not become a database constraint."})
            continue

        src_values = [_text(v) for v in data_by_id[src["id"]][src_col["original_name"]]]
        tgt_values = {_text(v) for v in data_by_id[tgt["id"]][tgt_col["original_name"]] if _text(v) != ""}
        meaningful_src = [v for v in src_values if v != ""]
        orphan_values = {v for v in meaningful_src if v not in tgt_values}
        orphan_rows = sum(1 for v in meaningful_src if v not in tgt_values)
        distinct_src = set(meaningful_src)
        coverage = (len(distinct_src - orphan_values) / len(distinct_src)) if distinct_src else 1.0
        exact_coverage = orphan_rows == 0
        target_requested_pk = pk_overrides.get(tgt["table_name"])
        target_pk_name = tgt.get("primary_key") if target_requested_pk is None else (None if target_requested_pk == "__generated__" else target_requested_pk)
        target_key_selected = target_pk_name == rel.get("target_column")
        suggested_constraint = bool(rel.get("enforceable")) and exact_coverage and target_key_selected
        if not target_key_selected:
            warnings.append({
                "title": f"{rel['target_table']}: relationship target is not the selected primary key",
                "detail": f"The chosen key for {rel['target_table']} differs from {rel['target_column']}. File2Base will keep this connection as a recommendation rather than enforce it as a foreign key.",
            })
        if orphan_rows:
            warnings.append({
                "title": f"{rel['source_table']}.{rel['source_column']}: unmatched values",
                "detail": f"{orphan_rows} non-empty source row(s) do not match the proposed target key. The connection will be stored as a recommendation, not enforced as a foreign key.",
            })
        relationship_checks.append({
            "source_table": final_names[rel["source_table"]],
            "source_column": rel["source_column"],
            "target_table": final_names[rel["target_table"]],
            "target_column": rel["target_column"],
            "confidence_pct": int(rel.get("confidence_pct", 0)),
            "coverage_pct": round(coverage * 100),
            "orphan_rows": orphan_rows,
            "will_enforce": suggested_constraint,
            "status": "Database constraint" if suggested_constraint else "Recommendation only",
            "target_key_selected": target_key_selected,
        })

    return {
        "can_migrate": len(blockers) == 0,
        "table_count": len(table_checks),
        "row_count": total_rows,
        "relationship_count": len(relationship_checks),
        "enforced_relationship_count": sum(1 for rel in relationship_checks if rel["will_enforce"]),
        "warning_count": len(warnings),
        "blocker_count": len(blockers),
        "conversion_warning_count": conversion_warnings,
        "tables": table_checks,
        "relationships": relationship_checks,
        "blockers": blockers,
        "warnings": warnings,
        "selected_relation_ids": sorted(selected_ids),
        "table_name_overrides": overrides,
        "primary_key_overrides": pk_overrides,
    }
