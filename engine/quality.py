"""Transparent heuristic profiling indicators used by the File2Base prototype."""
from __future__ import annotations


def build_quality_summary(analysis: dict) -> dict:
    """Compute an interpretable quality indicator from observed profiles."""
    tables = analysis.get("tables", [])
    total_rows = sum(int(table.get("row_count", 0) or 0) for table in tables)
    total_cells = sum(int(table.get("row_count", 0) or 0) * len(table.get("columns", [])) for table in tables)
    observed_cells = 0.0
    key_scores: list[float] = []
    for table in tables:
        row_count = int(table.get("row_count", 0) or 0)
        columns = table.get("columns", [])
        for col in columns:
            filled = col.get("filled_ratio")
            if filled is None:
                filled = 1 - (float(col.get("null_pct", 0) or 0) / 100)
            observed_cells += row_count * max(0.0, min(1.0, float(filled or 0)))
        chosen_pk = table.get("primary_key")
        key_col = next((col for col in columns if col.get("name") == chosen_pk), None)
        if key_col:
            filled_ratio = max(0.0, min(1.0, float(key_col.get("filled_ratio", 0) or 0)))
            unique_ratio = max(0.0, min(1.0, float(key_col.get("unique_ratio", 0) or 0)))
            key_scores.append(100 * min(filled_ratio, unique_ratio))
        else:
            key_scores.append(70.0)
    completeness = 100.0 if total_cells == 0 else 100 * observed_cells / total_cells
    duplicate_rows = int(analysis.get("summary", {}).get("duplicate_rows", 0) or 0)
    duplicate_cleanliness = 100.0 if total_rows == 0 else 100 * max(0.0, 1 - min(1.0, duplicate_rows / total_rows))
    identifier_readiness = sum(key_scores) / len(key_scores) if key_scores else 70.0
    relationships = analysis.get("relationships", [])
    relationship_coverage = (
        sum(max(0.0, min(1.0, float(rel.get("coverage", 0) or 0))) * 100 for rel in relationships) / len(relationships)
        if relationships else 75.0
    )
    score = round(0.40 * completeness + 0.20 * duplicate_cleanliness + 0.25 * identifier_readiness + 0.15 * relationship_coverage)
    recommendations = []
    if completeness < 98:
        recommendations.append("Review missing values before relying on reports or joins.")
    if duplicate_rows:
        recommendations.append(f"Inspect {duplicate_rows:,} exact duplicate row(s); they are preserved unless you choose otherwise.")
    fuzzy_candidates = sum(len(table.get("fuzzy_duplicates", [])) for table in tables)
    if fuzzy_candidates:
        recommendations.append(f"Inspect {fuzzy_candidates} potential fuzzy duplicate candidate(s) in entity fields (slight spelling/spacing variances).")
    if any(not table.get("primary_key") for table in tables):
        recommendations.append("At least one table needs a generated row ID or a manually selected identifier.")
    if relationships and any(float(rel.get("coverage", 0) or 0) < 0.98 for rel in relationships):
        recommendations.append("Review links with incomplete value coverage before enforcing foreign keys.")
    if not recommendations:
        recommendations.append("No major profiling flags surfaced. Confirm identifiers and relationships before migration.")
    return {
        "score": max(0, min(100, score)),
        "label": "Strong starting point" if score >= 85 else "Review recommended" if score >= 70 else "Needs attention",
        "completeness": round(completeness),
        "duplicate_cleanliness": round(duplicate_cleanliness),
        "identifier_readiness": round(identifier_readiness),
        "relationship_coverage": round(relationship_coverage),
        "duplicate_rows": duplicate_rows,
        "fuzzy_duplicates": fuzzy_candidates,
        "total_rows": total_rows,
        "table_count": len(tables),
        "recommendations": recommendations,
        "is_heuristic": True,
    }
