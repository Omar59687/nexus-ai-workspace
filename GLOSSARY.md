# Nexus AI

Nexus AI is a local-first AI workspace and multi-agent platform. This glossary defines the project's canonical language so plans, code, tests, and future sessions use the same terms.

Definitions describe concepts, not implementation status. A term may be defined here before its capability exists. See `docs/PROJECT_CHECKPOINTS.md` for what is implemented, verified, or accepted.

## Language

### Work and product

**Workspace**:
A top-level container that groups projects, members, settings, and shared resources.
_Avoid_: account, tenant, organization

**Project**:
A scoped body of work inside a workspace, containing its own documents, memory, agents, and workflows.
_Avoid_: folder, task

**Workspace Task**:
A persisted unit of work in the current `workspace_tasks` table, with a title, status, and creation time.
_Avoid_: job, ticket, checkpoint

**Document Intelligence**:
The capability to parse, index, retrieve, and reason over documents with evidence.
_Avoid_: document AI, file search

**Grounded Answer**:
An answer whose claims are supported by cited retrieved evidence; grounded does not mean guaranteed true.
_Avoid_: verified answer, factual answer

### Agents and orchestration

**Agent**:
A logical role with instructions, tools, memory access, and model access; it is not necessarily a separate model or process.
_Avoid_: bot, worker, LLM

**Orchestrator**:
The component that selects agents, routes work, manages shared state, and enforces approvals.
_Avoid_: supervisor process, controller

**Workflow**:
An ordered or branching set of steps that accomplishes a user goal and carries state between steps.
_Avoid_: pipeline, job

**Durable Execution**:
Execution in which workflow state is persisted so work can survive restarts and resume after failure.
_Avoid_: long-running request, background task

**Checkpoint (project)**:
A tracked unit of work with an ID, acceptance criteria, evidence, review status, and next action in the project checkpoint ledger.
_Avoid_: milestone, task

**Workflow Checkpoint**:
A persisted snapshot of workflow state used for durable execution and resumption.
_Avoid_: save point, project checkpoint

**Human-in-the-loop**:
A deliberate pause in an automated flow that requires an authorized human decision before continuing.
_Avoid_: manual step, approval

**Retry Policy**:
A rule set that defines which failures are retryable, the maximum attempts, and any backoff or escalation behavior.
_Avoid_: retry loop, infinite retry

### Models and structured data

**Model Adapter**:
A provider-specific implementation of the model interface that translates requests, responses, errors, and usage metadata.
_Avoid_: wrapper, client

**Provider Abstraction**:
One interface that lets local and optional cloud model providers be used without leaking provider-specific behavior into application logic.
_Avoid_: SDK, vendor lock-in layer

**Schema Registry**:
A named catalog that maps a schema name to its model, validator, and default prompt.
_Avoid_: schema list, model map

**Structured Output**:
Model output constrained to a declared schema; schema validity proves structure only, not factual correctness.
_Avoid_: JSON output, formatted answer

**Semantic Validation**:
Domain-rule validation applied after structural validation; it can reject well-formed but inappropriate values, but still does not prove truth.
_Avoid_: schema validation, fact checking

### Documents and memory

**RAG**:
Retrieval-Augmented Generation: retrieve relevant evidence first, then generate an answer conditioned on that evidence.
_Avoid_: search, retrieval

**Embeddings**:
Numeric vector representations of content used for semantic similarity and retrieval.
_Avoid_: vectors, encodings

**Vector Search**:
Similarity search over embeddings to find semantically related content.
_Avoid_: semantic search, similarity lookup

**Personal Memory**:
Memory scoped to one user, with its own retention, deletion, and access rules.
_Avoid_: user context, profile

**Project Memory**:
Memory scoped to one project and shared only with users who can access that project.
_Avoid_: team memory, shared context

### Security and operations

**Audit Log**:
An append-only record of security-relevant actions, actors, targets, outcomes, and timestamps, separate from performance logging.
_Avoid_: application log, event log

**Role-Based Access Control (RBAC)**:
An authorization model in which permissions are granted through roles rather than per-user ad hoc rules.
_Avoid_: permissions list, ACL

**Observability**:
The ability to inspect measured tokens, latency, resource use, cost, and errors for a request or workflow.
_Avoid_: monitoring, telemetry

**Checkpoint**:
The unqualified term is ambiguous in this project. Use **Checkpoint (project)** or **Workflow Checkpoint** explicitly.
_Avoid_: bare "checkpoint" in a context where either meaning is possible
