# Agent Swarm Task Protocol

This protocol is the contract between an orchestrator and execution agents.

## DAG Document

```yaml
schema_version: "0.1"
project: example-project
default_review_model: gpt-5
nodes: []
```

YAML is the preferred hand-authored format because task nodes contain long
natural-language fields. DAG documents and run records both use YAML.

## Node Fields

Required fields:

- `id`: Stable node identifier.
- `title`: Human-readable task name.
- `goal`: The desired outcome.
- `dependencies`: Node ids that must pass their review gate first.
- `target_files`: Files or directories the agent is expected to touch.
- `allowed_models`: Models that may execute the task.
- `recommended_model`: Default execution model.
- `risk_level`: `low`, `medium`, or `high`.
- `review_gate`: `auto_pass`, `orchestrator_review`, or `human_review`.
- `acceptance_criteria`: Observable completion criteria.
- `verification_commands`: Commands the executor should run.
- `do_not`: Explicit boundaries.
- `prompt_template`: Instruction template for the executor.
- `failure_policy`: What to do when execution fails.

Optional fields:

- `context_files`: Files the executor should read first.
- `outputs`: Expected artifacts such as commits, notes, or reports.
- `tags`: Scheduling hints such as `mini-safe`, `large-first`, or `docs`.

## Review Gate Semantics

- `auto_pass`: A successful run makes dependents ready.
- `orchestrator_review`: A successful run must be reviewed by the orchestrator.
- `human_review`: A successful run must be reviewed by a human.

Downstream nodes should only become ready after the dependency has a passing run
and the required review status is satisfied.

## Failure Policy

Recommended values:

- `retry_same_model`: Retry once with the same model.
- `escalate_to_large_model`: Re-run using the review or orchestrator model.
- `send_to_human`: Stop and ask for human judgment.
- `split_task_further`: The node is too broad and should be decomposed.

## Run Records

Execution records are also stored as YAML documents in `runs/`. They are
machine-written artifacts, but they follow the same single-format rule as the
task graph itself.
