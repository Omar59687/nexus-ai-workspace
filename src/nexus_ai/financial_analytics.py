"""Phase 5: bounded, deterministic multi-year financial analytics.

Finance fields are explicit, no LLM inference of financial semantics or units.
Only the requested metric, company, financial years and currency/unit are
selected. A same-name metric with different currency/unit cannot be combined.
Results are Decimal strings; divide-by-zero growth abstains.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, localcontext
from typing import Literal

from nexus_ai.data_analytics import (
    AnalyticsInputError,
    AnalyticsLimits,
    _amount,
    _column_name,
    _read_csv,
    _read_xlsx,
)

_CURRENCIES = frozenset({"SAR", "USD", "EUR", "GBP", "JOD", "AED", "QAR"})
_UNITS = frozenset({"ones", "thousands", "millions", "billions"})
_METRICS = frozenset({"revenue", "net_income", "operating_income", "assets", "liabilities", "equity", "cash_flow"})
_YEAR_MIN, _YEAR_MAX = 1900, 2100


def _year(value: object) -> int:
    if isinstance(value, bool):
        raise AnalyticsInputError("invalid financial year")
    if isinstance(value, float):
        raise AnalyticsInputError("financial year must be integer text or integer")
    try:
        year = int(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise AnalyticsInputError("invalid financial year") from exc
    if str(year) != str(value).strip() or not _YEAR_MIN <= year <= _YEAR_MAX:
        raise AnalyticsInputError("financial year must be 1900 to 2100")
    return year


def _label(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 160:
        raise AnalyticsInputError(f"invalid {field}")
    return value.strip()


def _decimal_string(number: Decimal) -> str:
    return format(number, "f")


def analyze_financial_series(
    blob: bytes,
    *,
    file_type: Literal["csv", "xlsx"],
    company: str,
    metric: str,
    currency: str,
    unit: str,
    start_year: int,
    end_year: int,
    company_column: str = "Company",
    year_column: str = "Year",
    metric_column: str = "Metric",
    value_column: str = "Value",
    currency_column: str = "Currency",
    unit_column: str = "Unit",
    sheet_name: str | None = None,
    limits: AnalyticsLimits = AnalyticsLimits(),
) -> dict[str, object]:
    """Return annual totals and year-over-year change for a selected dimension.

    Every parsed row is validated, including rows outside the selected filters:
    the caller must not be able to hide malformed or ambiguous data with filters.
    The selected currency/unit is mandatory on every included row; rows of
    another currency/unit for the same company/metric/year *block* rather than
    being silently discarded or converted.
    """
    if not isinstance(blob, bytes) or not blob or len(blob) > limits.max_file_bytes:
        raise AnalyticsInputError("missing or oversized input")
    if file_type not in ("csv", "xlsx"):
        raise AnalyticsInputError("unsupported file type")
    if file_type == "csv" and sheet_name is not None:
        raise AnalyticsInputError("CSV does not support worksheets")
    company = _label(company, field="company")
    metric = _label(metric, field="metric")
    if metric not in _METRICS:
        raise AnalyticsInputError("unknown financial metric; explicit metric required")
    if currency not in _CURRENCIES or unit not in _UNITS:
        raise AnalyticsInputError("explicit supported currency and unit required")
    if type(start_year) is not int or type(end_year) is not int or not (1900 <= start_year <= end_year <= 2100):
        raise AnalyticsInputError("invalid year range")
    columns = tuple(_column_name(x) for x in (
        company_column, year_column, metric_column, value_column,
        currency_column, unit_column
    ))
    if len(set(columns)) != len(columns):
        raise AnalyticsInputError("financial columns must be distinct")
    rows = _read_csv(blob, limits) if file_type == "csv" else _read_xlsx(blob, limits, sheet_name)
    if len(rows) < 2:
        raise AnalyticsInputError("header and at least one data row required")
    headers = tuple(_column_name(x) for x in rows[0])
    if len(headers) != len(set(headers)) or not set(columns).issubset(headers):
        raise AnalyticsInputError("duplicate or missing financial headings")
    indices = tuple(headers.index(c) for c in columns)
    values: dict[int, list[Decimal]] = defaultdict(list)
    selected_rows = 0
    for row in rows[1:]:
        if len(row) != len(headers):
            raise AnalyticsInputError("inconsistent financial row width")
        row_company, row_year, row_metric, row_value, row_currency, row_unit = (
            row[i] for i in indices
        )
        row_company = _label(row_company, field="company")
        row_year = _year(row_year)
        row_metric = _label(row_metric, field="metric")
        if row_metric not in _METRICS:
            raise AnalyticsInputError("unrecognized financial metric")
        row_value = _amount(row_value)
        row_currency = _label(row_currency, field="currency")
        row_unit = _label(row_unit, field="unit")
        if row_currency not in _CURRENCIES or row_unit not in _UNITS:
            raise AnalyticsInputError("unrecognized financial currency or unit")
        if row_company != company or row_metric != metric or not (start_year <= row_year <= end_year):
            continue
        if row_currency != currency or row_unit != unit:
            raise AnalyticsInputError("mixed currency or unit in selected financial series")
        values[row_year].append(row_value)
        selected_rows += 1
    if not selected_rows:
        raise AnalyticsInputError("no matching financial data")
    if len(values) > limits.max_groups:
        raise AnalyticsInputError("too many annual groups")

    # Multi-row aggregation is explicit and deterministic. A caller must ensure
    # rows are additive; this method cannot detect repeated financial statements.
    annual: list[dict[str, object]] = []
    prev_total: Decimal | None = None
    prev_year: int | None = None
    for year in sorted(values):
        with localcontext() as context:
            context.prec = 70
            total = sum(values[year], Decimal(0))
            growth = None
            reason = None
            if prev_year is not None and prev_year != year - 1:
                reason = "nonconsecutive_years"
            elif prev_total is not None and prev_total == 0:
                reason = "zero_baseline"
            elif prev_total is not None:
                growth = ((total - prev_total) / abs(prev_total)) * Decimal(100)
            annual.append({
                "year": year,
                "amount": _decimal_string(total),
                "row_count": len(values[year]),
                "yoy_percent": _decimal_string(growth.quantize(Decimal("0.0001"))) if growth is not None else None,
                "yoy_unavailable_reason": reason,
            })
            prev_year, prev_total = year, total
    # Chart values are decimal strings, never binary floats. Do not plot
    # dissimilar units together or auto-normalize accounting figures.
    return {
        "status": "PASS",
        "metric": metric,
        "company": company,
        "currency": currency,
        "unit": unit,
        "year_filter": {"start": start_year, "end": end_year},
        "rows_selected": selected_rows,
        "annual": annual,
        "chart": {
            "type": "line",
            "x_axis": "financial_year",
            "y_axis": f"{currency} {unit}",
            "data": [{"year": row["year"], "value": row["amount"]} for row in annual],
            "encoding": "decimal_string",
        },
        "limitations": [
            "Input rows must be additive and nonduplicated; the system cannot infer semantic duplicates.",
            "Numbers and units are supplied by the caller, not extracted from PDF tables.",
            "A missing year is not interpolated; YoY is unavailable across gaps and zero baselines.",
        ],
        "scope": {"model_calls": 0, "database_writes": 0, "source_persisted": False},
    }
