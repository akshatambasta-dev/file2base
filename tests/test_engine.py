"""Smoke test for File2Base's local analysis and SQLite migration engine."""
import shutil
import tempfile
import unittest
from pathlib import Path

from engine.analyzer import analyze_paths, clean_numeric_string
from engine.database_builder import _convert_value, browse_table, create_database, inspect_database
from engine.preflight import build_migration_preflight

ROOT = Path(__file__).resolve().parents[1]


class File2BaseEngineTests(unittest.TestCase):
    def test_sample_data_analyzes_and_migrates(self):
        with tempfile.TemporaryDirectory(prefix="file2base-test-") as temp:
            workspace = Path(temp)
            upload_dir = workspace / "uploads"
            upload_dir.mkdir()
            files = []
            for index, source in enumerate(sorted((ROOT / "sample_data").iterdir())):
                target = upload_dir / source.name
                shutil.copy2(source, target)
                files.append({"id": f"demo{index}", "filename": source.name, "path": str(target)})

            analysis = analyze_paths(files)
            self.assertEqual(analysis["summary"]["file_count"], 6)
            self.assertEqual(analysis["summary"]["row_count"], 41)
            self.assertGreaterEqual(analysis["summary"]["relationship_count"], 5)

            links = {(r["source_table"], r["source_column"], r["target_table"]) for r in analysis["relationships"]}
            self.assertIn(("orders", "customer_id", "customers"), links)
            self.assertIn(("order_items", "product_id", "products"), links)

            all_ids = [r["suggestion_id"] for r in analysis["relationships"]]
            result = create_database(str(workspace), analysis, all_ids)
            self.assertEqual(result["table_count"], 6)
            self.assertEqual(result["row_count"], 41)
            self.assertEqual(result["foreign_key_violations"], 0)

            info = inspect_database(result["db_path"])
            self.assertEqual(len(info["tables"]), 6)
            self.assertEqual(len(info["relationships"]), len(all_ids))
            customers = browse_table(result["db_path"], "customers")
            self.assertEqual(customers["total"], 8)
            self.assertIn("customer_id", customers["columns"])

    def test_numeric_conversion_does_not_truncate_fractional_values(self):
        self.assertEqual(_convert_value("10.5", "INTEGER"), "10.5")
        self.assertEqual(_convert_value("10", "INTEGER"), 10)

    def test_currency_conversion_and_numeric_cleaning(self):
        # clean_numeric_string handling of currencies and formatting
        self.assertEqual(clean_numeric_string("$1,250.00"), "1250.00")
        self.assertEqual(clean_numeric_string("₹ 4,500"), "4500")
        self.assertEqual(clean_numeric_string("€99.95"), "99.95")
        self.assertEqual(clean_numeric_string("£10"), "10")
        self.assertEqual(clean_numeric_string("¥500"), "500")
        self.assertEqual(clean_numeric_string(""), "")
        self.assertEqual(clean_numeric_string(None), "")

        # _convert_value consistency between INTEGER and REAL with currency symbols
        self.assertEqual(_convert_value("$100", "INTEGER"), 100)
        self.assertEqual(_convert_value("₹5,000", "INTEGER"), 5000)
        self.assertEqual(_convert_value("€49.99", "REAL"), 49.99)
        self.assertEqual(_convert_value("£1,234.56", "REAL"), 1234.56)
        self.assertEqual(_convert_value("$10.5", "INTEGER"), "10.5")

    def test_relationships_can_be_rejected(self):
        with tempfile.TemporaryDirectory(prefix="file2base-test-") as temp:
            workspace = Path(temp)
            upload_dir = workspace / "uploads"
            upload_dir.mkdir()
            files = []
            for index, source in enumerate(sorted((ROOT / "sample_data").iterdir())):
                target = upload_dir / source.name
                shutil.copy2(source, target)
                files.append({"id": f"demo{index}", "filename": source.name, "path": str(target)})
            analysis = analyze_paths(files)
            result = create_database(str(workspace), analysis, [])
            info = inspect_database(result["db_path"])
            self.assertEqual(len(info["relationships"]), 0)
            self.assertEqual(result["row_count"], 41)

    def test_preflight_checks_relationships_before_writing(self):
        with tempfile.TemporaryDirectory(prefix="file2base-preflight-") as temp:
            workspace = Path(temp)
            upload_dir = workspace / "uploads"
            upload_dir.mkdir()
            files = []
            for index, source in enumerate(sorted((ROOT / "sample_data").iterdir())):
                target = upload_dir / source.name
                shutil.copy2(source, target)
                files.append({"id": f"pf{index}", "filename": source.name, "path": str(target)})
            analysis = analyze_paths(files)
            ids = [rel["suggestion_id"] for rel in analysis["relationships"]]

            preview = build_migration_preflight(analysis, ids)
            self.assertTrue(preview["can_migrate"])
            self.assertEqual(preview["table_count"], 6)
            self.assertEqual(preview["row_count"], 41)
            self.assertEqual(preview["relationship_count"], 5)
            self.assertEqual(preview["enforced_relationship_count"], 5)
            self.assertEqual(preview["blocker_count"], 0)

            # Selecting a generated key is valid, but relationships aimed at the
            # old source key must be left as recommendations rather than FKs.
            overrides = {table["table_name"]: "__generated__" for table in analysis["tables"] if table["table_name"] == "products"}
            preview_generated = build_migration_preflight(analysis, ids, primary_key_overrides=overrides)
            self.assertTrue(preview_generated["can_migrate"])
            self.assertEqual(preview_generated["enforced_relationship_count"], 3)

    def test_failed_replacement_preserves_last_good_database(self):
        with tempfile.TemporaryDirectory(prefix="file2base-atomic-") as temp:
            workspace = Path(temp)
            upload_dir = workspace / "uploads"
            upload_dir.mkdir()
            files = []
            for index, source in enumerate(sorted((ROOT / "sample_data").iterdir())):
                target = upload_dir / source.name
                shutil.copy2(source, target)
                files.append({"id": f"atomic{index}", "filename": source.name, "path": str(target)})
            analysis = analyze_paths(files)
            ids = [rel["suggestion_id"] for rel in analysis["relationships"]]
            first = create_database(str(workspace), analysis, ids)
            database_path = Path(first["db_path"])
            self.assertTrue(database_path.exists())

            customers = next(Path(item["path"]) for item in files if item["filename"] == "customers.csv")
            lines = customers.read_text(encoding="utf-8-sig").splitlines()
            # Reuse the first customer ID in the final row to make insertion fail.
            first_id = lines[1].split(",")[0]
            last_parts = lines[-1].split(",")
            last_parts[0] = first_id
            lines[-1] = ",".join(last_parts)
            customers.write_text("\n".join(lines) + "\n", encoding="utf-8")

            with self.assertRaises(Exception):
                create_database(str(workspace), analysis, ids)
            self.assertTrue(database_path.exists(), "the prior successful DB should survive a failed replacement")
            self.assertEqual(browse_table(str(database_path), "customers")["total"], 8)
            self.assertFalse(Path(str(database_path) + ".tmp").exists())

    def test_quality_summary_calculation(self):
        from engine.quality import build_quality_summary
        mock_analysis = {
            "tables": [
                {
                    "row_count": 100,
                    "duplicate_rows": 0,
                    "primary_key": "id",
                    "columns": [
                        {"filled_ratio": 1.0, "unique_ratio": 1.0},
                        {"filled_ratio": 0.95, "unique_ratio": 0.5},
                    ],
                }
            ],
            "relationships": [
                {"coverage": 1.0}
            ],
        }
        summary = build_quality_summary(mock_analysis)
        self.assertIn("score", summary)
        self.assertGreaterEqual(summary["score"], 80)
        self.assertEqual(summary["label"], "Strong starting point")
        self.assertTrue(summary["is_heuristic"])

    def test_latin1_encoded_csv_reading(self):
        from engine.analyzer import read_business_file
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="wb", delete=False) as f:
            # Contains Café and naïve in latin-1 (0xe9 and 0xef)
            content = "id,name,city\n1,Caf\xe9,Paris\n2,na\xefve,Lyon\n".encode("latin-1")
            f.write(content)
            temp_path = f.name
        try:
            table = read_business_file(temp_path)
            self.assertEqual(len(table), 2)
            self.assertEqual(table.columns, ["id", "name", "city"])
            self.assertIn("Caf", table.rows[0]["name"])
        finally:
            Path(temp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
