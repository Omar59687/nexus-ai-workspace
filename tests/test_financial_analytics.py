"""Financial year, unit, and precision gates for Phase 5."""
from __future__ import annotations

import io
import unittest

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_analytics import analyze_financial_series


def data(rows):
    return ("Company,Year,Metric,Value,Currency,Unit\n" + "\n".join(rows) + "\n").encode("utf-8")


def run(rows, **options):
    args = dict(file_type="csv", company="Mobily", metric="revenue", currency="SAR",
                unit="thousands", start_year=2024, end_year=2025)
    args.update(options)
    return analyze_financial_series(data(rows), **args)


class FinancialAnalyticsTests(unittest.TestCase):
    def test_realistic_mobily_comparative_values_and_exact_growth(self):
        result = run([
            "Mobily,2024,revenue,18206447,SAR,thousands",
            "Mobily,2025,revenue,19641705,SAR,thousands",
            "Other,2025,revenue,999999999,SAR,thousands",
            "Mobily,2025,net_income,1,SAR,thousands",
        ])
        self.assertEqual(result["rows_selected"], 2)
        self.assertEqual([r["amount"] for r in result["annual"]],
                         ["18206447", "19641705"])
        self.assertEqual(result["annual"][1]["yoy_percent"], "7.8827")
        self.assertEqual(result["chart"]["y_axis"], "SAR thousands")
        self.assertEqual(result["chart"]["data"][1]["value"], "19641705")

    def test_zero_baseline_abstains(self):
        result = run(["Mobily,2024,revenue,0,SAR,thousands",
                      "Mobily,2025,revenue,100,SAR,thousands"])
        self.assertIsNone(result["annual"][1]["yoy_percent"])
        self.assertEqual(result["annual"][1]["yoy_unavailable_reason"], "zero_baseline")

    def test_nonconsecutive_years_do_not_generate_fake_growth(self):
        result = run(["Mobily,2023,revenue,90,SAR,thousands",
                      "Mobily,2025,revenue,110,SAR,thousands"], start_year=2023)
        self.assertIsNone(result["annual"][1]["yoy_percent"])
        self.assertEqual(result["annual"][1]["yoy_unavailable_reason"], "nonconsecutive_years")

    def test_aggregations_are_decimal_exact(self):
        result = run(["Mobily,2025,revenue,0.1,SAR,thousands",
                      "Mobily,2025,revenue,0.2,SAR,thousands"])
        self.assertEqual(result["annual"][0]["amount"], "0.3")
        self.assertEqual(result["rows_selected"], 2)

    def test_mixed_currencies_and_units_fail_closed(self):
        for row in ("Mobily,2025,revenue,100,USD,thousands",
                    "Mobily,2025,revenue,100,SAR,millions"):
            with self.subTest(row=row), self.assertRaisesRegex(AnalyticsInputError, "mixed currency or unit"):
                run(["Mobily,2024,revenue,10,SAR,thousands", row])

    def test_mismatched_metric_or_company_are_not_included(self):
        result = run(["Mobily,2025,revenue,5,SAR,thousands",
                      "Other,2025,revenue,500,SAR,thousands",
                      "Mobily,2025,net_income,700,SAR,thousands"])
        self.assertEqual(result["annual"][0]["amount"], "5")

    def test_reject_malformed_values_even_outside_filter(self):
        for row in ("Other,2025,revenue,NaN,SAR,thousands",
                    "Other,2025,revenue,10,USD,bogus",
                    "Other,2025,revenue,10,USD,thousands\nOther,20x5,revenue,10,USD,thousands"):
            with self.subTest(row=row), self.assertRaises(AnalyticsInputError):
                run(["Mobily,2025,revenue,5,SAR,thousands", row])

    def test_invalid_year_range_unknown_metric_and_missing_data(self):
        rows = ["Mobily,2025,revenue,5,SAR,thousands"]
        for args in ({"start_year": 2026, "end_year": 2025},
                     {"metric": "made_up"},
                     {"currency": "ETH"},
                     {"company": "Nonexistent"}):
            with self.subTest(args=args), self.assertRaises(AnalyticsInputError):
                run(rows, **args)

    def test_zero_year_not_conflated_with_missing_year(self):
        with self.assertRaises(AnalyticsInputError):
            run(["Mobily,,revenue,5,SAR,thousands"])

    def test_arabic_company_filter_exact_identity(self):
        result = run(["موبايلي,2025,revenue,19.7,SAR,billions"],
                     company="موبايلي", unit="billions")
        self.assertEqual(result["annual"][0]["amount"], "19.7")

    def test_xlsx_workbook_year_and_decimal_metrics(self):
        from openpyxl import Workbook
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Company", "Year", "Metric", "Value", "Currency", "Unit"])
        sheet.append(["Mobily", 2024, "revenue", 18.2, "SAR", "billions"])
        sheet.append(["Mobily", 2025, "revenue", 19.6, "SAR", "billions"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        result = analyze_financial_series(
            buffer.getvalue(), file_type="xlsx", company="Mobily",
            metric="revenue", currency="SAR", unit="billions",
            start_year=2024, end_year=2025,
        )
        self.assertEqual(result["annual"][0]["amount"], "18.2")
        self.assertEqual(result["annual"][1]["amount"], "19.6")


if __name__ == "__main__":
    unittest.main()
