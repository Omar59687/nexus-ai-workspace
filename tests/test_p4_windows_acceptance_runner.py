from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from scripts import run_p4_windows_acceptance as runner


class AcceptanceRunnerDatabaseGateTests(unittest.TestCase):
    def test_failed_database_preflight_never_invokes_database_commands(self):
        commit = "a" * 40
        run_names: list[str] = []

        def fake_git(command, **_kwargs):
            if command[1:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                return types.SimpleNamespace(returncode=0, stdout="feature/p4-live-integration-hardening\n")
            if command[1:] == ["rev-parse", "HEAD"]:
                return types.SimpleNamespace(returncode=0, stdout=commit + "\n")
            if command[1:] == ["status", "--porcelain"]:
                return types.SimpleNamespace(returncode=0, stdout="")
            raise AssertionError(f"unexpected git command: {command[1:]}")

        def fake_run(name, *_args, **_kwargs):
            run_names.append(name)
            return {"name": name, "status": "PASS", "required": True}

        fake_configs = {
            "nexus_ai_p4_it_": {"database": "nexus_ai_p4_it_test", "username": "test", "password": "secret", "port": "5432"},
            "nexus_ai_p4_app_": {"database": "nexus_ai_p4_app_test", "username": "test", "password": "secret", "port": "5432"},
        }
        with tempfile.TemporaryDirectory() as report_root:
            variables = {
                "LOCALAPPDATA": report_root,
                "NEXUS_P4_TEST_DATABASE_URL": "postgresql://test:secret@127.0.0.1/nexus_ai_p4_it_test",
                "NEXUS_P4_APP_TEST_DATABASE_URL": "postgresql://test:secret@127.0.0.1/nexus_ai_p4_app_test",
            }
            with (
                patch.dict(os.environ, variables, clear=False),
                patch.dict(sys.modules, {"psycopg": types.ModuleType("psycopg")}),
                patch.object(runner.subprocess, "run", side_effect=fake_git),
                patch.object(runner, "_parse_disposable_url",
                             side_effect=lambda _url, prefix: fake_configs[prefix]),
                patch.object(runner, "_ensure_empty_database",
                             side_effect=RuntimeError("not empty")),
                patch.object(runner, "_run", side_effect=fake_run),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = runner.main(["--expected-commit", commit])

        self.assertEqual(result, 1)
        self.assertNotIn("alembic_upgrade", run_names)
        self.assertNotIn("full_regression", run_names)
        self.assertNotIn("alembic_schema_check", run_names)
        self.assertNotIn("postgres_integration", run_names)
        self.assertIn("windows_pdf", run_names)


if __name__ == "__main__":
    unittest.main()
