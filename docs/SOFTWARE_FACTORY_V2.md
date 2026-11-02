# Nexus AI Software Factory V2

## Purpose and current status

Factory V2 is a configurable OpenCode workflow for bounded, independently reviewed engineering tasks. It does not run autonomously against Nexus AI application features merely because the profiles exist; the user activates the primary orchestrator for a task. The orchestrator plans the task, chooses the smallest suitable team, assigns non-overlapping ownership, and coordinates one independent reviewer for every implementation agent.

Profiles are project-scoped under `.opencode/agents/`. The six existing V1 profiles (`impl-core`, `impl-tests`, `impl-adapter`, `review-core`, `review-tests`, `review-adapter`) are retained unchanged as legacy profiles. Factory V2 uses separate `factory-v2-*` names.

## Hierarchy and limits

- One permanent primary: `factory-v2-orchestrator`.
- One to five implementation subagents, selected per task.
- Exactly one reviewer per implementer, reviewing only that implementer's assignment.
- At most two formal review passes per implementation/reviewer pair.
- Human approval is required before any commit or merge.

The five profiles are capacity slots, not a requirement to launch five agents. Small, independent tasks should use one pair; more agents are appropriate only when work can be partitioned into independent, non-overlapping ownership. Dependencies are sequenced. If overlapping files cannot be isolated with a verified, safe worktree mechanism, the assignments run sequentially.

## Model registry and reasoning controls

The installed runtime checked for this configuration was OpenCode **1.18.34**. `opencode models` reported the following active IDs used by V2:

| Profile slot | Requested model | Reviewer model | Requested reasoning |
|---|---|---|---|
| Orchestrator | `opencode/glm-5.3-flash-free` | — | `high` (model lists a `high` variant) |
| Implementer 1 | `opencode/glm-5.3-flash-free` | Reviewer 1: `opencode/deepseek-v4.1-flash-free` | Both list `high`; requested `high` |
| Implementer 2 | `opencode/deepseek-v4.1-flash-free` | Reviewer 2: `opencode/glm-5.3-flash-free` | Both list `high`; requested `high` |
| Implementer 3 | `opencode/mimo-v2.6-flash-free` | Reviewer 3: `opencode/nemotron-3.5-lightning-free` | No named variants shown by model metadata; no level claimed/configured |
| Implementer 4 | `opencode/nemotron-3.5-lightning-free` | Reviewer 4: `opencode/mimo-v2.6-flash-free` | No named variants shown by model metadata; no level claimed/configured |
| Implementer 5 | `opencode/glm-5.3-flash-free` | Reviewer 5: `opencode/deepseek-v4.1-flash-free` | Both list `high`; requested `high` |

The pairings use different configured model IDs for each implementer/reviewer pair. `opencode models <provider> --verbose` exposes model capabilities and variants. GLM and DeepSeek explicitly list `high`; MiMo and Nemotron Lightning expose a reasoning capability but list no named variants, so the profiles do not claim a particular effort setting. If model metadata changes, re-check it before allocation.

OpenCode reported the exact Luna identifier `openai/gpt-6-luna` and a `medium` reasoning variant. No V2 profile selects it. Per the usage restriction, Luna is optional for a human-invoked external audit only; do not use other OpenAI models.

These are configured/requested identities. A selected profile and `opencode models` output do not by themselves prove which model served a particular child session. The orchestrator must report actual identity only when the session/runtime exposes evidence; otherwise mark it unverified. Never silently substitute a model.

For this Factory V2 build session, the host identifies the active primary model as `openai/gpt-6-luna`, not the configured GLM orchestrator profile. The active Luna reasoning variant is not exposed to this harness, so compliance with Luna's MEDIUM-only restriction cannot be verified for this session. The GLM profile is configured for future sessions, but must be selected in a runtime that actually reports GLM before claiming the permanent GLM primary is active.

## Profiles and permissions

| Profile | Mode | Model | Responsibilities and permission boundary |
|---|---|---|---|
| `factory-v2-orchestrator` | primary | GLM 5.3 Flash Free | Plans, selects slots, delegates, integrates and reports. Task permission allows only the ten V2 slot names. Edits and shell commands require permission. |
| `factory-v2-impl-1` | subagent | GLM 5.3 Flash Free | Implements only the paths and contract assigned for this invocation. |
| `factory-v2-impl-2` | subagent | DeepSeek V4.1 Flash Free | Same implementation constraints. |
| `factory-v2-impl-3` | subagent | MiMo V2.6 Flash Free | Same implementation constraints. |
| `factory-v2-impl-4` | subagent | Nemotron 3.5 Lightning Free | Same implementation constraints. |
| `factory-v2-impl-5` | subagent | GLM 5.3 Flash Free | Same implementation constraints. |
| `factory-v2-review-1` | subagent | DeepSeek V4.1 Flash Free | Reviews only implementation slot 1. Edit/write/patch denied; shell is limited to read/status/diff/log and test/compile commands. |
| `factory-v2-review-2` | subagent | GLM 5.3 Flash Free | Reviews only implementation slot 2; same read-only boundary. |
| `factory-v2-review-3` | subagent | Nemotron 3.5 Lightning Free | Reviews only implementation slot 3; same read-only boundary. |
| `factory-v2-review-4` | subagent | MiMo V2.6 Flash Free | Reviews only implementation slot 4; same read-only boundary. |
| `factory-v2-review-5` | subagent | DeepSeek V4.1 Flash Free | Reviews only implementation slot 5; same read-only boundary. |

Implementation profiles use `edit: ask` and `bash: ask`; the owning task's exact file list and contract must be stated by the orchestrator before launch. They must stop on ownership/dependency conflicts rather than editing outside their assignment. Reviewers have edit, write, and patch denied, cannot invoke child tasks, and have shell denied except specific read-only Git inspection and test/compile command patterns. No reviewer receives Git mutation permissions.

The orchestrator's task permissions explicitly allow only `factory-v2-impl-*` and `factory-v2-review-*`. Human approval remains required for permission prompts and for any eventual commit or merge.

## Dynamic allocation protocol

Before launching agents, the orchestrator records:

1. Task objective and acceptance criteria.
2. Repository branch, HEAD, working-tree state, user-change ownership, and constraints.
3. Independent workstreams and dependencies.
4. Exact file ownership for each implementer (no concurrent overlap).
5. The corresponding reviewer, verified model ID, reasoning setting if the model exposes one, and required tests.

Choose the smallest team that provides genuinely independent units of work. Each implementer receives only its assignment, shared interface/acceptance contract, permitted files, and relevant constraints. The matching reviewer receives the original objective and acceptance criteria and independently inspects the actual diff, source, surrounding code, and tests. An implementer's report is context, never review evidence by itself.

If repository state is unexpected or user work cannot be safely preserved, stop before implementation. Never inspect `.env`. Never stage, commit, push, merge, rebase, reset, clean, discard, or switch branches.

## Bounded review and repair state machine

The state machine applies independently to each implementation/reviewer pair:

1. **Review cycle 1:** reviewer produces finding IDs, severity, exact file/line, evidence, risk, required correction, and suggested regression test. A clean review states inspected files and tests actually run.
2. **Repair cycle 1:** if confirmed defects exist, the same implementation owner makes corrections and reports exact changes/tests.
3. **Review cycle 2:** the same reviewer independently checks every prior finding and new material regressions from the repair.
4. **Repair cycle 2:** if needed, the same owner may make one final repair. No third formal review pass is allowed.
5. **Disposition:** unresolved Critical or High => REJECT; unresolved Medium => HUMAN DECISION; Low and Informational => document and classify. Present evidence for reviewer disagreements. Critical/High findings cannot be overridden without concrete evidence and human escalation.

Tests passing do not substitute for adversarial review. Corrections cannot weaken the acceptance criteria. The two review passes are a hard maximum, not a target.

## Integration, authorization, and observability

After pairs reach an acceptable disposition, the orchestrator inspects all accepted diffs, checks cross-assignment interfaces and ownership, runs focused tests and appropriate full regression, compile/dependency/migration checks, and verifies final diff and status. Only approved files may be integrated. No automatic commit, push, merge, rebase, reset, clean, discard, or branch switch is permitted. Human approval is required before committing or merging.

Each execution report contains task ID/objective, orchestrator identity, launched agents and requested/actual model identity when exposed, ownership mapping, review passes used, findings by severity, corrections, unresolved findings, conflicts, tests/results, wall duration and token/usage only if actually exposed, final ACCEPT/REJECT/HUMAN DECISION, and final Git status. Do not invent metrics or claim speedups without a comparable baseline.

## OpenCode limitations and smoke-test evidence

Configuration format: project Markdown agent profiles under `.opencode/agents/`, with YAML frontmatter fields for `description`, `mode`, `model`, `permission`, plus model-specific `reasoningEffort` passed through as an agent option. Project `opencode.json` was absent. The user-level `opencode.jsonc` was inspected and contains only the `$schema` declaration; it was not modified.

Available evidence from this setup:

- `opencode --version`: `1.18.34`.
- `opencode models`: exact configured OpenCode IDs listed above are present; verbose metadata confirms named `high` variants only for GLM and DeepSeek among the configured free models.
- `openai/gpt-6-luna` and its `medium` variant are present in verbose model metadata; no Luna profile is configured or invoked.
- This documentation/build session reports actual primary `openai/gpt-6-luna`; its reasoning setting is unknown. The configured Factory orchestrator profile requests GLM and was not the active model in this session.
- Existing V1 profiles were present before V2 files were added and are preserved unchanged.
- Native Task invocation smoke test: **BLOCKED** in the current orchestration harness. The Task tool exposed only `explore` and `general`; invoking a custom profile name returned `Unknown agent type: impl-core is not a valid agent type`. The harness does not expose a way to invoke `factory-v2-review-1` natively or verify child-session model identity. The installed CLI can enumerate profiles, but Factory V2 deliberately does not use `opencode run --agent` as a fallback. Therefore this setup has not demonstrated native custom-profile invocation, child model identity, or zero fallback. Do not mark these checks passed until run from an OpenCode primary session whose native Task tool exposes the custom profiles and whose child-session evidence confirms the configured reviewer model.

The profiles provide configuration for the bounded loop; they do not implement an independent durable workflow engine or guarantee runtime enforcement of review counts. The primary orchestrator prompt encodes the state machine, and execution evidence must be reported for each task.

## Activate Factory V2 in VS Code

1. Open the repository folder in VS Code with the OpenCode extension/runtime connected to this project.
2. Reload the OpenCode session after profile changes if the running session does not reload project agents automatically.
3. Select `factory-v2-orchestrator` as the **primary** agent (use the agent selector/Tab cycle or the extension's agent picker).
4. Start a task with its objective and acceptance criteria. The orchestrator will inspect repository state and state its proposed allocation before native Task delegation.
5. Review the final engineering report. Approve separately before any commit or merge.

If `factory-v2-orchestrator` is not selectable, or custom profiles are absent from the native Task tool, stop and resolve/reload the OpenCode session. Do not invoke subagents through `opencode run --agent`.
