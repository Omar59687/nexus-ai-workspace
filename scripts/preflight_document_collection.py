"""Opt-in, model-free document inventory; no implicit filesystem crawling."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nexus_ai.documents.collection_preflight import (
    CollectionManifestError, load_collection_manifest, preflight_collection,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-preflight", action="store_true", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        # Report stays outside approved root to prevent accidental ingestion.
        root = args.root.expanduser().resolve(strict=True)
        if args.report.expanduser().is_symlink() or args.manifest.expanduser().is_symlink():
            raise CollectionManifestError("report and manifest cannot be symlinks")
        report = args.report.expanduser().resolve()
        manifest = args.manifest.expanduser().resolve(strict=True)
        if report == root or root in report.parents or report == manifest:
            raise CollectionManifestError("report must be outside document root and distinct from manifest")
        entries = load_collection_manifest(manifest)
        output = preflight_collection(root, entries)
    except (OSError, ValueError):
        output = {
            "kind": "model_free_collection_preflight_v1",
            "status": "BLOCKED",
            "reason": "invalid_manifest_root_or_report",
            "scope": {"model_calls": "NONE", "database_writes": "NONE"},
        }
    if output["status"] != "BLOCKED":
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": output["status"],
        "ready_count": output.get("ready_count", 0),
        "blocked_count": output.get("blocked_count", 0),
        "duplicate_content_count": output.get("duplicate_content_count", 0),
        "report": str(args.report) if output["status"] != "BLOCKED" else None,
    }, ensure_ascii=True))
    return 0 if output["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
