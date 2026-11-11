"""Opt-in smoke check for structured generation against a live Ollama server.

This script is deliberately inert unless NEXUS_LIVE_OLLAMA=1 is set. Its
evidence report never contains the request prompt or exception text. The
HTTPX timeout configured through Ollama is an inactivity timeout, not a strict
wall-clock deadline for the whole request.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_TIMEOUT_SECONDS = 300.0
FIXED_PROMPT = (
    "Explain REST in one short sentence and give one safe example of an "
    "HTTP method."
)


def resolve_output_path(value: str | Path, project_root: Path) -> Path:
    """Resolve a report path and reject anything outside ignored local_data."""
    root = project_root.resolve()
    local_data = (root / "local_data").resolve()
    supplied = Path(value).expanduser()
    candidate = supplied if supplied.is_absolute() else root / supplied
    candidate = candidate.resolve()
    try:
        relative = candidate.relative_to(local_data)
    except ValueError as exc:
        raise ValueError("output path must be inside the repository local_data directory") from exc
    if not relative.parts or candidate == local_data:
        raise ValueError("output path must name a file inside local_data")
    if candidate.exists() and candidate.is_dir():
        raise ValueError("output path must name a file")
    return candidate


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Ollama model name")
    parser.add_argument(
        "--output", required=True, help="JSON evidence path under local_data/"
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Ollama HTTP timeout (default {DEFAULT_TIMEOUT_SECONDS:g}; maximum {MAX_TIMEOUT_SECONDS:g})",
    )
    args = parser.parse_args(argv)
    if not args.model.strip():
        parser.error("--model must not be empty")
    if not (0 < args.timeout_seconds <= MAX_TIMEOUT_SECONDS):
        parser.error(f"--timeout-seconds must be greater than 0 and at most {MAX_TIMEOUT_SECONDS:g}")
    return args


def _write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace atomically so an interrupted run cannot leave a partial report.
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = stream.name
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if os.environ.get("NEXUS_LIVE_OLLAMA") != "1":
        print(
            "Live Ollama smoke is disabled; set NEXUS_LIVE_OLLAMA=1 to opt in.",
            file=sys.stderr,
        )
        return 2

    project_root = Path(__file__).resolve().parents[1]
    try:
        output_path = resolve_output_path(args.output, project_root)
    except ValueError as exc:
        print(f"Invalid output path: {exc}", file=sys.stderr)
        return 2

    # Set before importing the application, which reads this environment value.
    os.environ["OLLAMA_TIMEOUT_SECONDS"] = str(args.timeout_seconds)
    started = time.monotonic()
    timestamp = datetime.now(timezone.utc).isoformat()
    observed_status: int | None = None
    try:
        # This import is intentionally below both explicit opt-in and path checks.
        from fastapi.testclient import TestClient
        from nexus_ai.main import app

        with TestClient(app) as client:
            response = client.post(
                "/structured/generate",
                json={
                    "schema_name": "rest_explanation",
                    "prompt": FIXED_PROMPT,
                    "model": args.model,
                },
            )
        observed_status = response.status_code
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        if response.is_success:
            body = response.json()
            report: dict[str, object] = {
                "timestamp_utc": timestamp,
                "model": args.model,
                "timeout_seconds": args.timeout_seconds,
                "status_code": response.status_code,
                "elapsed_ms": elapsed_ms,
                "metrics": body.get("metrics"),
                "response_data": body.get("data"),
            }
            outcome = 0
        else:
            report = {
                "timestamp_utc": timestamp,
                "model": args.model,
                "timeout_seconds": args.timeout_seconds,
                "status_code": response.status_code,
                "elapsed_ms": elapsed_ms,
                "failure_category": "http_error",
            }
            outcome = 1
    except Exception:
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        # Use a fixed category; do not serialize exception class or message.
        report = {
            "timestamp_utc": timestamp,
            "model": args.model,
            "timeout_seconds": args.timeout_seconds,
            "status_code": observed_status,
            "elapsed_ms": elapsed_ms,
            "failure_category": "request_or_application_error",
        }
        outcome = 1

    try:
        _write_report(output_path, report)
    except OSError:
        print("Could not write smoke evidence report.", file=sys.stderr)
        return 1

    if outcome:
        print(
            f"Smoke failed ({report.get('failure_category')}, status={report.get('status_code')}); "
            f"evidence: {output_path}",
            file=sys.stderr,
        )
    else:
        print(
            f"Smoke passed (status={report['status_code']}, elapsed_ms={report['elapsed_ms']}); "
            f"evidence: {output_path}"
        )
    return outcome


if __name__ == "__main__":
    raise SystemExit(main())
