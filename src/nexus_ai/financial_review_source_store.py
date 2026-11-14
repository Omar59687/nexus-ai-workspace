"""Explicitly pinned local PDF source lookup for trusted reviewer hosts.

Reuses the Phase 4 approved-root file gate. Client requests only supply
document/version identifiers; the lookup never interprets those identifiers
as paths. Every read requires an independent trusted document ACL decision.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
from typing import Callable, Mapping

from nexus_ai.documents.filesystem import read_approved_file, UnsafeDocumentPath
from nexus_ai.financial_review_adapter import ReviewPrincipal
from nexus_ai.financial_review_workflow import _require_text
from nexus_ai.financial_review_pdf import MAX_REVIEW_PDF_BYTES

_DIGEST = re.compile(r"\A[0-9a-f]{64}\Z")
MAX_PINNED_PDFS = 150


class PinnedLocalPdfStore:
    """Local source provider, constructed from a trusted owner inventory.

    Entries map (workspace, document_id, version_id) to
    (approved relative PDF path, immutable original file SHA-256).
    No directory scanning or client-controlled path construction.
    """

    def __init__(
        self, *,
        approved_root: str | Path,
        pinned: Mapping[tuple[str, str, str], tuple[str, str]],
        authorize_document: Callable[[ReviewPrincipal, str, str, str], bool],
    ):
        if not callable(authorize_document):
            raise ValueError("trusted per-document authorization required")
        if not isinstance(pinned, Mapping) or not 1 <= len(pinned) <= MAX_PINNED_PDFS:
            raise ValueError("invalid pinned document inventory")
        approved = {}
        for key, record in pinned.items():
            if (not isinstance(key, tuple) or len(key) != 3
                    or not isinstance(record, tuple) or len(record) != 2):
                raise ValueError("invalid pinned document record")
            workspace, document_id, version_id = key
            for value in key:
                _require_text(value, "pinned document identity", 128)
            relative, expected_digest = record
            if (not isinstance(relative, str)
                    or not relative.lower().endswith(".pdf")
                    or len(relative) > 500
                    or not isinstance(expected_digest, str)
                    or not _DIGEST.fullmatch(expected_digest)):
                raise ValueError("invalid pinned PDF identity")
            approved[(workspace, document_id, version_id)] = (
                relative, expected_digest,
            )
        self._root = Path(approved_root)
        self._pinned = approved
        self._authorize = authorize_document

    def __call__(
        self, principal: ReviewPrincipal, workspace_id: str,
        document_id: str, version_id: str,
    ) -> bytes:
        if not isinstance(principal, ReviewPrincipal):
            raise PermissionError("document access denied")
        try:
            workspace_id = _require_text(workspace_id, "workspace", 128)
            document_id = _require_text(document_id, "document", 128)
            version_id = _require_text(version_id, "version", 128)
            if self._authorize(
                principal, workspace_id, document_id, "view_pdf"
            ) is not True:
                raise PermissionError("document access denied")
            pinned = self._pinned.get((workspace_id, document_id, version_id))
            if pinned is None:
                raise PermissionError("document access denied")
            relative, expected_digest = pinned
            content, _ = read_approved_file(
                self._root, relative, max_bytes=MAX_REVIEW_PDF_BYTES,
            )
            if sha256(content).hexdigest() != expected_digest:
                raise ValueError("pinned PDF digest changed")
            return content
        except PermissionError:
            raise
        except (OSError, ValueError, UnsafeDocumentPath) as exc:
            # Never disclose absolute file paths, raw source bytes or
            # the internal reason for an unavailable PDF.
            raise ValueError("pinned original PDF unavailable") from exc
