"""Trusted-operator-only provisioning for opaque financial review sessions.

Not an HTTP endpoint, not imported by the default app, and never connects
automatically. Use a distinct DB writer role in a private operator process.
Raw bearer tokens are returned once and are NEVER printed by this module.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import secrets
from typing import Callable

from nexus_ai.financial_review_access import _ACTIONS, _TOKEN_PATTERN
from nexus_ai.financial_review_workflow import _require_text


class FinancialReviewProvisioner:
    """Controlled session issuance/revocation and tenant grant changes.

    The caller MUST enforce operator authorization, protected secret
    delivery, backups, auditing and a least-privilege writer DB role.
    This is intentionally not exposed in FastAPI.
    """

    def __init__(self, connection_factory: Callable):
        if not callable(connection_factory):
            raise ValueError("trusted provisioning connection required")
        self._connect = connection_factory

    @contextmanager
    def _transaction(self):
        connection = self._connect()
        try:
            if getattr(connection, "autocommit", False):
                raise ValueError("provisioning requires transactions")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_session(self, *, subject: str, ttl_seconds: int = 3600) -> str:
        """Return 32 random bytes as hex to a trusted secret-delivery caller.

        A new session has ZERO permissions until a separate explicit grant.
        Maximum lifetime is 24 hours; no refresh mechanism is provided.
        """
        subject = _require_text(subject, "operator subject", 128)
        if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 86400:
            raise ValueError("invalid session lifetime")
        token = secrets.token_hex(32)
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        with self._transaction() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO nexus_financial_sessions
                       (token_sha256, subject, expires_at)
                       VALUES (%s, %s, now() + (%s * interval '1 second'))""",
                    (digest, subject, ttl_seconds),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("session provisioning failed")
        return token

    def revoke_session(self, *, token_sha256: str) -> bool:
        """Revoke using the stored SHA-256 digest, not a raw bearer token."""
        if not isinstance(token_sha256, str) or not _TOKEN_PATTERN.fullmatch(token_sha256):
            raise ValueError("invalid session digest")
        with self._transaction() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """UPDATE nexus_financial_sessions
                       SET revoked_at = now()
                       WHERE token_sha256 = %s AND revoked_at IS NULL""",
                    (token_sha256,),
                )
                return cursor.rowcount == 1

    def grant(self, *, subject: str, workspace_id: str, action: str) -> None:
        subject = _require_text(subject, "operator subject", 128)
        workspace_id = _require_text(workspace_id, "workspace", 128)
        if action not in _ACTIONS:
            raise ValueError("invalid financial review action")
        with self._transaction() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO nexus_financial_permissions
                       (subject, workspace_id, action)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (subject, workspace_id, action) DO NOTHING""",
                    (subject, workspace_id, action),
                )

    def revoke_grant(self, *, subject: str, workspace_id: str, action: str) -> bool:
        subject = _require_text(subject, "operator subject", 128)
        workspace_id = _require_text(workspace_id, "workspace", 128)
        if action not in _ACTIONS:
            raise ValueError("invalid financial review action")
        with self._transaction() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """DELETE FROM nexus_financial_permissions
                       WHERE subject = %s AND workspace_id = %s AND action = %s""",
                    (subject, workspace_id, action),
                )
                return cursor.rowcount == 1
