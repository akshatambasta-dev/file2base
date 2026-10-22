"""Export engine for File2Base.

Produces unified clean Excel master workbooks and CSV ZIP archives directly
from the generated SQLite database.
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
import zipfile
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def _quote(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def get_tables_data(db_path: str) -> dict[str, dict[str, Any]]:
    """Retrieve all table structures and rows from the generated database."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        tables = [
            r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'file2base_relationships' ORDER BY name"
            ).fetchall()
        ]
        result: dict[str, dict[str, Any]] = {}
        for t in tables:
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({_quote(t)})").fetchall()]
            rows = [list(r) for r in con.execute(f"SELECT * FROM {_quote(t)}").fetchall()]
            result[t] = {"columns": cols, "rows": rows}
        return result
    finally:
        con.close()


def export_unified_excel(db_path: str) -> io.BytesIO:
    """Generate a clean, multi-tab Excel master workbook from the SQLite database."""
    tables_data = get_tables_data(db_path)
    wb = Workbook()

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="172B58", end_color="172B58", fill_type="solid")
    header_align = Alignment(horizontal="left", vertical="center")

    if not tables_data:
        ws = wb.active
        ws.title = "Empty"
        ws.append(["No tables found in generated database"])
    else:
        first_sheet = True
        for table_name, data in tables_data.items():
            # Sanitize tab name: Excel forbids \ / ? * : [ ] and max 31 chars
            safe_title = re.sub(r'[\/?:*\[\]]', '_', table_name)[:31]
            if first_sheet:
                ws = wb.active
                ws.title = safe_title
                first_sheet = False
            else:
                ws = wb.create_sheet(title=safe_title)

            # Write header row
            ws.append(data["columns"])
            for col_idx in range(1, len(data["columns"]) + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_align

            # Write record rows
            for row in data["rows"]:
                ws.append(row)

            # Auto-adjust column widths based on cell content
            for col_idx, col_name in enumerate(data["columns"], 1):
                max_len = len(str(col_name))
                for row in data["rows"][:50]:
                    val = row[col_idx - 1]
                    if val is not None:
                        max_len = max(max_len, len(str(val)))
                col_letter = get_column_letter(col_idx)
                ws.column_dimensions[col_letter].width = min(max(max_len + 3, 10), 45)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def export_csv_zip(db_path: str) -> io.BytesIO:
    """Generate a ZIP archive containing individual cleaned CSV files for each table."""
    tables_data = get_tables_data(db_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for table_name, data in tables_data.items():
            csv_buf = io.StringIO()
            writer = csv.writer(csv_buf)
            writer.writerow(data["columns"])
            for row in data["rows"]:
                writer.writerow(row)
            # Encode with UTF-8 BOM so Excel opens CSVs with proper international/currency display
            zf.writestr(f"{table_name}.csv", csv_buf.getvalue().encode("utf-8-sig"))

    buf.seek(0)
    return buf
