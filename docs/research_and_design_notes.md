# Research And Design Notes

This document preserves the design context behind the orchestrator/harness
direction. It is intentionally written as long-lived project memory, so future
sessions can recover the reasoning without relying on chat history.

## Core Position

The project is not trying to prove that more agents are always better. The
system should make orchestration accountable before making it powerful.

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

## Blackboard Architecture

Blackboard architecture is the closest conceptual match for the intended shared
workspace. Agents contribute observations to a shared board, while a controller
or policy decides what becomes canonical and who should act next.

For this project, the shared board should not be a raw group chat. It should be
a governed mission ledger:

- Raw worker thoughts stay private.
- Worker reports are structured.
- Public findings require provenance.
- The orchestrator or harness accepts facts into canonical state.
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

