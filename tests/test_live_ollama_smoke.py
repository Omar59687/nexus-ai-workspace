"""Safety checks for the opt-in live Ollama smoke harness."""

from __future__ import annotations

import builtins
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY_ROOT / "scripts" / "smoke_structured_ollama.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("smoke_structured_ollama", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_smoke_requires_explicit_opt_in_before_app_import(tmp_path: Path) -> None:
    guard_dir = tmp_path / "guard"
    guard_dir.mkdir()
    (guard_dir / "sitecustomize.py").write_text(
        "import builtins\n"
        "original_import = builtins.__import__\n"
        "def guarded_import(name, *args, **kwargs):\n"
        "    if name == 'nexus_ai' or name.startswith('nexus_ai.') or name.startswith('fastapi.testclient'):\n"
        "        raise AssertionError('application import attempted before opt-in')\n"
        "    return original_import(name, *args, **kwargs)\n"
        "builtins.__import__ = guarded_import\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("NEXUS_LIVE_OLLAMA", None)
    env["PYTHONPATH"] = str(guard_dir)
    output = (
        REPOSITORY_ROOT
        / "local_data"
        / f"opt_in_gate_{tmp_path.name}.json"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--model",
            "test-model",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 2
    assert "Live Ollama smoke is disabled" in result.stderr
    assert "application import attempted" not in result.stderr
    assert not output.exists()


def test_output_path_must_resolve_inside_local_data_without_app_import(
    tmp_path: Path, monkeypatch,
) -> None:
    # Track import attempts instead of sys.modules because another test may have
    # imported the application earlier in the same pytest process.
    attempted: list[str] = []
    original_import = builtins.__import__

    def tracking_import(name, *args, **kwargs):
        if name == "nexus_ai" or name.startswith("nexus_ai.") or name.startswith("fastapi"):
            attempted.append(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", tracking_import)
    module = _load_harness()
    assert attempted == []

    project = tmp_path / "repo"
    inside = module.resolve_output_path("local_data/evidence.json", project)
    assert inside == (project / "local_data" / "evidence.json").resolve()

    outside = tmp_path / "evidence.json"
    try:
        module.resolve_output_path(outside, project)
    except ValueError as exc:
        assert "inside the repository local_data" in str(exc)
    else:
        raise AssertionError("outside evidence path was accepted")
    assert attempted == []


def test_timeout_must_be_positive_and_below_hard_cap() -> None:
    module = _load_harness()
    for value in (0, -1, module.MAX_TIMEOUT_SECONDS + 0.1):
        try:
            module._parse_args(
                ["--model", "test-model", "--output", "local_data/e.json", "--timeout-seconds", str(value)]
            )
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError(f"invalid timeout {value} was accepted")
