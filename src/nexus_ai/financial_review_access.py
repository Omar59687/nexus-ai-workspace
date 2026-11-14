"""Opt-in opaque-session authentication and PostgreSQL workspace permissions.

Only SHA-256 token digests are stored. Session creation, permission grants,
revocation, TLS, auditing and key delivery belong to trusted operators;
no issuance or management endpoint exists here. No connection at import time.
"""
from __future__ import annotations

import hashlib
import re
from typing import Callable

from fastapi import Request

from nexus_ai.financial_review_adapter import ReviewPrincipal

# A caller must securely generate an unpredictable 32-byte token and encode
# it as 64 lowercase hexadecimal characters; never derive it from a password.
_TOKEN_PATTERN = re.compile(r"\A[a-f0-9]{64}\Z")
_ACTIONS = frozenset({"submit", "approve", "reject", "status", "analyze", "list"})

FINANCIAL_AUTH_SCHEMA_DDL = (
    """CREATE TABLE nexus_financial_sessions (
        token_sha256 char(64) PRIMARY KEY,
        subject text NOT NULL CHECK (length(subject) BETWEEN 1 AND 128),
        expires_at timestamptz NOT NULL,
        revoked_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        CHECK (token_sha256 ~ '^[0-9a-f]{64}$')
    )""",
    """CREATE TABLE nexus_financial_permissions (
        subject text NOT NULL CHECK (length(subject) BETWEEN 1 AND 128),
        workspace_id text NOT NULL CHECK (length(workspace_id) BETWEEN 1 AND 128),
        action text NOT NULL CHECK (action IN (
            'submit', 'approve', 'reject', 'status', 'analyze', 'list'
        )),
        PRIMARY KEY (subject, workspace_id, action)
    )""",
    "CREATE INDEX nexus_financial_sessions_expiry_idx ON nexus_financial_sessions (expires_at)",
)


class PostgresFinancialAccess:
    """Read-only, fail-closed session/permission lookups on injected DB connections.

    The connection factory must address a trusted, privately managed auth DB.
    Do not expose SQL grants or session provisioning through this API.
    """

    def __init__(self, connection_factory: Callable):
        if not callable(connection_factory):
            raise ValueError("transactional connection factory required")
        self._connect = connection_factory

    def _read_one(self, statement: str, args: tuple):
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(statement, args)
                row = cursor.fetchone()
            connection.rollback()  # release read-only transaction and snapshot
            return row
        finally:
            connection.close()

    def authenticate_request(self, request: Request) -> ReviewPrincipal:
        # Exactly one Authorization header; no cookies, query tokens or
        # unvalidated caller-provided identity headers.
        headers = request.headers.getlist("authorization")
        if len(headers) != 1:
            raise PermissionError("authentication required")
        header = headers[0]
        if not header.startswith("Bearer "):
            raise PermissionError("authentication required")
        token = header[7:]
        if not _TOKEN_PATTERN.fullmatch(token):
            raise PermissionError("authentication required")
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        try:
            row = self._read_one(
                """SELECT subject FROM nexus_financial_sessions
                   WHERE token_sha256 = %s
                     AND revoked_at IS NULL AND expires_at > now()""",
                (digest,),
            )
        except Exception as exc:
            raise PermissionError("authentication unavailable") from exc
        if row is None or not isinstance(row[0], str) or not 1 <= len(row[0].strip()) <= 128:
            raise PermissionError("authentication required")
        return ReviewPrincipal(row[0])

    def authorize(self, principal: ReviewPrincipal, workspace_id: str,
                  action: str) -> bool:
        if (not isinstance(principal, ReviewPrincipal)
                or not isinstance(principal.subject, str)
                or not 1 <= len(principal.subject.strip()) <= 128
                or not isinstance(workspace_id, str)
                or not 1 <= len(workspace_id.strip()) <= 128
                or action not in _ACTIONS):
            return False
        try:
            row = self._read_one(
                """SELECT 1 FROM nexus_financial_permissions
                   WHERE subject = %s AND workspace_id = %s
                     AND action = %s""",
                (principal.subject, workspace_id, action),
            )
        except Exception:
            return False
        return row is not None
