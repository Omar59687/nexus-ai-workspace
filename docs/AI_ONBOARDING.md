# AI Session Onboarding

**Mandatory entry point for every AI session working on Nexus AI.**

This file tells a fresh AI assistant how to resume work without reconstructing project history from chat logs. Read it before inspecting or changing code.

## 1. Read in this order

1. This file: `docs/AI_ONBOARDING.md`.
2. `docs/PROJECT_PLAN.md` — vision, owner-approved decisions, requirements, risks, and open questions.
3. `docs/PROJECT_CHECKPOINTS.md` — current status, evidence, blockers, and the next checkpoint.
4. `docs/ARCHITECTURE.md` — verified current architecture versus intended target.
5. `docs/ROADMAP.md` — the preserved 12-phase roadmap and phase status.
6. `GLOSSARY.md` — canonical vocabulary.
7. Relevant ADRs in `docs/adr/`.
8. The actual source, tests, and benchmark files for the area you are touching.

Do not rely on an old chat summary when a repository document or file can be checked directly.

## 2. Verify repository identity before doing anything

From the repository root, run:

```powershell
git branch --show-current
git rev-parse HEAD
git status --short --branch
git diff --stat
git diff --cached --stat
```

Verified execution baseline for the current CP5/CP6 work:

- Branch: `phase-1/foundation`
- Baseline commit: `e45a7aa2a7b7d69dea808b6811e69ca1afd74ec4` on `phase-1/foundation`
- Work is being performed in an isolated clone; the owner's Windows checkout is not mounted or modified
- Owner-reported local untracked `.agents/` and `skills-lock.json` were not present in the clone and have not been overwritten
- Current changes and verification evidence are exported separately before handoff

The repository is the authority. If the branch, HEAD, or working tree differs from the checkpoint records, stop and investigate before editing. Preserve all uncommitted and untracked work.

If the repository is unavailable, stop. Do not reconstruct work from memory.

Never read, print, copy, or commit `.env` or its contents. `.env.example` is safe to read.

## 3. Identify the approved checkpoint

1. Open `docs/PROJECT_CHECKPOINTS.md`.
2. Find the checkpoint whose status is `READY`, `IN_PROGRESS`, or `REVIEW_PENDING`.
3. Confirm its dependencies are satisfied.
4. Confirm the owner has authorized work on it.

At the verified CP5/CP6 handoff:

- The active workstream is Phase 3.
- `P3-CP4` is owner-accepted at commit `e45a7aa`; Windows validation is owner-reported, not rerun in this Linux environment.
- `P3-CP5` is implemented and independently reviewed in an isolated, uncommitted diff; owner review is pending.
- `P3-CP6` is blocked on PostgreSQL-backed full regression and Alembic checks in this environment.
- `P3-QG` (Phase 3 quality gate) is `BLOCKED`.
- The next action is owner review of the exported patch and a Windows full-suite/database rerun. Do not claim Phase 3 acceptance.

## 4. Respect file ownership

- If a Software Factory V2 assignment is active, edit only the paths assigned to your implementation slot. See `.opencode/agents/` and `docs/SOFTWARE_FACTORY_V2.md`.
- Reviewers are read-only and must not edit files, stage changes, or commit.
- Do not edit another agent's owned files to "fix" a review finding. Report the conflict to the orchestrator or owner.
- Do not modify production source, tests, models, migrations, benchmark definitions, scoring, installed skills, or `.env` for a documentation-only task.

## 5. Inspect actual files, not summaries

- Read the relevant source and tests before proposing changes.
- Check imports and call sites; do not assume a module is wired into FastAPI because a file exists.
- Check whether a file is tracked, untracked, or ignored.
- Treat an agent's completion report as context, not as review evidence.
- Treat generated code as unaccepted code until tests and review are recorded.

## 6. Run the required tests and record evidence

For the checkpoint you are working on:

1. Read its "Required test commands" in `docs/PROJECT_CHECKPOINTS.md`.
2. Run the focused tests first.
3. Run the full regression suite only when the checkpoint or phase requires it.
4. Record the exact command, environment, date, totals, and failures.
5. If a command was not run, say so. Never describe an unrun test as passing.
6. Do not overwrite historical benchmark reports.

A documentation-only task does not require rerunning the full test suite. Run the documentation checks specified by the task.

## 7. Update checkpoint status correctly

Use only these statuses:

`NOT_STARTED`, `READY`, `IN_PROGRESS`, `IMPLEMENTED`, `REVIEW_PENDING`, `CHANGES_REQUESTED`, `VERIFIED`, `ACCEPTED`, `BLOCKED`, `DEFERRED`.

Rules:

- `IMPLEMENTED` means code or documentation exists. It does not mean verified or accepted.
- `VERIFIED` requires recorded test evidence.
- `ACCEPTED` requires evidence, review disposition, and owner or delegated acceptance.
- Do not mark a task `[x]` merely because a file exists.
- Record blockers and the next action.
- Keep historical evidence labeled as historical.

## 8. Documentation update protocol

When your work changes the project state:

1. Update the checkpoint record with tasks, evidence, review status, blockers, next action, and commit SHA if one exists.
2. Update `docs/ARCHITECTURE.md` if a module moves from proposed to implemented.
3. Update `docs/PROJECT_PLAN.md` if an approved decision, requirement, or risk changes.
4. Update `docs/ROADMAP.md` only when phase status changes; do not renumber phases.
5. Add or supersede an ADR when a hard-to-reverse technical decision changes.
6. Update `GLOSSARY.md` when a domain term is added or sharpened.
7. Keep internal links valid.

## 9. Prohibited actions

Do not:

- Invent progress, test results, review outcomes, model identities, or benchmark numbers.
- Modify unrelated files.
- Treat generated or untracked code as accepted code.
- Mark tasks complete without evidence.
- Read or expose `.env`.
- Perform destructive Git or Docker operations without explicit owner authorization. This includes reset, clean, rebase, force-push, branch deletion, history rewriting, and volume removal.
- Stage, commit, push, or merge unless the owner explicitly asks.
- Install dependencies, reinstall skills, or modify `.agents/skills/` or `.opencode/agents/` without authorization.
- Create GitHub Issues or publish to an issue tracker unless the owner asks.
- Add new roadmap phases or renumber the existing 12 phases.
- Claim memory, RAG, agents, durable execution, RBAC, audit logging, or SaaS tenancy exists before it is implemented and accepted.

## 10. Current product and technical context

- **Product identity:** All-in-One AI Workspace and Multi-Agent Platform.
- **Approved direction:** workspace/project management, dynamic multi-agent orchestration, personal and project memory, Arabic and English, local-first AI with optional cloud providers, document intelligence and grounded answers, structured extraction with semantic validation, PostgreSQL and proposed pgvector, durable workflows, RBAC, audit logging, human approvals, observability, local development with future self-hosted/SaaS-ready architecture, and a deferred frontend.
- **The 37 approved decisions are recorded in `docs/PROJECT_PLAN.md`.** Read the source note there: the repository did not contain a separate 37-item decision log, so the register is an atomic restatement of the owner-approved brief plus blueprint principles.
- **Open technical questions are listed separately in `docs/PROJECT_PLAN.md`.** TQ-01 to TQ-08 correspond to the Phase 3 draft's D1-D8.
- **Implemented:** FastAPI foundation, PostgreSQL task CRUD, Ollama generation, benchmark subsystem, committed structured-output engine and REST adapter, and owner-accepted CP4 schema registry/service/adapter at e45.
- **CP5 working diff:** `/structured/generate` and deterministic API tests are implemented and independently reviewed, pending owner review; see the checkpoint ledger and QG evidence.
- **Not implemented:** RAG, memory, agent orchestration, durable execution, RBAC, audit logging, human approval enforcement, cost observability, frontend, SaaS tenancy.

## 11. Recommended resume sequence

1. Verify Git state.
2. Read `docs/PROJECT_CHECKPOINTS.md`.
3. Pick the authorized checkpoint.
4. Read its dependencies, files, acceptance criteria, and required tests.
5. Read the actual source and tests.
6. State your plan and file ownership before editing.
7. Implement only the assigned scope.
8. Run the required tests.
9. Record evidence and update the checkpoint.
10. Stop for owner review. Do not commit, push, or merge without explicit approval.

If anything conflicts, prefer the repository file over an agent summary, and prefer a recorded owner decision over an inference.
