"""Business Intelligence and insights engine for File2Base.

Auto-detects commercial entities (orders, sales, customers, inventory, products)
and computes high-value, plain-language business metrics, category breakdowns,
and actionable cross-file disconnect alerts from the generated SQLite database.
"""
from __future__ import annotations

import sqlite3
from typing import Any


def _quote(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def generate_business_insights(db_path: str) -> dict[str, Any]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        tables = [
            r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'file2base_relationships' ORDER BY name"
            ).fetchall()
        ]

        insights: dict[str, Any] = {
            "has_commercial_data": False,
            "kpis": [],
            "charts": [],
            "disconnects": [],
            "highlights": [],
            "entity_counts": {},
        }

        # Gather table metadata & row counts
        table_cols: dict[str, list[dict[str, Any]]] = {}
        for t in tables:
            cols = [dict(r) for r in con.execute(f"PRAGMA table_info({_quote(t)})").fetchall()]
            cnt = con.execute(f"SELECT COUNT(*) FROM {_quote(t)}").fetchone()[0]
            table_cols[t] = cols
            insights["entity_counts"][t] = cnt

        # 1. Detect Financial / Order / Revenue Signals
        revenue_found = False
        for t, cols in table_cols.items():
            col_names = {c["name"].lower(): c["name"] for c in cols}
            # Look for monetary/total columns
            amount_col = None
            for cand in ("order_total", "total", "amount", "price", "revenue", "spend", "sales", "subtotal"):
                if cand in col_names:
                    amount_col = col_names[cand]
                    break

            if amount_col:
                try:
                    res = con.execute(
                        f"SELECT COUNT(*), SUM(CAST({_quote(amount_col)} AS REAL)), AVG(CAST({_quote(amount_col)} AS REAL)) FROM {_quote(t)} WHERE {_quote(amount_col)} IS NOT NULL"
                    ).fetchone()
                    count, total, avg = res[0], res[1], res[2]
                    if count and total is not None and total > 0:
                        revenue_found = True
                        insights["has_commercial_data"] = True
                        insights["kpis"].append({
                            "label": "RECORDED REVENUE",
                            "value": f"{total:,.2f}",
                            "subtext": f"Across {count:,} records in {t}",
                            "badge": "Revenue",
                            "badge_type": "green",
                        })
                        insights["kpis"].append({
                            "label": "AVERAGE VALUE",
                            "value": f"{avg:,.2f}",
                            "subtext": f"Per recorded {t.rstrip('s')}",
                            "badge": "Avg Order",
                            "badge_type": "blue",
                        })

                        # Categorical breakdown if there's a status or category column
                        for status_cand in ("order_status", "status", "category", "type", "payment_status"):
                            if status_cand in col_names:
                                stat_col = col_names[status_cand]
                                breakdown = con.execute(
                                    f"SELECT {_quote(stat_col)} as label, COUNT(*) as count, SUM(CAST({_quote(amount_col)} AS REAL)) as total FROM {_quote(t)} WHERE {_quote(stat_col)} IS NOT NULL GROUP BY {_quote(stat_col)} ORDER BY count DESC LIMIT 6"
                                ).fetchall()
                                if len(breakdown) > 1:
                                    max_count = max(r["count"] for r in breakdown) or 1
                                    insights["charts"].append({
                                        "title": f"{t.title()} by {stat_col.replace('_', ' ').title()}",
                                        "type": "bars",
                                        "rows": [
                                            {
                                                "label": str(r["label"]).title(),
                                                "count": r["count"],
                                                "amount": f"{r['total']:,.2f}" if r["total"] is not None else None,
                                                "pct": round((r["count"] / count) * 100),
                                                "bar_pct": round((r["count"] / max_count) * 100),
                                            }
                                            for r in breakdown
                                        ],
                                    })
                                break
                        break
                except Exception:
                    pass

        # 2. Customer Breakdown / Demographics
        customer_table = None
        for t in tables:
            if any(term in t.lower() for term in ("customer", "client", "buyer", "user", "account")):
                customer_table = t
                break

        if customer_table:
            cols = {c["name"].lower(): c["name"] for c in table_cols[customer_table]}
            count = insights["entity_counts"].get(customer_table, 0)
            insights["kpis"].append({
                "label": "REGISTERED CUSTOMERS",
                "value": f"{count:,}",
                "subtext": f"Unique profiles in {customer_table}",
                "badge": "Customer Base",
                "badge_type": "navy",
            })

            # Check for city/region or customer_type distribution
            for loc_cand in ("city", "region", "state", "country", "customer_type", "type", "tier"):
                if loc_cand in cols:
                    loc_col = cols[loc_cand]
                    geo_data = con.execute(
                        f"SELECT {_quote(loc_col)} as label, COUNT(*) as cnt FROM {_quote(customer_table)} WHERE {_quote(loc_col)} IS NOT NULL GROUP BY {_quote(loc_col)} ORDER BY cnt DESC LIMIT 5"
                    ).fetchall()
                    if len(geo_data) > 1:
                        max_cnt = max(r["cnt"] for r in geo_data) or 1
                        insights["charts"].append({
                            "title": f"Top Customers by {loc_col.replace('_', ' ').title()}",
                            "type": "geo",
                            "rows": [
                                {
                                    "label": str(r["label"]).title(),
                                    "count": r["cnt"],
                                    "pct": round((r["cnt"] / count) * 100) if count else 0,
                                    "bar_pct": round((r["cnt"] / max_cnt) * 100),
                                }
                                for r in geo_data
                            ],
                        })
                    break

        # 3. Inventory / Stock Signals
        inventory_table = None
        for t in tables:
            if any(term in t.lower() for term in ("inventory", "stock", "warehouse", "product")):
                inventory_table = t
                break

        if inventory_table:
            cols = {c["name"].lower(): c["name"] for c in table_cols[inventory_table]}
            qty_col = None
            for cand in ("quantity_available", "quantity", "qty", "stock_level", "stock", "units"):
                if cand in cols:
                    qty_col = cols[cand]
                    break
            if qty_col:
                try:
                    res = con.execute(
                        f"SELECT SUM(CAST({_quote(qty_col)} AS REAL)), COUNT(*), MIN(CAST({_quote(qty_col)} AS REAL)) FROM {_quote(inventory_table)} WHERE {_quote(qty_col)} IS NOT NULL"
                    ).fetchone()
                    total_units, count, min_qty = res[0], res[1], res[2]
                    if total_units is not None:
                        insights["kpis"].append({
                            "label": "STOCK ON HAND",
                            "value": f"{int(total_units):,}",
                            "subtext": f"Across {count:,} inventory lines",
                            "badge": "Inventory",
                            "badge_type": "amber" if (min_qty is not None and min_qty < 10) else "green",
                        })

                        # Warehouse / facility breakdown chart
                        for wh_cand in ("warehouse", "location", "facility", "store", "bin"):
                            if wh_cand in cols:
                                wh_col = cols[wh_cand]
                                wh_data = con.execute(
                                    f"SELECT {_quote(wh_col)} as label, SUM(CAST({_quote(qty_col)} AS REAL)) as units FROM {_quote(inventory_table)} WHERE {_quote(wh_col)} IS NOT NULL GROUP BY {_quote(wh_col)} ORDER BY units DESC LIMIT 5"
                                ).fetchall()
                                if len(wh_data) > 1 and total_units > 0:
                                    max_u = max(r["units"] for r in wh_data) or 1
                                    insights["charts"].append({
                                        "title": f"Stock Distribution by {wh_col.replace('_', ' ').title()}",
                                        "type": "bars",
                                        "rows": [
                                            {
                                                "label": str(r["label"]).title(),
                                                "count": int(r["units"]),
                                                "pct": round((r["units"] / total_units) * 100),
                                                "bar_pct": round((r["units"] / max_u) * 100),
                                            }
                                            for r in wh_data
                                        ],
                                    })
                                break
                except Exception:
                    pass

        # 4. Actionable Business Disconnects / Orphan Record Analysis
        # Check if there are foreign keys or accepted relationships with unmatched records
        try:
            rel_rows = con.execute(
                "SELECT source_table, source_column, target_table, target_column, coverage FROM file2base_relationships WHERE coverage < 1.0"
            ).fetchall()
            for r in rel_rows:
                src_t, src_c, tgt_t, tgt_c = r[0], r[1], r[2], r[3]
                try:
                    missing = con.execute(
                        f"SELECT COUNT(*) FROM {_quote(src_t)} WHERE {_quote(src_c)} IS NOT NULL AND {_quote(src_c)} NOT IN (SELECT {_quote(tgt_c)} FROM {_quote(tgt_t)} WHERE {_quote(tgt_c)} IS NOT NULL)"
                    ).fetchone()[0]
                    if missing > 0:
                        insights["disconnects"].append({
                            "title": f"{missing} {src_t.rstrip('s').replace('_', ' ')} record(s) missing matching {tgt_t.rstrip('s')}",
                            "detail": f"{missing} row(s) in '{src_t}' have '{src_c}' entries that do not exist in '{tgt_t}.{tgt_c}'. In a spreadsheet this causes #N/A errors; in your database, these records are flagged so you can reconcile them.",
                            "source_table": src_t,
                            "target_table": tgt_t,
                            "missing_count": missing,
                        })
                except Exception:
                    pass
        except sqlite3.OperationalError:
            pass

        # If no commercial KPIs were triggered, generate generic high-level business entity KPIs
        if not insights["kpis"]:
            total_records = sum(insights["entity_counts"].values())
            insights["kpis"].append({
                "label": "BUSINESS ENTITIES",
                "value": str(len(tables)),
                "subtext": "Clean, structured tables",
                "badge": "Catalog",
                "badge_type": "blue",
            })
            insights["kpis"].append({
                "label": "TOTAL MANAGED RECORDS",
                "value": f"{total_records:,}",
                "subtext": "Consolidated without duplicates",
                "badge": "Records",
                "badge_type": "green",
            })

        # Summary statement for the owner
        if revenue_found:
            insights["summary_heading"] = "Your unified business operations at a glance"
            insights["summary_text"] = "Your customer, order, and inventory spreadsheets have been structured into linked entities. You can now track repeat buyers, monitor live stock levels, and query your entire business without manual VLOOKUPs."
        else:
            insights["summary_heading"] = "Your unified data structure is live"
            insights["summary_text"] = "Your raw spreadsheets are now structured into a unified relational database with consistent identifiers and checked connections."

        return insights
    finally:
        con.close()
