"""Phase 5 bounded CSV/XLSX analytics acceptance tests."""
from __future__ import annotations

import io
import unittest
from decimal import Decimal

from nexus_ai.data_analytics import AnalyticsInputError, AnalyticsLimits, analyze_table


def csv_table(source: str) -> dict:
    return analyze_table(
        source.encode("utf-8"), file_type="csv",
        group_column="Company", amount_column="Revenue",
    )


class BoundedAnalyticsTests(unittest.TestCase):
    def test_exact_decimal_financial_totals_with_arabic_labels(self):
        result = csv_table(
            "Company,Revenue,Year\nموبايلي,0.10,2025\n"
            "موبايلي,0.20,2025\nأرامكو,19.41,2025\n"
        )
        self.assertEqual(result["total"], "19.71")
        self.assertEqual(result["row_count"], 3)
        self.assertEqual(result["group_count"], 2)
        self.assertEqual(
            {r["label"]: r["value"] for r in result["chart_data"]},
            {"موبايلي": "0.30", "أرامكو": "19.41"},
        )
        self.assertEqual(result["scope"]["llm_calls"], 0)

    def test_negative_and_zero_values_preserve_math(self):
        result = csv_table("Company,Revenue\nA,10.20\nA,-1.20\nB,0\n")
        self.assertEqual(result["total"], "9.00")
        self.assertEqual({r["label"]: r["value"] for r in result["chart_data"]},
                         {"A": "9.00", "B": "0"})

    def test_reject_bad_numeric_inputs_without_coercion(self):
        for invalid in ["", "NaN", "Infinity", "1e9", "1,000", "SAR 3", "=2+2", "2_000"]:
            # CSV quote protects delimiter cases but still rejects the number.
            source = 'Company,Revenue\nA,"' + invalid + '"\n'
            with self.subTest(invalid=invalid), self.assertRaises(AnalyticsInputError):
                csv_table(source)

    def test_reject_duplicate_or_missing_headings(self):
        for source in ("Company,Company\nA,1\n", "Company,\nA,1\n",
                       "Company,Revenue\nA\n", "Company,Revenue\n"):
            with self.subTest(source=source), self.assertRaises(AnalyticsInputError):
                csv_table(source)

    def test_reject_binary_and_unsupported_encodings(self):
        with self.assertRaises(AnalyticsInputError):
            analyze_table(b"\xff\xfe", file_type="csv",
                          group_column="Company", amount_column="Revenue")
        with self.assertRaises(AnalyticsInputError):
            analyze_table(b"a,b\nx,y", file_type="tsv",
                          group_column="a", amount_column="b")

    def test_csv_limits_and_group_budgets(self):
        with self.assertRaises(AnalyticsInputError):
            analyze_table(b"A,B\nx,1\ny,2\n", file_type="csv",
                          group_column="A", amount_column="B",
                          limits=AnalyticsLimits(max_rows=1))
        with self.assertRaises(AnalyticsInputError):
            analyze_table(b"A,B\nx,1\ny,2\n", file_type="csv",
                          group_column="A", amount_column="B",
                          limits=AnalyticsLimits(max_groups=1))
        with self.assertRaises(AnalyticsInputError):
            analyze_table(b"A,B\nx,1\n", file_type="csv",
                          group_column="A", amount_column="B",
                          limits=AnalyticsLimits(max_file_bytes=5))

    def test_reject_missing_group_values(self):
        with self.assertRaises(AnalyticsInputError):
            csv_table("Company,Revenue\n,1.00\n")

    def test_csv_sheet_selection_rejected(self):
        with self.assertRaises(AnalyticsInputError):
            analyze_table(b"Company,Revenue\nA,1\n", file_type="csv",
                          group_column="Company", amount_column="Revenue",
                          sheet_name="Sheet1")

    def test_xlsx_text_values_and_specific_sheet(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Ignore"
        ws.append(["Company", "Revenue"])
        ws.append(["X", "1"])
        ws2 = wb.create_sheet("Statements")
        ws2.append(["Company", "Revenue", "Year"])
        ws2.append(["موبايلي", "19.641705", "2025"])
        ws2.append(["موبايلي", "-0.641705", "2025"])
        buffer = io.BytesIO()
        wb.save(buffer)
        result = analyze_table(buffer.getvalue(), file_type="xlsx",
                               sheet_name="Statements",
                               group_column="Company", amount_column="Revenue")
        self.assertEqual(result["total"], "19.000000")
        self.assertEqual(result["sheet_name"], "Statements")

    def test_xlsx_formula_cells_rejected_not_executed(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["Company", "Revenue"])
        ws.append(["X", "=1+1"])
        buffer = io.BytesIO()
        wb.save(buffer)
        with self.assertRaises(AnalyticsInputError):
            analyze_table(buffer.getvalue(), file_type="xlsx",
                          group_column="Company", amount_column="Revenue")

    def test_xlsx_invalid_zip_and_missing_sheet(self):
        with self.assertRaises(AnalyticsInputError):
            analyze_table(b"not a workbook", file_type="xlsx",
                          group_column="Company", amount_column="Revenue")
        from openpyxl import Workbook
        wb = Workbook()
        wb.active.append(["Company", "Revenue"])
        wb.active.append(["A", "1"])
        buffer = io.BytesIO()
        wb.save(buffer)
        with self.assertRaises(AnalyticsInputError):
            analyze_table(buffer.getvalue(), file_type="xlsx",
                          group_column="Company", amount_column="Revenue",
                          sheet_name="Unapproved")

    def test_xlsx_numeric_float_must_not_be_silently_coerced(self):
        from openpyxl import Workbook
        wb = Workbook()
        wb.active.append(["Company", "Revenue"])
        wb.active.append(["A", 0.1])
        buffer = io.BytesIO()
        wb.save(buffer)
        with self.assertRaises(AnalyticsInputError):
            analyze_table(buffer.getvalue(), file_type="xlsx",
                          group_column="Company", amount_column="Revenue")


if __name__ == "__main__":
    unittest.main()
