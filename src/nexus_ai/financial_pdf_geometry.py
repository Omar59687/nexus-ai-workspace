"""Opt-in bounded PDF text-position diagnostic using the existing worker limits.

Never use this as an authority for accounting rows. Coordinates from pypdf
are approximations and Arabic text fragments may be reordered. The parent
verifies a caller-provided SHA256 and invokes the same POSIX/Windows bounded
process architecture as ordinary PDF extraction. The worker emits no PDF
page content beyond selected, bounded position fragments.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from io import BytesIO
from pathlib import Path

from nexus_ai.data_analytics import AnalyticsInputError
from nexus_ai.documents.pdf_worker import (
    PdfWorkerExtractionError, _apply_worker_limits, _require_platform_limits,
    _run_bounded_process,
)
from nexus_ai.financial_positioned_tables import PositionedText


def extract_pdf_positions(
    pdf: bytes, *,
    expected_sha256: str,
    pages: tuple[int, ...],
    timeout_seconds: float = 60,
    max_boxes_per_page: int = 3000,
    memory_limit_bytes: int = 1024 * 1024 * 1024,
    cpu_limit_seconds: int = 30,
) -> dict[int, tuple[PositionedText, ...]]:
    if not isinstance(pdf, bytes) or not pdf or len(pdf) > 25 * 1024 * 1024:
        raise AnalyticsInputError("PDF exceeds input byte budget")
    if hashlib.sha256(pdf).hexdigest() != expected_sha256:
        raise AnalyticsInputError("source PDF digest does not match expected index")
    if (not isinstance(pages, tuple) or not 1 <= len(pages) <= 5
            or len(set(pages)) != len(pages)
            or any(type(page) is not int or not 1 <= page <= 500 for page in pages)):
        raise AnalyticsInputError("select between one and five distinct PDF pages")
    if type(max_boxes_per_page) is not int or not 1 <= max_boxes_per_page <= 3000:
        raise AnalyticsInputError("invalid positioned-text budget")
    if (not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 120):
        raise AnalyticsInputError("invalid worker time budget")
    if (type(memory_limit_bytes) is not int or not 256 * 1024 * 1024 <= memory_limit_bytes <= 2 * 1024 * 1024 * 1024
            or type(cpu_limit_seconds) is not int or not 1 <= cpu_limit_seconds <= 120):
        raise AnalyticsInputError("invalid PDF worker resource budget")
    _require_platform_limits()
    args = [
        sys.executable, "-m", "nexus_ai.financial_pdf_geometry",
        "--worker", "--pages", ",".join(map(str, pages)),
        "--max-boxes", str(max_boxes_per_page),
        "--memory", str(memory_limit_bytes),
        "--cpu", str(cpu_limit_seconds),
    ]
    encoded = _run_bounded_process(
        args, pdf, timeout_seconds=timeout_seconds,
        max_output_bytes=5 * max_boxes_per_page * 800 + 8192,
        memory_limit_bytes=memory_limit_bytes,
        cpu_limit_seconds=cpu_limit_seconds,
        python_path=str(Path(__file__).resolve().parents[1]),
    )
    try:
        report = json.loads(encoded.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise AnalyticsInputError("invalid position worker output") from exc
    if not isinstance(report, dict) or report.get("status") != "OK":
        raise AnalyticsInputError("PDF position worker abstained or failed")
    raw_pages = report.get("pages")
    if not isinstance(raw_pages, dict) or set(raw_pages) != set(map(str, pages)):
        raise AnalyticsInputError("position worker returned unexpected pages")
    output = {}
    for page in pages:
        rows = raw_pages[str(page)]
        if not isinstance(rows, list) or len(rows) > max_boxes_per_page:
            raise AnalyticsInputError("invalid position box inventory")
        boxes = []
        for row in rows:
            if (not isinstance(row, list) or len(row) != 3
                    or any(isinstance(n, bool) or not isinstance(n, (int, float))
                           or not math.isfinite(n) or not 0 <= n <= 5000 for n in row[:2])
                    or not isinstance(row[2], str) or not 0 < len(row[2]) <= 400):
                raise AnalyticsInputError("invalid position box from worker")
            boxes.append(PositionedText(page_number=page, x=row[0], y=row[1], text=row[2]))
        output[page] = tuple(boxes)
    return output


def _worker(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--pages", required=True)
    parser.add_argument("--max-boxes", type=int, required=True)
    parser.add_argument("--memory", type=int, required=True)
    parser.add_argument("--cpu", type=int, required=True)
    cfg = parser.parse_args(argv)
    try:
        _apply_worker_limits(cfg.memory, cfg.cpu)
        import pypdf
        requested = tuple(int(n) for n in cfg.pages.split(","))
        content = sys.stdin.buffer.read(25 * 1024 * 1024 + 1)
        if len(content) > 25 * 1024 * 1024:
            raise ValueError("input too large")
        reader = pypdf.PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted or len(reader.pages) > 500:
            raise ValueError("unsupported PDF")
        if any(n < 1 or n > len(reader.pages) for n in requested):
            raise ValueError("page outside PDF")
        output = {}
        for number in requested:
            boxes = []
            def visitor(text, cm, tm, font_dict, font_size):
                if not isinstance(text, str):
                    return
                # Keep small text fragments only. Do not split or
                # concatenate fragments, since that would falsify offsets.
                t = text.strip()
                if not t or len(t) > 400:
                    return
                try:
                    x, y = float(tm[4]), float(tm[5])
                except (ValueError, TypeError, IndexError):
                    return
                if not math.isfinite(x) or not math.isfinite(y) or not (0 <= x <= 5000 and 0 <= y <= 5000):
                    return
                boxes.append([x, y, t])
                if len(boxes) > cfg.max_boxes:
                    raise ValueError("PDF position box budget exceeded")
            reader.pages[number - 1].extract_text(visitor_text=visitor)
            output[str(number)] = boxes
        sys.stdout.write(json.dumps({"status": "OK", "pages": output}, ensure_ascii=False))
        return 0
    except BaseException:
        sys.stdout.write('{"status":"ABSTAIN"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(_worker(sys.argv[1:]))
