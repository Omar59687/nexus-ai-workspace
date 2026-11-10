# Durable workflow engine selection deferred

**Status:** Proposed

No durable workflow engine has been selected. The product requires durable execution, resumable state, bounded retries, and human approval waits, but the choice between a graph-based engine, a database-backed state machine, and a queue/worker design depends on Phase 6 orchestration and Phase 9 background-processing evidence.

## Considered options

- LangGraph checkpoints.
- A database-backed workflow state machine.
- A queue and worker system introduced only when load requires it.

## Consequences

- No workflow is durable today; do not claim durable execution.
- Orchestration design must keep state persistence and idempotency in scope.
- The engine decision requires an ADR, an owner decision, and integration evidence.
