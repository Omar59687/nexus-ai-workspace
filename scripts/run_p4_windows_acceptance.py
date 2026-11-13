"""Run Nexus P4 verification against explicitly disposable local databases.

Database checks are opt-in through two DSNs. Both targets must be loopback,
have the dedicated P4 name prefixes, and contain no user tables before the
runner executes migrations or tests. Reports are written outside the repo.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_DATABASES = {"nexus_ai", "nexus_ai_p4_test_ff120184bd33"}
EMPTY_QUERY = """SELECT 1
FROM pg_catalog.pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'public')
  AND n.nspname NOT LIKE 'pg_toast%'
UNION ALL
SELECT 1 FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
UNION ALL
SELECT 1 FROM pg_catalog.pg_proc p
JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
UNION ALL
SELECT 1 FROM pg_catalog.pg_type t
JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = 'public'
UNION ALL
SELECT 1 FROM pg_catalog.pg_collation WHERE collnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_operator WHERE oprnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_opclass WHERE opcnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_opfamily WHERE opfnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_conversion WHERE connamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_ts_config WHERE cfgnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_ts_dict WHERE dictnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_ts_parser WHERE prsnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_ts_template WHERE tmplnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_statistic_ext WHERE stxnamespace = 'public'::regnamespace
UNION ALL
SELECT 1 FROM pg_catalog.pg_extension WHERE extname <> 'plpgsql'
UNION ALL
SELECT 1 FROM pg_catalog.pg_largeobject_metadata
UNION ALL
SELECT 1 FROM pg_catalog.pg_event_trigger
UNION ALL
SELECT 1 FROM pg_catalog.pg_publication
UNION ALL
SELECT 1 FROM pg_catalog.pg_subscription
LIMIT 1"""


def _parse_disposable_url(value: str, prefix: str) -> dict[str, str]:
    parsed = urlsplit(value)
    database = unquote(parsed.path.lstrip("/"))
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("database URL must use PostgreSQL")
    if not re.fullmatch(re.escape(prefix) + r"[A-Za-z0-9_]{4,48}", database):
        raise ValueError(f"database name must match {prefix}<4-48 safe characters>")
    if database in FORBIDDEN_DATABASES:
        raise ValueError("protected database name is not permitted")
    host = parsed.hostname or ""
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("database URL must point to a loopback host")
    if not parsed.username or not parsed.password:
        raise ValueError("database URL must provide local credentials")
    return {
        "database": database,
        "host": host,
        "port": str(parsed.port or 5432),
        "username": unquote(parsed.username),
        "password": unquote(parsed.password),
    }


def _ensure_empty_database(config: dict[str, str]) -> None:
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required for database preflight") from exc
    with psycopg.connect(
        host=config["host"], port=int(config["port"]), dbname=config["database"],
        user=config["username"], password=config["password"], connect_timeout=5,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(EMPTY_QUERY)
            if cursor.fetchone() is not None:
                raise RuntimeError("database contains user objects; refusing all database writes")


def _run(label: str, command: list[str], env: dict[str, str], report_dir: Path,
         secrets: tuple[str, ...], *, required: bool = True) -> dict[str, object]:
    try:
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", check=False)
        output = result.stdout + result.stderr
        for secret in secrets:
            if secret:
                output = output.replace(secret, "[REDACTED]")
        safe_label = re.sub(r"[^A-Za-z0-9_-]", "_", label)
        (report_dir / f"{safe_label}.log").write_text(output, encoding="utf-8")
        status = "PASS" if result.returncode == 0 else "FAIL"
        return {"name": label, "status": status, "exit_code": result.returncode,
                "required": required}
    except OSError as exc:
        return {"name": label, "status": "BLOCKED", "error_type": type(exc).__name__,
                "required": required}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-branch", default="feature/p4-live-integration-hardening")
    parser.add_argument("--run-live-models", action="store_true")
    args = parser.parse_args(argv)

    report_root = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "NexusAI" / "reports"
    report_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_dir = report_root / f"p4-acceptance-{stamp}"
    report_dir.mkdir()
    checks: list[dict[str, object]] = []
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=False)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=False)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                            capture_output=True, text=True, check=False)
    git_ok = (branch.returncode == 0 and head.returncode == 0
              and status.returncode == 0 and not status.stdout.strip()
              and branch.stdout.strip() == args.expected_branch
              and head.stdout.strip().lower() == args.expected_commit.lower())
    checks.append({"name": "exact_git_revision", "status": "PASS" if git_ok else "FAIL",
                   "required": True})
    if not git_ok:
        _write_report(report_dir, checks)
        _print_status(checks, report_dir)
        return 1

    app = integration = None
    database_preflight_passed = False
    integration_url = os.environ.get("NEXUS_P4_TEST_DATABASE_URL", "")
    app_url = os.environ.get("NEXUS_P4_APP_TEST_DATABASE_URL", "")
    try:
        import psycopg  # noqa: F401
        if not integration_url or not app_url:
            raise ValueError("both P4 disposable database URL variables are required")
        integration = _parse_disposable_url(integration_url, "nexus_ai_p4_it_")
        app = _parse_disposable_url(app_url, "nexus_ai_p4_app_")
        if integration["database"] == app["database"]:
            raise ValueError("application and integration databases must be distinct")
        _ensure_empty_database(integration)
        _ensure_empty_database(app)
        database_preflight_passed = True
    except Exception as exc:
        checks.append({"name": "database_disposable_preflight", "status": "BLOCKED",
                       "error_type": type(exc).__name__, "required": True})
    else:
        checks.append({"name": "database_disposable_preflight", "status": "PASS", "required": True})

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    secrets: tuple[str, ...] = ()
    if database_preflight_passed:
        # These explicit process values override dotenv defaults used by the app.
        env.update({"POSTGRES_DB": app["database"], "POSTGRES_USER": app["username"],
                    "POSTGRES_PASSWORD": app["password"], "POSTGRES_PORT": app["port"],
                    "NEXUS_P4_TEST_DATABASE_URL": integration_url,
                    "NEXUS_P4_APP_TEST_DATABASE_URL": app_url})
        secrets = (integration_url, app_url, integration["username"], app["username"],
                   integration["password"], app["password"])

    checks.append(_run("dependency_check", [sys.executable, "-m", "pip", "check"], env,
                       report_dir, secrets))
    checks.append(_run("compilation", [sys.executable, "-m", "compileall", "-q", "src", "tests",
                                       "experiments", "scripts"], env, report_dir, secrets))
    checks.append(_run("diff_check", ["git", "diff", "--check"], env, report_dir, secrets))
    if database_preflight_passed:
        checks.append(_run("alembic_upgrade", [sys.executable, "-m", "alembic", "upgrade", "head"],
                           env, report_dir, secrets))
        checks.append(_run("full_regression", [sys.executable, "-m", "pytest", "-q"], env,
                           report_dir, secrets))
        checks.append(_run("alembic_schema_check", [sys.executable, "-m", "alembic", "check"],
                           env, report_dir, secrets))
        integration_env = env.copy()
        integration_env["NEXUS_P4_TEST_DATABASE_URL"] = integration_url
        checks.append(_run("postgres_integration", [sys.executable, "-m", "pytest", "-q",
                           "tests/persistence/test_postgres_integration.py"], integration_env,
                           report_dir, secrets))
    else:
        for name in ("alembic_upgrade", "full_regression", "alembic_schema_check", "postgres_integration"):
            checks.append({"name": name, "status": "BLOCKED",
                           "reason": "safe isolated database preflight did not pass", "required": True})
    checks.append(_run("windows_pdf", [sys.executable, "-m", "pytest", "-q",
                       "tests/documents/test_pdf_worker.py",
                       "tests/documents/test_pdf_worker_windows.py"], env, report_dir, secrets))
    if args.run_live_models:
        checks.append(_run("local_e5_ollama", [sys.executable, "scripts/run_local_rag_integration.py",
                       "--run-live"], env, report_dir, secrets))
    else:
        checks.append({"name": "local_e5_ollama", "status": "SKIPPED",
                       "reason": "use --run-live-models to opt in", "required": False})
    _write_report(report_dir, checks)
    _print_status(checks, report_dir)
    return 1 if any(c["status"] in {"FAIL", "BLOCKED"} and c.get("required") for c in checks) else 0


def _write_report(report_dir: Path, checks: list[dict[str, object]]) -> None:
    (report_dir / "summary.json").write_text(
        json.dumps({"checks": checks}, indent=2, ensure_ascii=False), encoding="utf-8")


def _print_status(checks: list[dict[str, object]], report_dir: Path) -> None:
    for check in checks:
        print(f"{check['status']}: {check['name']}")
    print(f"Reports: {report_dir}")


if __name__ == "__main__":
    raise SystemExit(main())
