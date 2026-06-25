# Research And Design Notes

This document preserves the design context behind the orchestrator/harness
direction. It is intentionally written as long-lived project memory, so future
sessions can recover the reasoning without relying on chat history.

## Core Position

The project is not trying to prove that more agents are always better. The
system should make orchestration accountable before making it powerful.

The project is also not trying to replace software engineering agents such as
Codex, Claude Code, Cline, OpenHands, SWE-agent, Goose, Aider, or OpenCode.
Those systems should be studied as external runtimes that BureauLess can
constrain, audit, and replay.

For v1, BureauLess wraps those agent runtimes from the outside. It does not
enter their internal loops to control every model request, tool call, context
compaction, or token segment. The first useful boundary is assignment to
session to result proposal to ledger decision.

This avoids turning BureauLess into another coding agent. Existing coding
agents already provide filesystem tools, shell execution, patch generation,
context handling, and provider-specific loops. BureauLess should govern their
contracts, workspace boundaries, verification evidence, review gates, and
outcome accounting.

That is also why v1 should not try to normalize every native tool-call format
into one canonical trace schema. Different agents expose different request,
tool, and response shapes; forcing a fake universal trace too early would add
adapter complexity without improving the first useful control boundary.

The default path is `single_agent`. More complex modes, such as DAG workflows,
parallel swarms, advisor review, human gates, and commit gates, must justify
their added coordination cost.

## Agreed Principles

- The orchestrator owns coordination, not execution.
- Worker agents own execution, not global truth.
- The ledger owns shared truth, not private reasoning.
- Not orchestrating is a valid orchestration decision.
- Workflow safety must be enforced by the harness, not remembered by prompts.
- Shared facts must include provenance.
- Agent contexts should stay isolated; broadcasts should be filtered deltas.
- Advisors are lazy, bounded, and budget-gated.
- Tokens are scarce; coordination overhead is a first-class design constraint.
- Long-running work must be replayable from durable events.

## Originality Position

BureauLess does not invent workflow graphs, event sourcing, sandboxed agent
runtimes, provenance, or budget accounting from scratch. Its useful novelty is
the combination and default posture:

- Do not orchestrate unless orchestration has a budget and risk reason.
- Do not trust worker claims unless they become accepted events with provenance.
- Do not broadcast full context when a filtered delta is sufficient.
- Do not escalate models, agents, or advisors without an explicit gate.
- Do not let an agent own mission truth, ledger writes, or completion decisions.
- Do not rebuild agent internals unless a narrow, test-only internal worker is
  explicitly justified later.

This is engineering governance rather than demo-driven autonomy. Its value
becomes visible when tasks are long-running, providers vary, context is costly,
and one uncontrolled worker action could pollute shared state.

## Outcome-First Measurement

The first metrics layer should record whether a bounded assignment was accepted,
which agent/model/provider ran it, how much wall time it used, how many tokens
or dollars were reported, and what artifacts or verification results it
produced.

It should not initially explain why an agent wasted tokens or which internal
tool call caused failure. Native logs can be stored as immutable artifacts for
later analysis, while the canonical metrics stay at session granularity.

## Agent Compatibility Matrix

Before semi-automatic execution, the runtime needs a compatibility view that is
more actionable than raw CLI help text and less policy-heavy than final
dispatch readiness.

The compatibility matrix answers:

- can this agent run non-interactively?
- can the harness override model and provider settings?
- can the harness isolate config?
- can the harness control working directory and capture structured output?
- can timeout and cancellation be enforced from the outside?

This layer should classify agents as `dispatchable`, `limited`, or
`manual_only` based on their observed control surface. It is still not the same
thing as dispatch readiness. Final readiness also depends on workspace
isolation, session behavior, and later policy gates.

## Native Result Extraction Contracts

Session records should say how runtime metrics were obtained, not just what the
final numbers were.

That means the runtime must distinguish at least three cases:

- the agent emitted structured result data and the wrapper extracted it
- the agent completed but did not emit usage or patch metadata
- the wrapper expected structure but failed to extract it cleanly

This distinction matters because `missing` is not one thing. "The agent never
reported token usage" is a different operational fact from "the wrapper broke
while parsing stdout". Those cases should produce different extraction status,
warnings, and confidence levels even if both end with `total_tokens` missing.

For v1, this contract stays at session granularity:

- preserve native stdout/stderr
- extract session-level outcome metrics where possible
- record an explicit extraction contract and status
- avoid pretending we have a canonical cross-agent internal tool trace

This keeps the first useful accounting boundary honest without dragging the
project into premature per-tool-call normalization.

## Session Workspace Isolation

Semi-automatic runtime only becomes trustworthy when assignment execution is
physically separated from canonical mission state.

For v1, the important property is not "perfect sandboxing". It is "a worker
cannot casually mutate the source root that the orchestrator treats as
canonical input state".

That is why the session record should capture:

- source root
- prepared workspace path
- requested isolation mode
- actual isolation mode after fallback
- cleanup policy
- retained paths for logs and audit artifacts

Copy mode is the baseline because it is portable and easy to reason about.
Worktree mode is the preferred git-aware optimization where available, because
it preserves repository structure while still keeping writes off the canonical
working tree.

The runtime should treat fallback as explicit state, not hidden behavior. If a
requested worktree launch falls back to copy mode, the session record should
say so.

## Assignment Lifecycle Replay

Session records alone are not enough for runtime control. The harness also
needs replayable assignment lifecycle facts in the ledger.

For the current runtime boundary, three points matter:

- `assignment_created` prevents duplicate dispatch of the same runnable node
- `worker_timeout`, `assignment_cancelled`, and `assignment_superseded` close
  an attempt as non-completed
- accepted workflow output events, not raw session success, mark an attempt as
  completed

This keeps an important distinction intact: a process can exit successfully
without producing any accepted workflow event. In that case the assignment
attempt is still auditable, but it should not masquerade as completed.

Replay should therefore expose assignment attempts as separate lifecycle state,
while preserving the simpler node state used by the gatekeeper:

- completed if accepted workflow events exist
- blocked if dependencies, gates, or an in-flight assignment block dispatch
- runnable when waits are satisfied and no active assignment remains

## Session-To-Result Packaging

The runtime should not treat a raw session record as interchangeable with a
result proposal.

A session record is execution evidence. A result proposal is an importable
claim. Packaging is the step that turns one into the other.

That boundary matters because packaging is where the runtime can still reject
bad provenance before canonical ledger state is touched.

For v1, packaging should enforce:

- assignment boundary matches between session and assignment packet
- completed-only packaging for import-ready results
- deterministic `result_id` and `source_event` derivation
- artifact hashes verified against actual files at packaging time
- native logs converted into immutable artifact-style refs

If a session says an artifact exists but the file is gone, the runtime should
fail packaging explicitly. It should not silently pass through the stale path
and hope a later import or replay step notices.

## Dispatch Readiness

Compatibility and dispatch readiness should remain separate concepts.

Compatibility answers: what control surface does this agent expose?

Dispatch readiness answers: given this agent and this workspace policy, may the
runtime launch it automatically right now?

That distinction matters because an agent can be partially usable in a manual
path while still being below the bar for automatic launch.

For the current runtime line, the readiness states are:

- `dispatchable`: compatibility is strong enough and the requested workspace
  isolation mode is currently satisfiable
- `manual_only`: the workspace is fine, but the agent control surface is below
  the automatic-launch threshold
- `blocked`: the requested launch policy cannot be satisfied in the current
  environment, for example because the workspace root is missing or worktree
  isolation is unavailable

This keeps "agent weakness" and "environmental launch failure" distinct in a
machine-readable way. That distinction is useful for both policy code and
workbench messaging.

## Observed Budget Activation

Budget policy should stop pretending that every decision is first-run
estimation forever.

Once stable session metrics exist, pre-dispatch policy should use observed
runtime evidence alongside configured limits:

- cumulative observed token usage
- cumulative known cost usage
- missing-usage and missing-cost counts
- observed coordination ratio across prior workflow modes

This does not replace prediction. It constrains prediction.

The runtime still needs projected tokens, projected cost, and projected
coordination ratio for the proposed dispatch. But those projections should be
checked against mission budget in the context of what has already been spent.

Workflow selection should also remain conservative:

- reject or simplify over-orchestrated plans such as unjustified
  `parallel_swarm`
- raise the floor when a proposed `single_agent` path violates review/risk
  requirements
- stop automatic dispatch entirely when hard budget conditions or human-stop
  rules trigger

That gives the system a concrete pre-dispatch control point instead of leaving
budget and workflow policy as passive documentation.

## Runtime Field Notes Template

When studying external agent products or frameworks, record boundary behavior
rather than personality or marketing claims:

```yaml
agent: openhands
type: software_engineering_runtime
strengths:
  - sandboxed execution
  - lifecycle control
  - runtime abstraction
risks:
  - heavy runtime dependency
  - may duplicate BureauLess orchestration
adapter_takeaways:
  - useful as managed external executor
  - should not own ledger or workflow selection
bureauless_boundary:
  allowed:
    - execute assignment
    - produce artifacts
    - report result
  forbidden:
    - update canonical ledger
    - spawn uncontrolled agents
    - decide mission completion
```

For each runtime, ask: what does it teach BureauLess about controlling agents,
and which capabilities must be kept behind harness rules?

## Blackboard Architecture

Blackboard architecture is the closest conceptual match for the intended shared
workspace. Agents contribute observations to a shared board, while a controller
or policy decides what becomes canonical and who should act next.

For this project, the shared board should not be a raw group chat. It should be
a governed mission ledger:

- Raw worker thoughts stay private.
- Worker reports are structured.
- Public findings require provenance.
- The orchestrator approves facts; the harness validates and writes canonical state.
- Other agents receive role-filtered broadcast views.

Useful reference:

- [Exploring Advanced LLM Multi-Agent Systems Based on Blackboard Architecture](https://arxiv.org/abs/2507.01701)

## AutoGen SelectorGroupChat

AutoGen `SelectorGroupChat` implements a team where participants broadcast
messages to all members, and a model selects the next speaker from the shared
context.

Useful idea:

- Broadcasts can coordinate specialist agents.
- A model can select the next actor based on roles and current context.

Risk for this project:

- Full shared context grows quickly.
- Every agent seeing everything can pollute local reasoning.
- The project should prefer filtered broadcasts over full conversation history.

Reference:

- [AutoGen SelectorGroupChat](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/selector-group-chat.html)

## AutoGen Swarm

AutoGen `Swarm` supports handoff between agents based on capability. Agents can
delegate to one another and operate over a shared message context.

Useful idea:

- Handoff is a strong pattern for local ownership transfer.
- Workers can decide when a different specialist should continue.

Risk for this project:

- A decentralized handoff system can weaken global control.
- Shared message context is not enough for long-running auditability.
- The orchestrator should remain the owner of canonical mission state.

Reference:

- [AutoGen Swarm](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/swarm.html)

## AutoGen GraphFlow

AutoGen `GraphFlow` uses directed graph execution to control how agents interact.
It supports sequential chains, parallel fan-out, conditional branching, loops,
and joins.

Useful idea:

- Complex coordination should be represented as executable structure.
- Join conditions should be explicit.
- Workflows should be observable and debuggable.

Design consequence:

- A committer must not run because a prompt says "wait for review".
- A committer should run only when the runtime sees both `patch_ready` and
  `review_approved` events.

Reference:

- [AutoGen GraphFlow](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/graph-flow.html)

## Magentic-One

Magentic-One uses an orchestrator that plans, delegates tasks, tracks progress,
and revises the plan as needed.

Useful idea:

- The orchestrator is a control plane.
- Specialist agents can be modular and replaceable.
- Planning and progress tracking should stay centralized.

Risk for this project:

- If the orchestrator also executes, role boundaries blur.
- The orchestrator should not become "the strongest worker".

Reference:

- [AutoGen Magentic-One](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/magentic-one.html)
- [Magentic-One paper](https://arxiv.org/abs/2411.04468)

## LangGraph

LangGraph models workflows as graphs with shared state, nodes, and edges. It
also supports persistence, parallel super-steps, and state channels.

Useful idea:

- Runtime state should be explicit.
- Nodes do work; edges decide what can happen next.
- Persistence and replay are runtime responsibilities.

Design consequence:

- The harness should compile and execute structured workflow state.
- Private worker context and public mission state should be separate channels.

References:

- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

## Deep Agents

Deep Agents emphasizes task planning, subagents, isolated context windows,
context offloading, file systems, and human-in-the-loop steering.

Useful idea:

- Heavy subtasks should run in isolated contexts.
- Subagents should return compact results instead of leaking full history.
- Context management is a core harness capability, not a nice-to-have.

Design consequence:

- Worker private scratchpads should not enter the public ledger by default.
- Large tool outputs should become artifact references plus summaries.

Reference:

- [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview)

## Temporal

Temporal is not an LLM framework, but its workflow model is valuable for long
tasks: durable execution, event history, signals, replay, retries, and recovery.

Useful idea:

- Long tasks need durable event history.
- Resume and replay should be designed from the start.
- External signals, including human approval, should be part of workflow state.

Design consequence:

- The mission ledger should be append-only at the event layer.
- Current mission state should be rebuildable from the event log.

Reference:

- [Temporal Workflow Execution](https://docs.temporal.io/workflow-execution)

## Counterpressure Against Over-Orchestration

Recent research argues that for fixed procedural tasks, external orchestration
can underperform a strong model following the full procedure in context.

This project should treat that as a useful warning:

- Do not use many agents by default.
- Do not summon advisors for low-risk work.
- Do not parallelize unless there is clear value.
- Let the orchestrator choose `single_agent` when that is enough.

References:

- [In-Context Prompting Obsoletes Agent Orchestration for Procedural Tasks](https://arxiv.org/abs/2604.27891)
- [Compiling Agentic Workflows into LLM Weights](https://arxiv.org/abs/2605.22502)

## Design North Star

The system should be a small, disciplined engineering team:

- One control-plane orchestrator.
- Bounded worker agents.
- Lazy advisors.
- Deterministic runtime enforcement.
- Durable evidence.
- Clear budget accounting.

The goal is not "more agents". The goal is better delegation with visible cost,
visible risk, and recoverable state.
