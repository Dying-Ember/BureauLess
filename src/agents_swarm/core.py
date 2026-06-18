from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from string import Template
from typing import Any
from uuid import uuid4

import yaml


VALID_RISK_LEVELS = {"low", "medium", "high"}
VALID_REVIEW_GATES = {"auto_pass", "orchestrator_review", "human_review"}
VALID_FAILURE_POLICIES = {
    "retry_same_model",
    "escalate_to_large_model",
    "send_to_human",
    "split_task_further",
}
PASSING_STATUSES = {"passed"}
SATISFIED_REVIEW = {
    "auto_pass": {"not_required", "approved"},
    "orchestrator_review": {"orchestrator_approved"},
    "human_review": {"human_approved"},
}
VALID_REVIEW_STATUSES = {
    "pending",
    "not_required",
    "approved",
    "orchestrator_approved",
    "human_approved",
    "rejected",
}


class ProtocolError(ValueError):
    """Raised when a DAG document or run record is invalid."""


@dataclass(frozen=True)
class TaskNode:
    id: str
    title: str
    goal: str
    dependencies: list[str]
    target_files: list[str]
    context_files: list[str]
    allowed_models: list[str]
    recommended_model: str
    risk_level: str
    review_gate: str
    acceptance_criteria: list[str]
    verification_commands: list[str]
    do_not: list[str]
    prompt_template: str
    failure_policy: str
    outputs: list[str]
    tags: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskNode":
        required = {
            "id",
            "title",
            "goal",
            "dependencies",
            "target_files",
            "allowed_models",
            "recommended_model",
            "risk_level",
            "review_gate",
            "acceptance_criteria",
            "verification_commands",
            "do_not",
            "prompt_template",
            "failure_policy",
        }
        missing = sorted(required - data.keys())
        if missing:
            raise ProtocolError(f"Task node is missing required fields: {', '.join(missing)}")

        node = cls(
            id=_as_string(data, "id"),
            title=_as_string(data, "title"),
            goal=_as_string(data, "goal"),
            dependencies=_as_string_list(data, "dependencies"),
            target_files=_as_string_list(data, "target_files"),
            context_files=_as_string_list(data, "context_files", default=[]),
            allowed_models=_as_string_list(data, "allowed_models"),
            recommended_model=_as_string(data, "recommended_model"),
            risk_level=_as_string(data, "risk_level"),
            review_gate=_as_string(data, "review_gate"),
            acceptance_criteria=_as_string_list(data, "acceptance_criteria"),
            verification_commands=_as_string_list(data, "verification_commands"),
            do_not=_as_string_list(data, "do_not"),
            prompt_template=_as_string(data, "prompt_template"),
            failure_policy=_as_string(data, "failure_policy"),
            outputs=_as_string_list(data, "outputs", default=[]),
            tags=_as_string_list(data, "tags", default=[]),
        )
        node.validate()
        return node

    def validate(self) -> None:
        if not self.id.strip():
            raise ProtocolError("Task id cannot be empty")
        if self.risk_level not in VALID_RISK_LEVELS:
            raise ProtocolError(f"{self.id}: invalid risk_level {self.risk_level!r}")
        if self.review_gate not in VALID_REVIEW_GATES:
            raise ProtocolError(f"{self.id}: invalid review_gate {self.review_gate!r}")
        if self.failure_policy not in VALID_FAILURE_POLICIES:
            raise ProtocolError(f"{self.id}: invalid failure_policy {self.failure_policy!r}")
        if self.recommended_model not in self.allowed_models:
            raise ProtocolError(
                f"{self.id}: recommended_model must be included in allowed_models"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "goal": self.goal,
            "dependencies": self.dependencies,
            "target_files": self.target_files,
            "context_files": self.context_files,
            "allowed_models": self.allowed_models,
            "recommended_model": self.recommended_model,
            "risk_level": self.risk_level,
            "review_gate": self.review_gate,
            "acceptance_criteria": self.acceptance_criteria,
            "verification_commands": self.verification_commands,
            "do_not": self.do_not,
            "prompt_template": self.prompt_template,
            "failure_policy": self.failure_policy,
            "outputs": self.outputs,
            "tags": self.tags,
        }


@dataclass(frozen=True)
class Dag:
    schema_version: str
    project: str
    default_review_model: str
    nodes: dict[str, TaskNode]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Dag":
        raw_nodes = data.get("nodes")
        if not isinstance(raw_nodes, list):
            raise ProtocolError("DAG field 'nodes' must be a list")

        nodes: dict[str, TaskNode] = {}
        for raw_node in raw_nodes:
            if not isinstance(raw_node, dict):
                raise ProtocolError("Each DAG node must be an object")
            node = TaskNode.from_dict(raw_node)
            if node.id in nodes:
                raise ProtocolError(f"Duplicate node id: {node.id}")
            nodes[node.id] = node

        dag = cls(
            schema_version=_as_string(data, "schema_version"),
            project=_as_string(data, "project"),
            default_review_model=_as_string(data, "default_review_model"),
            nodes=nodes,
        )
        dag.validate()
        return dag

    def validate(self) -> None:
        for node in self.nodes.values():
            for dependency in node.dependencies:
                if dependency not in self.nodes:
                    raise ProtocolError(f"{node.id}: unknown dependency {dependency!r}")
        self._assert_acyclic()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project": self.project,
            "default_review_model": self.default_review_model,
            "nodes": [node.to_dict() for node in self.nodes.values()],
        }

    def _assert_acyclic(self) -> None:
        temporary: set[str] = set()
        permanent: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in permanent:
                return
            if node_id in temporary:
                raise ProtocolError(f"Cycle detected at node {node_id}")
            temporary.add(node_id)
            for dependency in self.nodes[node_id].dependencies:
                visit(dependency)
            temporary.remove(node_id)
            permanent.add(node_id)

        for node_id in self.nodes:
            visit(node_id)


def load_dag(path: Path) -> Dag:
    with path.open("r", encoding="utf-8") as handle:
        if path.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(handle)
        else:
            data = json.load(handle)
    if not isinstance(data, dict):
        raise ProtocolError("DAG document must be an object")
    return Dag.from_dict(data)


def write_dag_json(dag: Dag, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(dag.to_dict(), handle, indent=2)
        handle.write("\n")
    return path


def dag_documents_match(left_path: Path, right_path: Path) -> bool:
    return load_dag(left_path).to_dict() == load_dag(right_path).to_dict()


def load_run_records(runs_dir: Path) -> list[dict[str, Any]]:
    if not runs_dir.exists():
        return []
    records = []
    for path in sorted(runs_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as handle:
            record = json.load(handle)
        if isinstance(record, dict):
            records.append(record)
    return records


def ready_nodes(dag: Dag, records: list[dict[str, Any]]) -> list[TaskNode]:
    completed = _completed_node_ids(dag, records)
    attempted = {record.get("task_id") for record in records if record.get("status") == "passed"}
    ready = []
    for node in dag.nodes.values():
        if node.id in attempted:
            continue
        if all(dependency in completed for dependency in node.dependencies):
            ready.append(node)
    return ready


def render_prompt(dag: Dag, node_id: str) -> str:
    node = _node_or_error(dag, node_id)
    context = {
        "id": node.id,
        "title": node.title,
        "goal": node.goal,
        "recommended_model": node.recommended_model,
        "allowed_models": ", ".join(node.allowed_models),
        "risk_level": node.risk_level,
        "review_gate": node.review_gate,
        "failure_policy": node.failure_policy,
        "dependencies": _lines(node.dependencies),
        "target_files": _lines(node.target_files),
        "context_files": _lines(node.context_files),
        "acceptance_criteria": _lines(node.acceptance_criteria),
        "verification_commands": _lines(node.verification_commands),
        "do_not": _lines(node.do_not),
        "outputs": _lines(node.outputs),
        "tags": ", ".join(node.tags),
    }
    body = Template(node.prompt_template).safe_substitute(context)
    return "\n".join(
        [
            f"# Task {node.id}: {node.title}",
            "",
            f"Recommended model: {node.recommended_model}",
            f"Allowed models: {context['allowed_models']}",
            f"Risk level: {node.risk_level}",
            f"Review gate: {node.review_gate}",
            f"Failure policy: {node.failure_policy}",
            "",
            "## Goal",
            node.goal,
            "",
            "## Dependencies",
            context["dependencies"],
            "",
            "## Target Files",
            context["target_files"],
            "",
            "## Context Files",
            context["context_files"],
            "",
            "## Acceptance Criteria",
            context["acceptance_criteria"],
            "",
            "## Verification Commands",
            context["verification_commands"],
            "",
            "## Do Not",
            context["do_not"],
            "",
            "## Instructions",
            body,
        ]
    )


def create_run_record(
    dag: Dag,
    task_id: str,
    model: str,
    status: str,
    input_commit: str | None = None,
    output_commit: str | None = None,
    changed_files: list[str] | None = None,
    verification_result: str | None = None,
    review_status: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    node = _node_or_error(dag, task_id)
    if model not in node.allowed_models:
        raise ProtocolError(f"{task_id}: model {model!r} is not allowed for this node")
    if review_status is None:
        review_status = "not_required" if node.review_gate == "auto_pass" else "pending"

    now = datetime.now(timezone.utc).isoformat()
    return {
        "run_id": str(uuid4()),
        "task_id": task_id,
        "model": model,
        "status": status,
        "started_at": now,
        "finished_at": now,
        "input_commit": input_commit,
        "output_commit": output_commit,
        "changed_files": changed_files or [],
        "verification_result": verification_result,
        "review_status": review_status,
        "notes": notes,
    }


def write_run_record(runs_dir: Path, record: dict[str, Any]) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{record['task_id']}-{record['run_id']}.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def update_review_status(
    dag: Dag,
    runs_dir: Path,
    task_id: str,
    review_status: str,
    run_id: str | None = None,
) -> Path:
    _node_or_error(dag, task_id)
    if review_status not in VALID_REVIEW_STATUSES:
        raise ProtocolError(f"Invalid review_status: {review_status}")

    matches = []
    for path in sorted(runs_dir.glob(f"{task_id}-*.json")):
        with path.open("r", encoding="utf-8") as handle:
            record = json.load(handle)
        if not isinstance(record, dict):
            continue
        if run_id is not None and record.get("run_id") != run_id:
            continue
        matches.append((path, record))

    if not matches:
        suffix = f" with run_id {run_id}" if run_id else ""
        raise ProtocolError(f"No run record found for {task_id}{suffix}")

    path, record = matches[-1]
    record["review_status"] = review_status
    record["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def _completed_node_ids(dag: Dag, records: list[dict[str, Any]]) -> set[str]:
    completed: set[str] = set()
    for record in records:
        task_id = record.get("task_id")
        if task_id not in dag.nodes or record.get("status") not in PASSING_STATUSES:
            continue
        node = dag.nodes[task_id]
        review_status = record.get("review_status")
        if review_status in SATISFIED_REVIEW[node.review_gate]:
            completed.add(task_id)
    return completed


def _node_or_error(dag: Dag, node_id: str) -> TaskNode:
    try:
        return dag.nodes[node_id]
    except KeyError as exc:
        raise ProtocolError(f"Unknown node id: {node_id}") from exc


def _as_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ProtocolError(f"Field {key!r} must be a string")
    return value


def _as_string_list(
    data: dict[str, Any],
    key: str,
    default: list[str] | None = None,
) -> list[str]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProtocolError(f"Field {key!r} must be a list of strings")
    return value


def _lines(items: list[str]) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- {item}" for item in items)
