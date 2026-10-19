"""Lightweight, explainable analysis engine for the File2Base demonstration MVP.

This version intentionally avoids pandas/numpy so it can run on Windows systems
where Application Control blocks unsigned NumPy extension modules.
"""
from __future__ import annotations

import csv
import datetime as _dt
import difflib
import math
import os
import re
from collections import Counter
from typing import Any

from openpyxl import load_workbook

ID_WORDS = {"id", "key", "code", "sku", "uuid", "identifier", "number", "no"}
DATE_WORDS = {"date", "time", "created_at", "updated_at", "timestamp", "dob", "birthdate"}


class DataTable:
    """Small pandas-free table representation used by the demo engine."""
    def __init__(self, columns: list[str], rows: list[dict[str, Any]]):
        self.columns = columns
        self.rows = rows

    @property
    def empty(self) -> bool:
        return not self.columns or not self.rows

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, column: str) -> list[Any]:
        return [row.get(column) for row in self.rows]


def slugify(value: str, fallback: str = "table") -> str:
    value = str(value).strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        value = fallback
    if value[0].isdigit():
        value = f"t_{value}"
    return value[:55]


def unique_names(names: list[str]) -> list[str]:
    result = []
    counts: Counter[str] = Counter()
    for name in names:
        base = slugify(name, "column")
        counts[base] += 1
        result.append(base if counts[base] == 1 else f"{base}_{counts[base]}")
    return result


def _unique_headers(values: list[Any]) -> list[str]:
    """Return non-empty unique source headers, without losing repeated columns."""
    output: list[str] = []
    counts: Counter[str] = Counter()
    used: set[str] = set()
    for index, value in enumerate(values):
        base = str(value).strip() if value is not None else ""
        if not base:
            base = f"Column {index + 1}"
        counts[base] += 1
        candidate = base if counts[base] == 1 else f"{base}_{counts[base]}"
        while candidate in used:
            counts[base] += 1
            candidate = f"{base}_{counts[base]}"
        used.add(candidate)
        output.append(candidate)
    return output


def _clean_value(value: Any) -> Any:
    if isinstance(value, str):
        return value if value.strip() else None
    return value


CURRENCY_SYMBOLS = ("₹", "$", "€", "£", "¥")


def clean_numeric_string(value: Any) -> str:
    """Normalize numeric strings by stripping thousands separators and currency symbols."""
    text = str(value).strip() if value is not None else ""
    if not text:
        return ""
    text = text.replace(",", "")
    for sym in CURRENCY_SYMBOLS:
        text = text.replace(sym, "")
    return text.strip()


def read_business_file(path: str) -> DataTable:
    """Read CSV or the first worksheet of an XLSX file using pure-Python tooling."""
    ext = os.path.splitext(path)[1].lower()
    raw_rows: list[list[Any]] = []
    if ext == ".csv":
        # First attempt UTF-8 (with BOM handling), then fallback to latin-1 for broad compatibility
        lines = None
        for enc in ("utf-8-sig", "latin-1"):
            try:
                with open(path, "r", encoding=enc, newline="") as handle:
                    reader = csv.reader(handle)
                    lines = [row for row in reader]
                break
            except UnicodeDecodeError:
                continue
        if lines is None:
            with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                reader = csv.reader(handle)
                lines = [row for row in reader]
        raw_rows = lines
    elif ext == ".xlsx":
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = workbook.active
            raw_rows = [list(row) for row in sheet.iter_rows(values_only=True)]
        finally:
            workbook.close()
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    # Ignore completely blank trailing rows often left behind by spreadsheets.
    while raw_rows and all(value is None or (isinstance(value, str) and not value.strip()) for value in raw_rows[-1]):
        raw_rows.pop()
    if not raw_rows:
        raise ValueError("The file does not contain a header row or data columns.")

    headers = _unique_headers(raw_rows[0])
    rows: list[dict[str, Any]] = []
    for raw in raw_rows[1:]:
        values = list(raw[:len(headers)])
        if len(values) < len(headers):
            values.extend([None] * (len(headers) - len(values)))
        row = {header: _clean_value(value) for header, value in zip(headers, values)}
        # Preserve genuinely blank rows only if the row contains at least one value.
        if any(value is not None for value in row.values()):
            rows.append(row)
    return DataTable(headers, rows)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer():
            return str(int(value))
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat(sep=" ") if isinstance(value, _dt.datetime) else value.isoformat()
    return str(value).strip()


def _nonempty(values: list[Any]) -> list[Any]:
    return [value for value in values if _text(value) != ""]


def _looks_like_date(value: str) -> bool:
    if not re.search(r"[-/]|[A-Za-z]{3}", value):
        return False
    normalized = value.strip()
    try:
        _dt.datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        return True
    except ValueError:
        pass
    formats = (
        "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y",
        "%d-%m-%Y", "%m-%d-%Y", "%d-%b-%Y", "%d %b %Y",
        "%b %d, %Y", "%Y-%m-%d %H:%M:%S", "%d/%m/%y", "%m/%d/%y",
    )
    for fmt in formats:
        try:
            _dt.datetime.strptime(normalized, fmt)
            return True
        except ValueError:
            continue
    return False


def infer_sql_type(column_name: str, values: list[Any]) -> str:
    vals = [_text(value) for value in _nonempty(values)]
    if not vals:
        return "TEXT"
    name = slugify(column_name)
    tokens = set(name.split("_"))
    # Preserve identifiers and phone/postal numbers as text (leading zeros matter).
    if tokens & {"phone", "mobile", "postal", "postcode", "zip", "sku", "id", "code", "account"}:
        return "TEXT"
    if tokens & DATE_WORDS or any(re.search(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", value) for value in vals[:30]):
        date_ratio = sum(_looks_like_date(value) for value in vals[:200]) / min(len(vals), 200)
        if date_ratio >= 0.75:
            return "TEXT"
    lowered = {value.lower() for value in vals}
    if lowered <= {"true", "false", "yes", "no", "0", "1"} and len(lowered) <= 2:
        return "INTEGER"
    parsed: list[float] = []
    for value in vals:
        try:
            parsed.append(float(clean_numeric_string(value)))
        except ValueError:
            continue
    ratio = len(parsed) / len(vals)
    if ratio >= 0.95:
        if all(number.is_integer() for number in parsed):
            return "INTEGER"
        return "REAL"
    return "TEXT"


def _is_identifierish(name: str) -> bool:
    tokens = set(slugify(name).split("_"))
    return bool(tokens & ID_WORDS) or slugify(name).endswith("_id") or slugify(name).endswith("_key")


def profile_file(file_id: str, original_filename: str, path: str, table: DataTable, used_table_names: set[str]) -> dict[str, Any]:
    base = slugify(os.path.splitext(original_filename)[0], "business_data")
    table_name = base
    suffix = 2
    while table_name in used_table_names:
        table_name = f"{base}_{suffix}"
        suffix += 1
    used_table_names.add(table_name)

    original_cols = [str(c) for c in table.columns]
    db_cols = unique_names(original_cols)
    col_profiles = []
    for original, db_name in zip(original_cols, db_cols):
        values = table[original]
        nonempty = _nonempty(values)
        unique_count = len({_text(value).casefold() for value in nonempty})
        total = len(values)
        null_count = total - len(nonempty)
        sql_type = infer_sql_type(original, values)
        examples = []
        for value in nonempty:
            sample = _text(value)
            if sample not in examples:
                examples.append(sample[:70])
            if len(examples) >= 3:
                break
        unique_ratio = unique_count / max(1, len(nonempty))
        filled_ratio = len(nonempty) / max(1, total)
        semantic_bonus = 0.2 if _is_identifierish(original) else 0.0
        pk_score = (0.55 * unique_ratio) + (0.25 * filled_ratio) + semantic_bonus
        col_profiles.append({
            "original_name": original,
            "name": db_name,
            "sql_type": sql_type,
            "total_count": total,
            "null_count": null_count,
            "null_pct": round((null_count / max(1, total)) * 100, 1),
            "unique_count": unique_count,
            "unique_ratio": round(unique_ratio, 4),
            "filled_ratio": round(filled_ratio, 4),
            "identifier_like": _is_identifierish(original),
            "pk_score": round(pk_score, 3),
            "samples": examples,
        })

    viable = [c for c in col_profiles if c["unique_ratio"] >= 0.995 and c["filled_ratio"] >= 0.98]
    viable.sort(key=lambda c: (c["identifier_like"], c["pk_score"], c["unique_ratio"]), reverse=True)
    primary_key = viable[0]["name"] if viable else None
    for col in col_profiles:
        col["is_primary_key"] = col["name"] == primary_key

    row_signatures = [tuple(_text(row.get(column)).casefold() for column in original_cols) for row in table.rows]
    duplicate_rows = len(row_signatures) - len(set(row_signatures))
    return {
        "id": file_id,
        "filename": original_filename,
        "path": path,
        "table_name": table_name,
        "row_count": len(table),
        "column_count": len(table.columns),
        "duplicate_rows": duplicate_rows,
        "columns": col_profiles,
        "primary_key": primary_key,
    }


def _name_similarity(source_col: str, target_col: str, target_table: str) -> float:
    s = slugify(source_col)
    t = slugify(target_col)
    if s == t:
        return 1.0
    if s.replace("_", "") == t.replace("_", ""):
        return 0.95
    source_tokens = set(s.split("_"))
    target_tokens = set(t.split("_"))
    table_tokens = set(slugify(target_table).split("_"))
    overlap = len(source_tokens & target_tokens) / max(1, len(source_tokens | target_tokens))
    if table_tokens and table_tokens <= source_tokens and ("id" in source_tokens or "key" in source_tokens):
        overlap = max(overlap, 0.8)
    ratio = difflib.SequenceMatcher(None, s, t).ratio()
    return max(overlap, ratio * 0.8)


def _value_set(values: list[Any]) -> set[str]:
    return {_text(value) for value in values if _text(value) != ""}


def _compatible_types(a: str, b: str) -> float:
    numeric = {"INTEGER", "REAL"}
    if a == b:
        return 1.0
    if a in numeric and b in numeric:
        return 0.9
    return 0.55 if "TEXT" in {a, b} else 0.25


def analyze_paths(files: list[dict[str, str]]) -> dict[str, Any]:
    """Analyze uploaded files and return JSON-serializable profiles and relationship proposals."""
    tables_by_id: dict[str, DataTable] = {}
    used_table_names: set[str] = set()
    profiles = []
    for item in files:
        table = read_business_file(item["path"])
        if len(table) > 100_000:
            raise ValueError(f"{item['filename']} has more than 100,000 rows; the demo limit is 100,000 rows per file.")
        tables_by_id[item["id"]] = table
        profiles.append(profile_file(item["id"], item["filename"], item["path"], table, used_table_names))

    relationships = []
    for source in profiles:
        source_table = tables_by_id[source["id"]]
        for source_col in source["columns"]:
            for target in profiles:
                if target["id"] == source["id"] or not target.get("primary_key"):
                    continue
                target_col = next(c for c in target["columns"] if c["name"] == target["primary_key"])
                name_score = _name_similarity(source_col["original_name"], target_col["original_name"], target["table_name"])
                if name_score < 0.35:
                    continue
                source_vals = _value_set(source_table[source_col["original_name"]])
                target_table = tables_by_id[target["id"]]
                target_vals = _value_set(target_table[target_col["original_name"]])
                if not source_vals or not target_vals:
                    continue
                overlap_count = len(source_vals & target_vals)
                coverage = overlap_count / max(1, len(source_vals))
                type_score = _compatible_types(source_col["sql_type"], target_col["sql_type"])
                confidence = (0.35 * name_score) + (0.55 * coverage) + (0.10 * type_score)
                if (coverage >= 0.25 and name_score >= 0.45) or (coverage >= 0.65 and name_score >= 0.25):
                    relationships.append({
                        "source_table": source["table_name"],
                        "source_file_id": source["id"],
                        "source_column": source_col["name"],
                        "source_column_original": source_col["original_name"],
                        "target_table": target["table_name"],
                        "target_file_id": target["id"],
                        "target_column": target_col["name"],
                        "target_column_original": target_col["original_name"],
                        "name_similarity": round(name_score, 3),
                        "coverage": round(coverage, 3),
                        "matched_distinct_values": overlap_count,
                        "source_distinct_values": len(source_vals),
                        "confidence": round(confidence, 3),
                        "confidence_pct": round(confidence * 100),
                        "enforceable": coverage >= 0.999999,
                        "reason": _relationship_reason(name_score, coverage, type_score),
                    })

    relationships.sort(key=lambda r: (r["confidence"], r["coverage"]), reverse=True)
    selected_best = []
    seen_source_cols: set[tuple[str, str]] = set()
    for rel in relationships:
        key = (rel["source_table"], rel["source_column"])
        if key in seen_source_cols:
            continue
        seen_source_cols.add(key)
        rel["suggestion_id"] = len(selected_best)
        selected_best.append(rel)

    return {
        "tables": profiles,
        "relationships": selected_best,
        "summary": {
            "file_count": len(profiles),
            "row_count": sum(p["row_count"] for p in profiles),
            "column_count": sum(p["column_count"] for p in profiles),
            "relationship_count": len(selected_best),
            "duplicate_rows": sum(p["duplicate_rows"] for p in profiles),
        },
    }


def _relationship_reason(name_score: float, coverage: float, type_score: float) -> str:
    bits = []
    if name_score >= 0.9:
        bits.append("column names match closely")
    elif name_score >= 0.6:
        bits.append("column names are semantically similar")
    if coverage >= 0.98:
        bits.append("all or nearly all source values exist in the target key")
    elif coverage >= 0.7:
        bits.append("most source values exist in the target key")
    else:
        bits.append("some source values overlap the target key")
    if type_score >= 0.9:
        bits.append("data types are compatible")
    return "; ".join(bits)
