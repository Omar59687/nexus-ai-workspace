"""Reproducible performance harness contract, not a timing gate."""
import pytest
from scripts.measure_p5_analytics import _data, measure


def test_benchmark_reconciles_exact_csv_and_xlsx_totals():
    result = measure(rows=36)
    assert result["purpose"] == "REPORT_ONLY_NOT_AN_ACCEPTANCE_THRESHOLD"
    for kind in ("csv", "xlsx"):
        sample = result["measurements"][kind]
        assert sample["total_decimal"] == "289"
        assert sample["row_count"] == 36
        assert sample["input_bytes"] > 0
        assert sample["traced_peak_bytes"] > 0
        assert sample["elapsed_ms"] >= 0


@pytest.mark.parametrize("rows", [0, -1, 20001, True, 1.5])
def test_benchmark_rejects_out_of_bounds_row_counts(rows):
    with pytest.raises(ValueError):
        _data(rows)
