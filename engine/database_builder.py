"""SQLite schema creation and data migration for File2Base's local demo."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Any

from engine.analyzer import read_business_file, slugify


def _quote(identifier: str) -> str:
    # Identifiers are already sanitized, but quote them defensively regardless.
    return '"' + identifier.replace('"', '""') + '"'


def _convert_value(value: Any, sql_type: str):
    if value is None or (isinstance(value, float) and value != value):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if sql_type == "INTEGER":
        try:
            number = float(str(value).strip())
            if number.is_integer():
                return int(number)
            # Preserve fractional values rather than silently truncating them.
            # SQLite's dynamic typing can retain this numeric-looking value even
            # when the declared column affinity is INTEGER; preflight also warns.
            return str(value).strip()
        except (ValueError, TypeError):
            return str(value).strip()
    if sql_type == "REAL":
        try:
            return float(str(value).replace(",", "").strip())
        except (ValueError, TypeError):
            return str(value).strip()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat(sep=" ") if hasattr(value, "hour") else value.isoformat()
        except TypeError:
            return value.isoformat()
    return str(value).strip()


def _unique_db_columns(table: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    used = set()
    for col in table["columns"]:
        base = slugify(col["name"], "column")
        name = base
        i = 2
        while name in used:
            name = f"{base}_{i}"
            i += 1
        used.add(name)
        copied = dict(col)
        copied["name"] = name
        out.append(copied)
    return out


def create_database(
    workspace_dir: str,
    analysis: dict[str, Any],
    approved_relation_ids: list[int],
    table_name_overrides: dict[str, str] | None = None,
    primary_key_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create generated.sqlite from the reviewed schema using atomic replacement."""
    table_name_overrides = table_name_overrides or {}
    primary_key_overrides = primary_key_overrides or {}
    db_path = os.path.join(workspace_dir, "generated.sqlite")
    # Build to a temporary file. The last successful database is preserved unless
    # the replacement migration fully succeeds and passes integrity checks.
    temp_db_path = db_path + ".tmp"
    if os.path.exists(temp_db_path):
        os.remove(temp_db_path)

    tables = analysis["tables"]
    id_to_original = {t["id"]: t["table_name"] for t in tables}
    original_to_new = {}
    used_names = set()
    for table in tables:
        chosen = slugify(table_name_overrides.get(table["table_name"], table["table_name"]), "business_table")
        base = chosen
        i = 2
        while chosen in used_names:
            chosen = f"{base}_{i}"
            i += 1
        used_names.add(chosen)
        original_to_new[table["table_name"]] = chosen

    approved = [r for r in analysis.get("relationships", []) if int(r["suggestion_id"]) in set(approved_relation_ids)]
    # Only create an enforced FK constraint when evidence suggests every distinct source key is covered.
    # Only create enforced constraints for complete value coverage. A high but
    # imperfect coverage score is still useful as a recommendation, not a safe FK.
    selected_primary_keys = {}
    for table in tables:
        submitted = primary_key_overrides.get(table["table_name"])
        if submitted == "__generated__":
            selected_primary_keys[table["table_name"]] = None
        elif submitted:
            selected_primary_keys[table["table_name"]] = submitted
        else:
            selected_primary_keys[table["table_name"]] = table.get("primary_key")
    enforceable = [
        r for r in approved
        if r.get("enforceable")
        and float(r.get("coverage", 0)) >= 0.999999
        and selected_primary_keys.get(r["target_table"]) == r.get("target_column")
    ]
    enforced_suggestion_ids = {int(r["suggestion_id"]) for r in enforceable}
    table_objects = []
    source_frames = {}
    for table in tables:
        df = read_business_file(table["path"])
        source_frames[table["id"]] = df
        effective_table = {**table, "primary_key": selected_primary_keys.get(table["table_name"])}
        cols = _unique_db_columns(effective_table)
        for col in cols:
            col["is_primary_key"] = bool(effective_table["primary_key"]) and col["name"] == effective_table["primary_key"]
        table_objects.append({
            **effective_table,
            "new_name": original_to_new[table["table_name"]],
            "db_columns": cols,
        })

    by_original_table = {t["table_name"]: t for t in table_objects}
    by_id = {t["id"]: t for t in table_objects}
    for rel in approved:
        rel["source_table_final"] = original_to_new[rel["source_table"]]
        rel["target_table_final"] = original_to_new[rel["target_table"]]

    # Map source table/column and target table/column to generated identifiers.
    for rel in enforceable:
        s_table = by_original_table[rel["source_table"]]
        t_table = by_original_table[rel["target_table"]]
        s_col = next((c for c in s_table["db_columns"] if c["name"] == rel["source_column"]), None)
        t_col = next((c for c in t_table["db_columns"] if c["name"] == rel["target_column"]), None)
        if s_col and t_col:
            rel["source_column_final"] = s_col["name"]
            rel["target_column_final"] = t_col["name"]

    con = sqlite3.connect(temp_db_path)
    con.execute("PRAGMA foreign_keys = OFF")  # Data loads first; validation is run after loading.
    created_tables = []
    row_counts = {}
    try:
        # First create all tables, allowing FK declarations to reference tables created later.
        for table in table_objects:
            cols = table["db_columns"]
            pk = next((c["name"] for c in cols if c.get("is_primary_key")), None)
            definitions = []
            for col in cols:
                definitions.append(f"{_quote(col['name'])} {col.get('sql_type', 'TEXT')}")
            if pk:
                definitions.append(f"PRIMARY KEY ({_quote(pk)})")
            else:
                synthetic_id = "file2base_id"
                existing_names = {c["name"] for c in cols}
                suffix = 2
                while synthetic_id in existing_names:
                    synthetic_id = f"file2base_id_{suffix}"
                    suffix += 1
                table["synthetic_id"] = synthetic_id
                definitions.append(f"{_quote(synthetic_id)} INTEGER PRIMARY KEY AUTOINCREMENT")
            for rel in enforceable:
                if rel["source_table"] == table["table_name"] and rel.get("source_column_final") and rel.get("target_column_final"):
                    definitions.append(
                        f"FOREIGN KEY ({_quote(rel['source_column_final'])}) REFERENCES "
                        f"{_quote(rel['target_table_final'])} ({_quote(rel['target_column_final'])})"
                    )
            ddl = f"CREATE TABLE {_quote(table['new_name'])} ({', '.join(definitions)})"
            con.execute(ddl)
            created_tables.append(table["new_name"])

        # Migrate source data. Input columns are matched to their normalized output columns by position.
        for table in table_objects:
            df = source_frames[table["id"]]
            cols = table["db_columns"]
            output_names = [c["name"] for c in cols]
            placeholders = ",".join(["?"] * len(output_names))
            col_sql = ",".join(_quote(name) for name in output_names)
            insert_sql = f"INSERT INTO {_quote(table['new_name'])} ({col_sql}) VALUES ({placeholders})"
            original_col_names = [c["original_name"] for c in cols]
            rows = []
            for row in df.rows:
                out_row = []
                for col in cols:
                    value = row.get(col["original_name"])
                    out_row.append(_convert_value(value, col.get("sql_type", "TEXT")))
                rows.append(tuple(out_row))
            if rows:
                con.executemany(insert_sql, rows)
            row_counts[table["new_name"]] = len(rows)

        con.commit()
        con.execute("PRAGMA foreign_keys = ON")
        violations = con.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise ValueError(
                f"Migration safety check failed: {len(violations)} foreign-key violation(s). "
                "The previous database was preserved; review the relationships and try again."
            )
        # Store the complete accepted relationship map, including non-enforced recommendations, for UI transparency.
        con.execute("CREATE TABLE IF NOT EXISTS file2base_relationships (source_table TEXT, source_column TEXT, target_table TEXT, target_column TEXT, confidence_pct INTEGER, enforced INTEGER, coverage REAL)")
        for rel in approved:
            con.execute(
                "INSERT INTO file2base_relationships VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rel.get("source_table_final"), rel["source_column"], rel.get("target_table_final"), rel["target_column"],
                 int(rel["confidence_pct"]), int(int(rel["suggestion_id"]) in enforced_suggestion_ids), float(rel["coverage"]))
            )
        con.commit()
    except Exception:
        con.rollback()
        con.close()
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)
        raise
    finally:
        try:
            con.close()
        except Exception:
            pass

    # Atomic replacement means a failed run never deletes a previous good build.
    os.replace(temp_db_path, db_path)

    result = {
        "db_path": db_path,
        "table_count": len(created_tables),
        "row_count": sum(row_counts.values()),
        "row_counts": row_counts,
        "tables": created_tables,
        "relationships": [
            {
                "source_table": r.get("source_table_final"),
                "source_column": r["source_column"],
                "target_table": r.get("target_table_final"),
                "target_column": r["target_column"],
                "confidence_pct": r["confidence_pct"],
                "enforced": int(r["suggestion_id"]) in enforced_suggestion_ids,
                "coverage": r["coverage"],
            } for r in approved
        ],
        "foreign_key_violations": len(violations),
        "analysis_tables": table_objects,
    }
    with open(os.path.join(workspace_dir, "database_result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return result


def inspect_database(db_path: str) -> dict[str, Any]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        table_names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'file2base_relationships' ORDER BY name")]
        tables = []
        for name in table_names:
            columns = [dict(r) for r in con.execute(f"PRAGMA table_info({_quote(name)})")]
            count = con.execute(f"SELECT COUNT(*) FROM {_quote(name)}").fetchone()[0]
            fks = [dict(r) for r in con.execute(f"PRAGMA foreign_key_list({_quote(name)})")]
            tables.append({"name": name, "columns": columns, "row_count": count, "foreign_keys": fks})
        try:
            relationships = [dict(r) for r in con.execute("SELECT source_table, source_column, target_table, target_column, confidence_pct, enforced, coverage FROM file2base_relationships ORDER BY confidence_pct DESC")]
        except sqlite3.OperationalError:
            relationships = []
        return {"tables": tables, "relationships": relationships, "row_count": sum(t["row_count"] for t in tables)}
    finally:
        con.close()


def browse_table(db_path: str, table_name: str, limit: int = 100) -> dict[str, Any]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        known = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if table_name not in known:
            raise ValueError("Table not found.")
        columns = [r[1] for r in con.execute(f"PRAGMA table_info({_quote(table_name)})")]
        rows = [dict(r) for r in con.execute(f"SELECT * FROM {_quote(table_name)} LIMIT ?", (limit,)).fetchall()]
        total = con.execute(f"SELECT COUNT(*) FROM {_quote(table_name)}").fetchone()[0]
        return {"table_name": table_name, "columns": columns, "rows": rows, "total": total, "limit": limit}
    finally:
        con.close()
