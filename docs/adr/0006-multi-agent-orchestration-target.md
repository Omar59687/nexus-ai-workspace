# Dynamic multi-agent orchestration as the target

**Status:** Accepted

The target architecture uses dynamic multi-agent orchestration rather than a fixed single-agent pipeline. The planned logical roles are Supervisor, Document, Data, Research, and Report; they are roles, not a requirement to run five models or processes, may share one local model, and should use deterministic tools for well-defined operations.

## Consequences

- The orchestrator must select roles per task and record the routing decision.
- Agent roles require shared state, permissions, approvals, and observability.
- No agent, orchestrator, or workflow engine exists yet.
- Phase 6 remains gated by the earlier phases and the durable-execution decision.
