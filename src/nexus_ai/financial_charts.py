"""Deterministic SVG chart rendering for validated financial analytics output.

Accepts only the output of the bounded financial-series contract (or an
equivalent caller-created object satisfying all checks), escapes dynamic
labels and never embeds scripts, hyperlinks, external images or HTML.
Numeric plotting coordinates are approximations; financial values remain
exact decimal strings in source data.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from html import escape

from nexus_ai.data_analytics import AnalyticsInputError


def render_financial_line_svg(analysis: dict, *, width: int = 760, height: int = 400) -> str:
    if type(width) is not int or type(height) is not int or not (360 <= width <= 1600) or not (260 <= height <= 1000):
        raise AnalyticsInputError("invalid chart dimensions")
    if not isinstance(analysis, dict) or analysis.get("status") != "PASS":
        raise AnalyticsInputError("only validated financial analysis outputs are accepted")
    chart = analysis.get("chart")
    if not isinstance(chart, dict) or chart.get("type") != "line" or chart.get("encoding") != "decimal_string":
        raise AnalyticsInputError("unsupported financial chart")
    data = chart.get("data")
    if not isinstance(data, list) or not 1 <= len(data) <= 201:
        raise AnalyticsInputError("chart data count outside limits")
    title = f"{analysis.get('company', '')} — {analysis.get('metric', '')}"
    units = chart.get("y_axis")
    if not all(isinstance(s, str) and 0 < len(s) <= 180 for s in (title, units)):
        raise AnalyticsInputError("invalid chart labels")
    points = []
    for row in data:
        if not isinstance(row, dict) or type(row.get("year")) is not int or not 1900 <= row["year"] <= 2100:
            raise AnalyticsInputError("invalid chart year")
        value = row.get("value")
        if not isinstance(value, str) or not 1 <= len(value) <= 45:
            raise AnalyticsInputError("invalid chart value")
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise AnalyticsInputError("invalid chart decimal") from exc
        if not number.is_finite() or abs(number) > Decimal("1e25"):
            raise AnalyticsInputError("out-of-range chart decimal")
        if points and row["year"] <= points[-1][0]:
            raise AnalyticsInputError("years must be strictly increasing")
        points.append((row["year"], number))
    years = [year for year, _ in points]
    values = [value for _, value in points]
    y_min, y_max = min(values + [Decimal(0)]), max(values + [Decimal(0)])
    if y_min == y_max:
        y_max = y_min + Decimal(1)
    left, right, top, bottom = 90, width - 32, 75, height - 72
    def x_for(year):
        if len(points) == 1:
            return (left + right) / 2
        return left + (year - years[0]) * (right - left) / (years[-1] - years[0])
    def y_for(value):
        # Float conversion is used only for pixel coordinates, not for data,
        # aggregations, currency amounts or growth values.
        proportion = float((value - y_min) / (y_max - y_min))
        return bottom - proportion * (bottom - top)
    coordinates = [(x_for(year), y_for(value)) for year, value in points]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.2f},{y:.2f}"
                    for i, (x, y) in enumerate(coordinates))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title, quote=True)}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{left}" y="33" font-family="Arial,sans-serif" font-size="20" fill="#172b4d">{escape(title)}</text>',
        f'<text x="{left}" y="53" font-family="Arial,sans-serif" font-size="12" fill="#52606d">{escape(units)}</text>',
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#8898aa"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#8898aa"/>',
        f'<path d="{path}" fill="none" stroke="#2364aa" stroke-width="2.5"/>',
    ]
    for (year, value), (x, y) in zip(points, coordinates):
        parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="#2364aa"/>')
        parts.append(f'<text x="{x:.2f}" y="{bottom + 22}" font-size="11" font-family="Arial,sans-serif" text-anchor="middle">{year}</text>')
        # Display full Decimal value as text: no misleading rounding.
        parts.append(f'<text x="{x:.2f}" y="{max(15, y-12):.2f}" font-size="11" font-family="Arial,sans-serif" text-anchor="middle">{escape(format(value, "f"))}</text>')
    parts.append('</svg>')
    return "\n".join(parts) + "\n"
