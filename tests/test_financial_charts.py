"""Deterministic chart rendering and injection resistance."""
from __future__ import annotations

import re
import unittest
import xml.etree.ElementTree as ET

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.financial_analytics import analyze_financial_series
from nexus_ai.financial_charts import render_financial_line_svg


class FinancialChartsTests(unittest.TestCase):
    def make_report(self, company="Mobily"):
        csv = ("Company,Year,Metric,Value,Currency,Unit\n"
               f"{company},2024,revenue,18206447,SAR,thousands\n"
               f"{company},2025,revenue,19641705,SAR,thousands\n")
        return analyze_financial_series(
            csv.encode(), file_type="csv", company=company, metric="revenue",
            currency="SAR", unit="thousands", start_year=2024, end_year=2025,
        )

    def test_deterministic_xml_chart_and_exact_text(self):
        report = self.make_report()
        first = render_financial_line_svg(report)
        second = render_financial_line_svg(report)
        self.assertEqual(first, second)
        root = ET.fromstring(first)
        self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
        self.assertIn("19641705", first)
        self.assertIn("18206447", first)
        self.assertIn("SAR thousands", first)
        self.assertIn("M90.00", first)

    def test_labels_escaped_and_no_executable_markup(self):
        company = "A&<script>alert(1)</script>"
        report = self.make_report(company)
        svg = render_financial_line_svg(report)
        ET.fromstring(svg)
        self.assertNotIn("<script>", svg)
        self.assertNotIn("</script>", svg)
        self.assertIn("&lt;script&gt;", svg)

    def test_reject_untrusted_series(self):
        report = self.make_report()
        report["chart"]["data"][0]["value"] = "NaN"
        with self.assertRaises(AnalyticsInputError):
            render_financial_line_svg(report)

    def test_reject_out_of_order_year_and_invalid_dimensions(self):
        report = self.make_report()
        report["chart"]["data"][1]["year"] = 2024
        with self.assertRaises(AnalyticsInputError):
            render_financial_line_svg(report)
        with self.assertRaises(AnalyticsInputError):
            render_financial_line_svg(self.make_report(), width=200)

    def test_single_year_and_zero_value(self):
        report = self.make_report()
        report["chart"]["data"] = [{"year": 2025, "value": "0.0000"}]
        svg = render_financial_line_svg(report)
        ET.fromstring(svg)
        self.assertIn("0.0000", svg)


if __name__ == "__main__":
    unittest.main()
