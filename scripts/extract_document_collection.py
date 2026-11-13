"""Owner opt-in batch extraction, no GPU/model/DB."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nexus_ai.documents.collection_preflight import (
    CollectionManifestError, load_collection_manifest
)
from nexus_ai.documents.collection_extraction import extract_collection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-extraction", action="store_true", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.manifest.is_symlink() or args.report.is_symlink():
            raise CollectionManifestError("symlink manifest/report prohibited")
        root = args.root.expanduser().resolve(strict=True)
        manifest = args.manifest.expanduser().resolve(strict=True)
        report = args.report.expanduser().resolve()
        if report == root or root in report.parents or report == manifest:
            raise CollectionManifestError("report must be outside document root")
        entries = load_collection_manifest(manifest)
        output = extract_collection(root, entries)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError):
        output = {
            "status": "BLOCKED",
            "reason": "invalid_root_manifest_or_report",
        }
    print(json.dumps({
        "status": output["status"],
        "extracted_count": output.get("extracted_count", 0),
        "duplicate_count": output.get("duplicate_count", 0),
        "blocked_count": output.get("blocked_count", 0),
    }))
    return 0 if output["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
