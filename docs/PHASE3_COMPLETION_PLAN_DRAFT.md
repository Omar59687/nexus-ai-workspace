# Phase 3 Completion Plan — Draft for Human Review

**Status:** Planning draft only. Not approved. No implementation is authorized by this document.

**Scope of this document:** Propose how Phase 3 could be completed and evaluated. It does not amend the original blueprint, benchmark cases, scoring rules, production code, migrations, or model defaults.

**Source basis:**

- `docs/PROJECT_BLUEPRINT.md`, especially the 12-phase roadmap, the Mandatory Phase Quality Gate, and the Current status section.
- `README.md`.
- `docs/BENCHMARKS.md`.
- Committed implementation at `17eb240472d94986ca4c50c5117cd41c2fb403db`.
- Existing local benchmark reports under `local_data/llm_benchmarks/`, which are Git-ignored evaluation artifacts.

**Important non-claim:** The original blueprint does **not** define Phase 3 checkpoints or checkpoint-specific acceptance criteria. It names Phase 3 as “Local LLM Integration — Ollama, LangChain, structured outputs, local model benchmarks” (`docs/PROJECT_BLUEPRINT.md:57`) and requires the generic Mandatory Phase Quality Gate (`docs/PROJECT_BLUEPRINT.md:70-83`). The checkpoint sequence and criteria below are **proposals for approval**, not restatements of an existing official plan.

---

## 1. Facts supported by the current repository

### 1.1 Repository position

| Item | Current evidence |
| --- | --- |
| Branch | `phase-1/foundation` |
| HEAD | `17eb240472d94986ca4c50c5117cd41c2fb403db` |
| Commit subject | `feat: add reproducible local LLM benchmark suite` |
| Working tree | Clean at the time of this draft |
| Checkpoint 1 | Local Ollama integration, committed at `9b8227e` |
| Checkpoint 2 | Reproducible benchmarking, committed at `17eb240` |
| Latest complete regression | 116 passed after PostgreSQL was restored |
| PostgreSQL | Running at `127.0.0.1:5433`, reported healthy |
| Latest `pip check` | No broken requirements |
| Latest `alembic check` | No new upgrade operations detected |

The 116-test result, `pip check`, and `alembic check` results were obtained in the immediately preceding verification run. They were not rerun while creating this draft.

### 1.2 Implemented Phase 3 surface

- Ollama HTTP integration is implemented in `src/nexus_ai/ollama.py`.
  - Default base URL: `http://127.0.0.1:11434`.
  - Default model: `llama3.2:latest` (`src/nexus_ai/ollama.py:21`).
  - Uses `POST /api/generate` with `stream: false`.
  - Records response text, model, `done`, total duration, prompt token count, and generated token count.
  - Categorizes timeout, unavailable-service, and invalid-response failures.
- `POST /llm/generate` exposes the Ollama client through FastAPI (`src/nexus_ai/main.py:75-99`).
- Pydantic request/response schemas exist in `src/nexus_ai/schemas.py`, including `LLMGenerateRequest` and `LLMGenerateResponse`.
- The reproducible benchmark subsystem exists under `src/nexus_ai/benchmark/` and `scripts/run_llm_benchmark.py`.
- Benchmark cases and unchanged scoring rules live in `benchmarks/cases.json` and `src/nexus_ai/benchmark/scoring.py`.
- The benchmark runner records warm-up separately from measured trials, rejects incomplete generations from passing, and never overwrites an existing report.
- Diagnostic REST prompt experiments live under `benchmarks/experiments/` and are explicitly separate from the original benchmark case.

### 1.3 Model evidence already recorded

| Model | Benchmark result | Completion state | Notes |
| --- | ---: | --- | --- |
| `llama3.2:latest` | 4/6 | 6/6 completed | REST 0/2; JSON 2/2; HTTP bullets 2/2. REST expansion repeatedly factually wrong. |
| `qwen3:4b` | 0/6 | 0/6 completed | All six trials stopped at the 256-token limit with `done_reason="length"`. |
| `gemma3:4b` | 2/6 | 6/6 completed | REST 0/2; JSON 0/2; HTTP bullets 2/2. JSON failed because of Markdown fences. |
| Concise REST prompt experiment | 2/2 passing trials | 2/2 completed | Correct expansions and four sentences in both trials; limited to one prompt and two trials. |

The original benchmark remains unchanged at version `1.0.1`. The benchmark evaluates deterministic checks, not general model quality or factual reliability.

### 1.4 Documented gaps

- No Phase 3 checkpoint sequence or checkpoint-specific acceptance criteria exist in the repository.
- No Phase 3 acceptance criteria have been approved and recorded.
- No Phase 3 quality-gate decision has been recorded.
- No production structured-output feature exists. The only structured-output behavior is the `structured_json` benchmark case and its evaluator.
- LangChain is named in the Phase 3 roadmap item, but there is no LangChain dependency, import, integration, or use case definition in the repository.
- The blueprint’s Current status section still says “Planning / repository setup” and points to Task 1.1 (`docs/PROJECT_BLUEPRINT.md:104-106`). This is stale relative to committed work.
- The original REST failure for `llama3.2:latest` is documented as a model factual error, not a scoring defect (`docs/BENCHMARKS.md:79-86`).

### 1.5 What is not established

- That `llama3.2:latest` is reliable for factual technical explanations.
- That any alternative model is suitable as the production default.
- That the concise prompt experiment generalizes beyond its two trials.
- That LangChain is necessary for any approved Phase 3 use case.
- That schema-valid JSON implies factually correct content.
- That the current hardware can support a larger model with acceptable latency or memory use.

---

## 2. Evidence rules for this plan

These rules apply to every proposed checkpoint and to the final phase gate.

1. **Facts versus proposals:** Repository behavior and recorded measurements are facts. Checkpoint order, new production features, thresholds, and acceptance criteria below are proposals requiring approval.
2. **Completion versus correctness:** An incomplete response must never count as a successful answer, even if its text looks plausible.
3. **Automated score versus factual correctness:** A deterministic benchmark score measures the named checks only. A passing JSON check does not establish factual truth. A failing REST check may reflect a real factual error or incomplete topical coverage.
4. **JSON/schema validity versus factual correctness:** Parsing successfully against a schema proves structure only. It does not prove that values are true, complete, or appropriate.
5. **No benchmark rewriting:** The original cases, scoring rules, thresholds, and baseline reports remain unchanged. Any new prompt remains an experiment unless separately approved.
6. **No claim without evidence:** A command or test is reported as passing only when it was actually run and its output recorded.
7. **No secrets:** `.env` contents are not read, copied, printed, or committed. Generated reports remain under Git-ignored `local_data/`.
8. **No speed-only decisions:** Latency or throughput alone is insufficient to select a model or accept a structured-output design.

---

## 3. Decisions requiring human approval

The following decisions are unresolved. They must be answered before implementation or before Phase 3 closure, as indicated.

| ID | Decision | Why it is needed | When it must be resolved |
| --- | --- | --- | --- |
| D1 | Approve, revise, or reject the proposed checkpoint sequence in Section 4. | The blueprint has no Phase 3 checkpoint plan. | Before any checkpoint work |
| D2 | Is factual model reliability a Phase 3 exit criterion? If yes, which cases, which models, and what threshold? | The blueprint requires evidence and phase gates but does not define a model-accuracy threshold. Existing evidence shows factual failure for the default model. | Before the final Phase 3 gate |
| D3 | Is the `llama3.2:latest` REST limitation accepted as a documented limitation, or must it be remediated before Phase 3 closes? | The baseline model fails 0/2 on the original REST case. Remediation could mean a model change, a prompt change, or accepting the limitation. Each has different consequences. | Before the final Phase 3 gate |
| D4 | Is LangChain required for a defined Phase 3 use case, or should it remain a deferred decision? | LangChain is named in the roadmap but has no committed use case or dependency. Adding it without a use case would expand scope; omitting it without a decision would leave a roadmap item unresolved. | Proposed decision checkpoint, before the final gate |
| D5 | Is schema-constrained structured output a production requirement, or only a benchmark concern? If production, what is the approved contract and failure behavior? | No production structured-output feature exists. The plan must not invent one. | Before the proposed structured-output checkpoint |
| D6 | Which model remains the production default? | Current source and `.env.example` retain `llama3.2:latest`; no alternative has been adopted. The decision must consider factual reliability, completion, latency, memory, and hardware placement, not speed alone. | Before the final Phase 3 gate |
| D7 | What performance and resource targets apply to Phase 3? | The blueprint requires targets to be defined before judging quality and performance (`docs/PROJECT_BLUEPRINT.md:78`). No Phase 3 targets exist. | Before performance-gate evaluation |
| D8 | What cross-phase integration evidence is required for Phase 3 closure? | The blueprint requires interfaces and data flows between the phase and earlier phases to be tested (`docs/PROJECT_BLUEPRINT.md:77`). The specific integration matrix is not defined. | Before the final Phase 3 gate |

Until these decisions are approved, this draft is a proposal only.

---

## 4. Proposed checkpoint sequence

The labels below are working labels. They do not create official checkpoint numbering or amend the roadmap.

Recommended order:

1. **Proposed Checkpoint 3A — LangChain necessity decision (decision-only).**
2. **Proposed Checkpoint 3B — Schema-constrained structured outputs and validation (implementation, conditional on D5).**
3. **Phase 3 Quality Gate — final verification (not an implementation checkpoint or implementation task).**

Rationale for the order: resolving the LangChain question first prevents an unapproved dependency from shaping the structured-output design. If humans prefer, 3B can begin before 3A only if D5 is approved and the structured-output design explicitly avoids an unapproved LangChain dependency.

### 4.1 Proposed Checkpoint 3A — LangChain necessity decision

**Type:** Decision record and scope clarification. No production integration.

**Purpose:** Determine whether LangChain is required by a concrete, approved Phase 3 use case, or whether it should be deferred or rejected for this phase.

**Dependencies:** D1 approval of this sequence; human availability for D4.

**Proposed deliverables:**

- A short decision record stating one of: adopt for a named use case, defer, or reject for Phase 3.
- If adopted: the named use case, expected benefit, alternatives considered, dependency and license impact, local resource impact, test impact, rollback plan, and a separately scoped implementation plan.
- If deferred or rejected: the rationale and the effect on the Phase 3 scope statement. The original blueprint is not silently rewritten.
- Confirmation that no dependency was added and no production code changed during the decision checkpoint.

**Proposed measurable acceptance criteria:**

1. The decision record explicitly cites the Phase 3 roadmap item and the specific use case, or states that no use case exists.
2. The decision is one of “adopt,” “defer,” or “reject,” with a written rationale.
3. If “adopt,” the record includes a dependency/version proposal, local-only compatibility check, license check, resource estimate, test plan, and rollback plan. No installation occurs in this checkpoint.
4. If “defer” or “reject,” the record states how Phase 3 closure will account for the named roadmap item without claiming it was implemented.
5. A human reviewer approves the record.
6. `git status` shows only the approved decision document, not production or benchmark changes.

### 4.2 Proposed Checkpoint 3B — Schema-constrained structured outputs and validation

**Type:** Conditional implementation proposal. It is not approved until D5 is answered.

**Purpose:** If approved, add a schema-constrained structured-output path with deterministic validation and explicit failure behavior, without changing the existing benchmark cases or scoring rules.

**Dependencies:** D1, D4, and D5. If D4 adopts LangChain, the implementation must follow the approved decision record; if D4 defers or rejects LangChain, the implementation must not depend on it.

**Proposed scope:**

- One human-approved structured-output contract (request shape, response schema, allowed keys/types, and failure behavior).
- Deterministic validation against that contract.
- Explicit rejection of malformed JSON, Markdown fences, extra keys, missing keys, wrong types, empty responses, and incomplete generations.
- Documented distinction between schema validity and factual correctness.
- Unit and API/integration tests for the approved contract.
- No change to `benchmarks/cases.json`, benchmark scoring, thresholds, or historical reports.

**Out of scope unless separately approved:**

- New agents or orchestration.
- RAG, embeddings, or vector storage.
- Changes to task CRUD or PostgreSQL schema.
- Changing the default model.
- Broad “LLM reliability” claims.
- LangChain installation before D4 approval.
- Replacing the original REST benchmark or its scoring.

**Proposed deliverables:**

- The approved contract and its documentation.
- Implementation of the contract.
- Validation/error-handling tests.
- API integration test for the structured-output path.
- Evidence that incomplete generations cannot pass.
- A short note separating structural validity from factual correctness.
- Updated relevant non-blueprint documentation.

**Proposed measurable acceptance criteria:**

1. A valid response matching the approved schema is accepted and returned without silent mutation.
2. Valid JSON with extra keys, missing keys, or wrong types is rejected with a deterministic, documented error.
3. Markdown-fenced JSON, surrounding commentary, empty output, and non-JSON output are rejected.
4. An incomplete generation (`done` not true, or `done_reason="length"`, or token limit reached) is never reported as a successful structured response.
5. Unit tests cover the valid case and every rejection category above.
6. An API/integration test exercises the endpoint or service boundary and verifies the documented error mapping.
7. Existing benchmark tests continue to pass unchanged.
8. The full regression suite passes against PostgreSQL.
9. `pip check` and `alembic check` pass, or any environment blocker is reported explicitly rather than skipped silently.
10. The evidence package explicitly states that schema validation does not prove factual correctness.
11. No historical benchmark report is overwritten; any new run uses a unique run ID.
12. A human reviewer approves the contract, implementation, tests, and limitation notes.

### 4.3 Phase 3 Quality Gate

**Type:** Final verification gate. It is not an implementation checkpoint and should not be treated as one, consistent with the blueprint’s statement that the final gate is verification, not an additional implementation task (`docs/PROJECT_BLUEPRINT.md:83`).

**Entry criteria:**

- D1 through D8 are resolved.
- Any approved checkpoint work is complete and reviewed.
- The original benchmark cases and scoring rules remain unchanged.
- A model/default decision and a documented-limitations statement exist.

**Required evidence:**

1. **Acceptance criteria:** Every approved Phase 3 criterion has explicit evidence.
2. **Phase tests:** Unit, API, negative-path, and integration tests for Phase 3 pass.
3. **Regression tests:** The full suite passes against the candidate state, including all Phase 1 and Phase 2 tests.
4. **Cross-phase integration:** At minimum, test the interfaces and data flows between:
   - FastAPI and the Ollama client;
   - FastAPI and PostgreSQL-backed task CRUD;
   - the benchmark runner and the unchanged cases/scoring;
   - the approved structured-output path, if implemented.
   The exact test matrix is subject to D8.
5. **Benchmark evidence:** Re-run or cite the latest benchmark reports with documented model names, Ollama version, hardware, settings, completion state, tokens, and unchanged scoring. Preserve all historical reports.
6. **Performance and resource evidence:** Record measured latency, token counts, and observed hardware placement. Judge them only against targets approved under D7. Do not select a model on speed alone.
7. **Quality checks:** Run the applicable compile, dependency, migration, and diff checks. Report failures honestly.
8. **Review:** Review code, dependencies, configuration, documentation, and outstanding risks.
9. **Evidence record:** Record commands, environment, test totals, failures, and benchmark results. Never describe an unrun test as passing.
10. **Gate decision:** Any failed criterion or unresolved critical/high-severity issue blocks progression. Fix and rerun the affected tests plus the full regression suite.

**Proposed measurable closure checklist:**

- [ ] Phase 3 objective mapped item by item: Ollama, LangChain decision outcome, structured outputs decision/outcome, local model benchmarks.
- [ ] Approved decisions D1–D8 recorded with approver and date.
- [ ] Full regression suite passes with exact totals recorded.
- [ ] Phase 3 tests pass with exact totals recorded.
- [ ] Cross-phase integration tests pass with exact totals recorded.
- [ ] Benchmark reports remain Git-ignored and all historical reports are preserved.
- [ ] Model/default decision recorded, including factual limitations and completion failures.
- [ ] Performance targets were approved before measurement and results are reported against them.
- [ ] `.env` remains ignored and untracked; no secrets appear in docs, reports, or logs.
- [ ] No critical/high-severity issue remains unresolved.
- [ ] Human reviewer signs the gate decision.

**Phase 3 cannot be closed by this draft alone.** Closure requires the approved decisions, checkpoint evidence, and gate review above.

---

## 5. Phase 3 closure evidence package

The following evidence should be assembled for human review before any closure claim:

1. Decision records for D1–D8.
2. Checkpoint 3A decision record, including the LangChain outcome.
3. Checkpoint 3B contract, implementation notes, and test evidence, if approved.
4. Full regression output with exact test totals.
5. Phase-specific and cross-phase integration test output.
6. Benchmark reports with model identity, Ollama version, hardware, settings, completion state, tokens, and scoring.
7. Performance/resource measurements compared with pre-approved targets.
8. A documented limitations section covering:
   - `llama3.2:latest` REST factual failure;
   - `qwen3:4b` incomplete generation under the tested protocol;
   - `gemma3:4b` unchanged-benchmark score of 2/6;
   - the limited scope of the two-trial concise prompt experiment;
   - the distinction between structural validity and factual correctness.
9. Review notes for code, dependencies, configuration, and documentation.
10. Final Git status confirming no unapproved changes.

---

## 6. Risks and limitations

### 6.1 Factual reliability

- `llama3.2:latest` has repeatedly produced a factually wrong REST expansion under the original prompt while still completing the response. Completion and fluency are not factual correctness.
- `gemma3:4b` completed all trials but scored 2/6 on the unchanged benchmark. Its REST expansion was factually correct in the observed trials, but the automated case still failed on keyword coverage; its JSON failed on Markdown fences.
- `qwen3:4b` produced no completed answers under the tested 256-token protocol, so the comparison is inconclusive for factual quality.
- The concise REST experiment passed twice but covers one prompt and one case. It does not establish general reliability.

### 6.2 Structural validity versus truth

- A JSON object can be perfectly valid and still contain false or inappropriate values.
- A schema-constrained output feature can improve mechanical reliability without improving factual accuracy.
- Approval of structured outputs must not be presented as approval of model factual reliability.

### 6.3 Benchmark and evaluation limitations

- The benchmark is intentionally small and deterministic. It is not a general model-quality evaluation.
- Two measured trials per case are limited evidence.
- Deterministic seeding does not guarantee bit-for-bit identical output on every backend.
- Prompt wording materially affects results; the concise experiment demonstrates sensitivity but not generalization.
- Changing cases, scoring, or thresholds would invalidate comparison with the existing baseline. Any such change requires separate approval and a new benchmark version.

### 6.4 Resource and hardware constraints

- Target hardware is 16 GB RAM with a 2 GB NVIDIA MX450 (`docs/PROJECT_BLUEPRINT.md:20`).
- GPU acceleration may not fit a given model; observed placement must be recorded rather than assumed.
- Larger or differently quantized models may change latency, memory pressure, and completion behavior.
- Model comparisons must be sequential to reduce memory pressure, as previously practiced.

### 6.5 Dependency and scope risks

- Adding LangChain without a defined use case would expand scope and maintenance burden.
- Adding a dependency requires license, resource, and compatibility review before approval.
- The blueprint names LangChain, so deferring it requires an explicit human decision, not silent omission.
- The blueprint’s stale Current status section can mislead future contributors; updating it is a documentation decision separate from this draft.

### 6.6 Process risks

- Proceeding without approved acceptance criteria would violate the phase-gate principle.
- Treating a benchmark pass as factual certification would overstate the evidence.
- Skipping PostgreSQL-dependent tests or masking environment failures would produce a false completion claim.
- Overwriting historical reports would destroy baseline evidence.

---

## 7. Recommendation

1. Review and resolve D1–D8 before any implementation.
2. If D1 is approved, execute the LangChain decision checkpoint first.
3. Approve or reject D5 before starting the structured-output checkpoint.
4. Do not change the default model until D6 is resolved with evidence covering factual reliability, completion, latency, tokens, and resource use.
5. Close Phase 3 only through the documented quality gate and evidence package above.

This document is a planning proposal. It does not authorize implementation, dependency installation, model changes, benchmark changes, commits, or phase closure.
