"""Disposable localhost PostgreSQL authentication and permission tests."""
import hashlib
import os
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_ai.financial_review_access import (
    FINANCIAL_AUTH_SCHEMA_DDL, PostgresFinancialAccess,
)
from nexus_ai.financial_review_http import create_financial_review_router
from tests.persistence import test_postgres_integration as _guard


class _Ledger:
    workspace_id = "tenant"

    def __init__(self):
        self.calls = []

    def status(self):
        self.calls.append("status")
        return {"pending": 0}

    def reject(self, item_id, *, reviewer_id):
        self.calls.append((item_id, reviewer_id))


class FinancialAccessPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _guard.PostgresLiveIntegrationTests.setUpClass.__func__(cls)

    def setUp(self):
        self._schema = _guard._create_test_schema(self._psycopg, self._base_params)
        params = dict(self._base_params)
        params["options"] = f"-csearch_path={self._schema}"
        self._params = params
        with self._psycopg.connect(**params) as db:
            with db.cursor() as cur:
                for stmt in FINANCIAL_AUTH_SCHEMA_DDL:
                    cur.execute(stmt)
        self.token = os.urandom(32).hex()
        self.ledger = _Ledger()
        access = PostgresFinancialAccess(lambda: self._psycopg.connect(**params))
        app = FastAPI()
        app.include_router(create_financial_review_router(
            workspace_id="tenant", ledger_factory=lambda: self.ledger,
            authenticate_request=access.authenticate_request,
            authorize=access.authorize,
        ))
        self.client = TestClient(app)

    def tearDown(self):
        if getattr(self, "_schema", None):
            _guard._drop_test_schema(self._psycopg, self._base_params, self._schema)

    def sql(self, statement, args=()):
        with self._psycopg.connect(**self._params) as db:
            with db.cursor() as cur:
                cur.execute(statement, args)

    def headers(self, token=None):
        return {"Authorization": "Bearer " + (self.token if token is None else token)}

    def provision(self, *, expired=False, revoked=False):
        self.sql(
            """INSERT INTO nexus_financial_sessions
               (token_sha256, subject, expires_at, revoked_at)
               VALUES (%s, 'reviewer', now() + (%s * interval '1 second'),
                       CASE WHEN %s THEN now() ELSE NULL END)""",
            (hashlib.sha256(self.token.encode("ascii")).hexdigest(),
             -10 if expired else 3600, revoked),
        )

    def test_unprovisioned_invalid_and_duplicate_headers_denied(self):
        assert self.client.get("/financial-reviews/status",
                               headers=self.headers()).status_code == 401
        for token in ("123", "x" * 64, "A" * 64, self.token + "x"):
            assert self.client.get("/financial-reviews/status",
                                   headers=self.headers(token)).status_code == 401
        assert self.client.get("/financial-reviews/status").status_code == 401
        assert self.ledger.calls == []

    def test_provisioned_session_requires_workspace_grant(self):
        self.provision()
        assert self.client.get("/financial-reviews/status",
                               headers=self.headers()).status_code == 403
        self.sql("""INSERT INTO nexus_financial_permissions
                    (subject, workspace_id, action)
                    VALUES ('reviewer', 'tenant', 'status')""")
        assert self.client.get("/financial-reviews/status",
                               headers=self.headers()).status_code == 200
        assert self.client.post("/financial-reviews/selections/2/reject",
                                headers=self.headers()).status_code == 403
        self.sql("""INSERT INTO nexus_financial_permissions
                    (subject, workspace_id, action)
                    VALUES ('reviewer', 'tenant', 'reject')""")
        assert self.client.post("/financial-reviews/selections/2/reject",
                                headers=self.headers()).status_code == 204
        assert self.ledger.calls[-1] == (2, "reviewer")
        self.sql("""DELETE FROM nexus_financial_permissions
                    WHERE subject = 'reviewer' AND action = 'status'""")
        assert self.client.get("/financial-reviews/status",
                               headers=self.headers()).status_code == 403

    def test_expiration_and_revocation_fail_closed(self):
        self.provision(expired=True)
        assert self.client.get("/financial-reviews/status",
                               headers=self.headers()).status_code == 401
        self.sql("""UPDATE nexus_financial_sessions
                    SET expires_at = now() + interval '1 hour',
                        revoked_at = now()""")
        assert self.client.get("/financial-reviews/status",
                               headers=self.headers()).status_code == 401

    def test_grant_other_workspace_does_not_authorize_tenant(self):
        self.provision()
        self.sql("""INSERT INTO nexus_financial_permissions
                    (subject, workspace_id, action)
                    VALUES ('reviewer', 'other-tenant', 'status')""")
        assert self.client.get("/financial-reviews/status",
                               headers=self.headers()).status_code == 403
        assert self.ledger.calls == []


if __name__ == "__main__":
    unittest.main()
