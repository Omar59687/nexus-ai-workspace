"""Guarded entry points for synthetic development-only RAG evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from experiments.rag_prototype.evaluation import (
    RetrieverSpec,
    FixtureError,
    load_fixture,
    run_evaluation,
)


def load_provisional_fixture(path: str | Path) -> dict[str, Any]:
    """Load a synthetic dev fixture and reject holdout or mixed-split inputs."""
    fixture = load_fixture(path)
    splits = {row.get("split") for row in fixture["documents"]}
    if splits != {"dev"}:
        raise FixtureError("provisional evaluation accepts a dev-only fixture; holdout is protected")
    if not fixture.get("synthetic"):
        raise FixtureError("provisional evaluation requires a clearly labeled synthetic fixture")
    if any(query.get("split") != "dev" for query in fixture["queries"]):
        raise FixtureError("provisional evaluation rejects queries outside the dev split")
    return fixture


def run_provisional_evaluation(
    fixture: str | Path | Mapping[str, Any],
    *,
    k: int = 3,
    retrievers: Mapping[str, Any] | None = None,
    measure_latency: bool = False,
) -> dict[str, Any]:
    """Evaluate synthetic dev data only and label results as provisional."""
    loaded = load_provisional_fixture(fixture) if isinstance(fixture, (str, Path)) else dict(fixture)
    if not loaded.get("synthetic"):
        raise FixtureError("provisional evaluation requires a clearly labeled synthetic fixture")
    splits = {row.get("split") for row in loaded.get("documents", [])}
    if splits != {"dev"} or any(row.get("split") != "dev" for row in loaded.get("queries", [])):
        raise FixtureError("provisional evaluation accepts a dev-only fixture; holdout is protected")
    report = run_evaluation(
        loaded,
        split="dev",
        k=k,
        retrievers=retrievers,
        measure_latency=measure_latency,
    )
    report["evaluation_stage"] = "provisional-development"
    report["interpretation"] = "synthetic fixture mechanics only; not evidence of real-corpus retrieval quality"
    return report
