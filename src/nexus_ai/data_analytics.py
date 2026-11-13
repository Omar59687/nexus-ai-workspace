"""Local-first bounded CSV/XLSX financial analytics.

Phase 5 backend candidate, NOT a network route. The caller supplies file
bytes from an already authorized source; there is no filesystem traversal,
cloud call, model dependency, spreadsheet macro execution or DB write.

All financial arithmetic uses Decimal; Pandas is only used to group validated
tabular rows. Missing/invalid values fail closed instead of silently coercing
values or treating absent data as zero.
"""
from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal


class AnalyticsInputError(ValueError):
    """Malformed, unsupported or over-limit tabular data."""


@dataclass(frozen=True)
class AnalyticsLimits:
    max_file_bytes: int = 3_000_000
    max_expanded_xlsx_bytes: int = 30_000_000
    max_rows: int = 20_000
    max_columns: int = 64
    max_groups: int = 500

    def __post_init__(self) -> None:
        for value in vars(self).values():
            if type(value) is not int or value <= 0:
                raise ValueError("limits must be positive integers")


def _column_name(value: object) -> str:
    if not isinstance(value, str):
        raise AnalyticsInputError("column names must be text")
    result = value.strip()
    if not result or len(result) > 120 or any(ord(c) < 32 for c in result):
        raise AnalyticsInputError("invalid column name")
    return result


def _read_csv(blob: bytes, limits: AnalyticsLimits) -> list[list[object]]:
    try:
        text = blob.decode("utf-8-sig", errors="strict")
    except UnicodeError as exc:
        raise AnalyticsInputError("CSV must be UTF-8") from exc
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        rows = []
        for row in reader:
            if len(row) > limits.max_columns:
                raise AnalyticsInputError("too many columns")
            rows.append(row)
            if len(rows) > limits.max_rows + 1:
                raise AnalyticsInputError("too many rows")
        return rows
    except csv.Error as exc:
        raise AnalyticsInputError("malformed CSV") from exc


def _read_xlsx(blob: bytes, limits: AnalyticsLimits, sheet_name: str | None) -> list[list[object]]:
    # Zip central directory preflight bounds decompression and rejects hidden
    # extra entries. This is a local trusted-user format parser, not a sandbox.
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            entries = zf.infolist()
            if len(entries) > 2000 or sum(entry.file_size for entry in entries) > limits.max_expanded_xlsx_bytes:
                raise AnalyticsInputError("XLSX expanded size exceeds limit")
            if any(entry.flag_bits & 0x1 for entry in entries):
                raise AnalyticsInputError("encrypted XLSX unsupported")
            if any(entry.filename.lower().endswith((".bin", ".vba")) for entry in entries):
                raise AnalyticsInputError("macro/binary workbook content unsupported")
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise AnalyticsInputError("invalid XLSX") from exc
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise AnalyticsInputError("XLSX requires the analytics extra") from exc
    try:
        workbook = load_workbook(io.BytesIO(blob), read_only=True, data_only=False, keep_links=False)
        try:
            if not workbook.sheetnames:
                raise AnalyticsInputError("workbook contains no sheets")
            if sheet_name is not None and sheet_name not in workbook.sheetnames:
                raise AnalyticsInputError("unknown worksheet")
            ws = workbook[sheet_name or workbook.sheetnames[0]]
            if ws.max_column and ws.max_column > limits.max_columns:
                raise AnalyticsInputError("too many columns")
            if ws.max_row and ws.max_row > limits.max_rows + 1:
                raise AnalyticsInputError("too many rows")
            rows = []
            for row in ws.iter_rows(values_only=False):
                if len(row) > limits.max_columns:
                    raise AnalyticsInputError("too many columns")
                if any(cell.data_type == "f" for cell in row):
                    raise AnalyticsInputError("formula cells are not accepted")
                values = [cell.value for cell in row]
                rows.append(values)
                if len(rows) > limits.max_rows + 1:
                    raise AnalyticsInputError("too many rows")
            return rows
        finally:
            workbook.close()
    except AnalyticsInputError:
        raise
    except Exception as exc:
        raise AnalyticsInputError("invalid or unsupported XLSX structure") from exc


_NUMERIC = re.compile(r"^-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)$")


def _amount(value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise AnalyticsInputError("missing or invalid numeric amount")
    # XLSX decimal cells are decoded by openpyxl into Python floats. Convert
    # their shortest round-trip decimal spelling; never sum binary floats.
    # The original spreadsheet's displayed number format is not an accounting
    # precision guarantee, so this conversion policy is disclosed in results.
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AnalyticsInputError("non-finite numeric amount")
        text = str(value)
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise AnalyticsInputError("numeric amount must be decimal text or an integer")
    if not _NUMERIC.fullmatch(text) or len(text) > 40:
        raise AnalyticsInputError("numeric amount must be a plain decimal, with no currency symbols or grouping")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise AnalyticsInputError("invalid decimal amount") from exc
    if not amount.is_finite() or amount.adjusted() > 24 or amount.adjusted() < -18:
        raise AnalyticsInputError("amount outside supported precision/range")
    return amount


def analyze_table(
    blob: bytes,
    *,
    file_type: Literal["csv", "xlsx"],
    group_column: str,
    amount_column: str,
    sheet_name: str | None = None,
    limits: AnalyticsLimits = AnalyticsLimits(),
) -> dict[str, object]:
    """Aggregate one numeric measure by an explicit dimension.

    `total` and `chart_data[].value` are JSON decimal *strings*. Consumers
    must not assume chart values are IEEE floating-point or percentages.
    """
    if not isinstance(blob, bytes) or not blob or len(blob) > limits.max_file_bytes:
        raise AnalyticsInputError("missing or oversized input file")
    if file_type not in ("csv", "xlsx"):
        raise AnalyticsInputError("file_type must be csv or xlsx")
    if sheet_name is not None and (not isinstance(sheet_name, str) or not sheet_name or len(sheet_name) > 120):
        raise AnalyticsInputError("invalid sheet name")
    if file_type == "csv" and sheet_name is not None:
        raise AnalyticsInputError("sheet_name only applies to XLSX")
    group_column, amount_column = _column_name(group_column), _column_name(amount_column)
    if group_column == amount_column:
        raise AnalyticsInputError("group and amount columns must differ")
    rows = _read_csv(blob, limits) if file_type == "csv" else _read_xlsx(blob, limits, sheet_name)
    if len(rows) < 2:
        raise AnalyticsInputError("header plus at least one data row required")
    headers = [_column_name(value) for value in rows[0]]
    if len(headers) != len(set(headers)):
        raise AnalyticsInputError("duplicate column headings")
    if group_column not in headers or amount_column not in headers:
        raise AnalyticsInputError("requested columns missing")
    group_idx, amount_idx = headers.index(group_column), headers.index(amount_column)
    clean = []
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(headers):
            raise AnalyticsInputError("row width differs from header")
        label = row[group_idx]
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 160:
            raise AnalyticsInputError("blank or invalid grouping label")
        value = _amount(row[amount_idx])
        clean.append((label.strip(), value))
    if len(clean) > limits.max_rows:
        raise AnalyticsInputError("too many rows")
    if len(set(label for label, _ in clean)) > limits.max_groups:
        raise AnalyticsInputError("too many groups")
    try:
        import pandas as pd
    except ImportError as exc:
        raise AnalyticsInputError("Pandas requires the analytics extra") from exc
    dataframe = pd.DataFrame(clean, columns=["group", "amount"])
    aggregates = dataframe.groupby("group", sort=True, dropna=False)["amount"].sum()
    # Use direct Decimal arithmetic to validate the Pandas aggregation result.
    expected_total = sum((value for _, value in clean), Decimal(0))
    found_total = sum((value for value in aggregates.tolist()), Decimal(0))
    if expected_total != found_total:
        raise AnalyticsInputError("aggregation integrity mismatch")
    chart = [{"label": str(label), "value": format(value, "f")}
             for label, value in aggregates.items()]
    return {
        "status": "PASS",
        "file_type": file_type,
        "sheet_name": sheet_name if file_type == "xlsx" else None,
        "group_column": group_column,
        "amount_column": amount_column,
        "row_count": len(clean),
        "group_count": len(chart),
        "total": format(expected_total, "f"),
        "chart_type": "bar",
        "chart_data": chart,
        "value_encoding": "decimal_string",
        "numeric_policy": (
            "CSV decimal text preserved; XLSX numeric cells use shortest "
            "round-trip decimal representation of parsed stored values; "
            "spreadsheet number formats are not applied"
        ),
        "limits": {
            "max_file_bytes": limits.max_file_bytes,
            "max_rows": limits.max_rows,
            "max_columns": limits.max_columns,
        },
        "scope": {
            "llm_calls": 0,
            "database_writes": 0,
            "input_persisted": False,
        },
    }
