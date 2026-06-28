from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import yaml

from ..agents import doctor_agent, list_agent_specs
from ..cli.main import prepare_demo_workspace
from ..core import (
    Dag,
    ProtocolError,
    create_node,
    load_dag,
    load_run_records,
    ready_nodes,
    render_prompt,
    update_node_dependencies,
    update_node_metadata,
    update_review_status,
)
from ..protocol import (
    append_ledger_event,
    export_assignment,
    import_result_proposal,
    load_ledger,
    load_mission,
    load_workflow,
    materialize_current_workflow,
    write_ledger,
)
from ..runtime import (
    build_mutation_supersession_events,
    evaluate_assignment_impacts,
    evaluate_gatekeeper,
    replay_workflow,
    summarize_metrics,
)
from ..runtime.sessions import (
    build_assignment_created_event,
    create_session_spec,
    package_session_result,
    run_session,
)


NodeState = Literal["ready", "blocked", "completed", "needs_review"]


class ReviewRequest(BaseModel):
    dag_path: str
    runs_dir: str = "runs"
    task_id: str
    review_status: str
    run_id: str | None = None


class NodeMetadataUpdateRequest(BaseModel):
    dag_path: str
    task_id: str
    updates: dict[str, Any]


class NodeDependenciesUpdateRequest(BaseModel):
    dag_path: str
    task_id: str
    dependencies: list[str]


class CreateNodeRequest(BaseModel):
    dag_path: str
    node: dict[str, Any]


class RuntimeDemoRequest(BaseModel):
    workspace: str
    agent: str = "shell-dummy"
    shell_command: str | None = None
    assignment_id: str = "assign-implement-demo"
    session_id: str = "session-implement-demo"
    result_id: str = "result-implement-demo"


class MutationDecisionRequest(BaseModel):
    workflow_path: str
    ledger_path: str
    proposal_event_id: str
    decision: Literal["accept", "reject"]
    actor: Literal["orchestrator", "human"] = "human"
    reason: str | None = None
    applied_changes: dict[str, Any] | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="BureauLess workbench")

    @app.exception_handler(ProtocolError)
    def handle_protocol_error(_request, exc: ProtocolError) -> JSONResponse:
        return JSONResponse(status_code=400, content=protocol_error_payload(exc))

    @app.exception_handler(OSError)
    def handle_os_error(_request, exc: OSError) -> JSONResponse:
        return JSONResponse(status_code=400, content=protocol_error_payload(exc))

    @app.get("/api/dag")
    def api_dag(path: str = "examples/optimization_dag.yaml") -> dict[str, Any]:
        dag = load_dag(Path(path))
        return dag_payload(dag)

    @app.get("/api/validate")
    def api_validate(path: str = "examples/optimization_dag.yaml") -> dict[str, Any]:
        try:
            load_dag(Path(path))
        except yaml.YAMLError as exc:
            return {"ok": False, "errors": [validation_error_from_yaml(exc)]}
        except (ProtocolError, OSError) as exc:
            return {"ok": False, "errors": [validation_error_from_exception(exc)]}
        return {"ok": True, "errors": []}

    @app.get("/api/runs")
    def api_runs(runs_dir: str = "runs") -> dict[str, Any]:
        return {"runs": load_run_records(Path(runs_dir))}

    @app.get("/api/state")
    def api_state(
        dag_path: str = "examples/optimization_dag.yaml",
        runs_dir: str = "runs",
    ) -> dict[str, Any]:
        dag = load_dag(Path(dag_path))
        records = load_run_records(Path(runs_dir))
        return state_payload(dag, records)

    @app.get("/api/prompt/{task_id}")
    def api_prompt(
        task_id: str,
        dag_path: str = "examples/optimization_dag.yaml",
    ) -> dict[str, str]:
        return {"task_id": task_id, "prompt": render_prompt(load_dag(Path(dag_path)), task_id)}

    @app.post("/api/review")
    def api_review(request: ReviewRequest) -> dict[str, str]:
        dag = load_dag(Path(request.dag_path))
        path = update_review_status(
            dag=dag,
            runs_dir=Path(request.runs_dir),
            task_id=request.task_id,
            review_status=request.review_status,
            run_id=request.run_id,
        )
        return {"path": str(path)}

    @app.post("/api/dag/node-metadata")
    def api_update_node_metadata(request: NodeMetadataUpdateRequest) -> dict[str, Any]:
        path, backup_path, dag = update_node_metadata(
            dag_path=Path(request.dag_path),
            task_id=request.task_id,
            updates=request.updates,
        )
        return {
            "path": str(path),
            "backup_path": str(backup_path),
            "node": dag.nodes[request.task_id].to_dict(),
        }

    @app.post("/api/dag/node-dependencies")
    def api_update_node_dependencies(
        request: NodeDependenciesUpdateRequest,
    ) -> dict[str, Any]:
        path, backup_path, dag = update_node_dependencies(
            dag_path=Path(request.dag_path),
            task_id=request.task_id,
            dependencies=request.dependencies,
        )
        return {
            "path": str(path),
            "backup_path": str(backup_path),
            "node": dag.nodes[request.task_id].to_dict(),
        }

    @app.post("/api/dag/nodes")
    def api_create_node(request: CreateNodeRequest) -> dict[str, Any]:
        path, backup_path, dag = create_node(
            dag_path=Path(request.dag_path),
            node_data=request.node,
        )
        node_id = request.node.get("id")
        if not isinstance(node_id, str):
            raise ProtocolError("Field 'id' must be a string")
        return {
            "path": str(path),
            "backup_path": str(backup_path),
            "node": dag.nodes[node_id].to_dict(),
        }

    @app.get("/api/mission")
    def api_mission(path: str = "examples/missions/demo/mission.yaml") -> dict[str, Any]:
        mission = load_mission(Path(path))
        return {
            "mission_id": mission.mission_id,
            "goal": mission.goal,
            "status": mission.status,
            "default_mode": mission.default_mode,
            "allowed_modes": mission.allowed_modes,
            "budget": mission.budget,
            "models": mission.models,
            "human_gate": mission.human_gate,
        }

    @app.get("/api/workflow")
    def api_workflow(path: str = "examples/missions/demo/workflows/coder_reviewer_committer.yaml") -> dict[str, Any]:
        workflow = load_workflow(Path(path))
        return workflow_payload(workflow)

    @app.get("/api/ledger")
    def api_ledger(path: str = "examples/missions/demo/ledger.yaml") -> dict[str, Any]:
        ledger = load_ledger(Path(path))
        return {
            "mission_id": ledger.mission_id,
            "ledger_version": ledger.ledger_version,
            "current_goal": ledger.current_goal,
            "current_plan_ref": ledger.current_plan_ref,
            "public_findings": ledger.public_findings,
            "decisions": ledger.decisions,
            "risks": ledger.risks,
            "artifacts": ledger.artifacts,
            "broadcasts": ledger.broadcasts,
            "open_questions": ledger.open_questions,
            "event_log": ledger.event_log,
        }

    @app.get("/api/replay")
    def api_replay(
        workflow_path: str = "examples/missions/demo/workflows/coder_reviewer_committer.yaml",
        ledger_path: str = "examples/missions/demo/ledger.yaml",
    ) -> dict[str, Any]:
        workflow = load_workflow(Path(workflow_path))
        ledger = load_ledger(Path(ledger_path))
        return replay_workflow(workflow, ledger).to_dict()

    @app.get("/api/gatekeeper")
    def api_gatekeeper(
        workflow_path: str = "examples/missions/demo/workflows/coder_reviewer_committer.yaml",
        ledger_path: str = "examples/missions/demo/ledger.yaml",
    ) -> dict[str, Any]:
        workflow = load_workflow(Path(workflow_path))
        ledger = load_ledger(Path(ledger_path))
        return evaluate_gatekeeper(workflow, ledger).to_dict()

    @app.get("/api/mutations")
    def api_mutations(
        workflow_path: str = "examples/missions/demo/workflows/coder_reviewer_committer.yaml",
        ledger_path: str = "examples/missions/demo/ledger.yaml",
    ) -> dict[str, Any]:
        workflow = load_workflow(Path(workflow_path))
        ledger = load_ledger(Path(ledger_path))
        return mutation_inspection_payload(workflow, ledger)

    @app.post("/api/mutations/decision")
    def api_mutation_decision(request: MutationDecisionRequest) -> dict[str, Any]:
        workflow = load_workflow(Path(request.workflow_path))
        ledger_path = Path(request.ledger_path)
        ledger = load_ledger(ledger_path)
        proposal_event = next(
            (
                event
                for event in ledger.event_log
                if event.get("event_id") == request.proposal_event_id
                and event.get("event_type") == "workflow_mutation_proposed"
            ),
            None,
        )
        if proposal_event is None:
            raise ProtocolError("Unknown workflow mutation proposal event")

        event_id = f"event-mutation-{request.decision}-{uuid4()}"
        decision_event: dict[str, Any] = {
            "event_id": event_id,
            "event_type": f"workflow_mutation_{request.decision}ed",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "source_event_id": request.proposal_event_id,
            "actor": request.actor,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if request.decision == "reject":
            if not request.reason:
                raise ProtocolError("Mutation rejection requires a reason")
            decision_event["reason"] = request.reason
            updated = append_ledger_event(ledger, decision_event, workflow)
        else:
            proposal = proposal_event.get("mutation_proposal")
            if not isinstance(proposal, dict):
                raise ProtocolError("Mutation proposal event is missing mutation_proposal")
            proposed_changes = proposal.get("proposed_changes")
            if not isinstance(proposed_changes, dict):
                raise ProtocolError("Mutation proposal is missing proposed_changes")
            decision_event["applied_changes"] = (
                request.applied_changes
                if request.applied_changes is not None
                else proposed_changes
            )
            before = materialize_current_workflow(workflow, ledger)
            updated = append_ledger_event(ledger, decision_event, workflow)
            after = materialize_current_workflow(workflow, updated)
            impacts = evaluate_assignment_impacts(
                before,
                after,
                updated,
                decision_event["applied_changes"],
            )
            for supersession_event in build_mutation_supersession_events(
                after, decision_event, impacts
            ):
                updated = append_ledger_event(updated, supersession_event, after)

        write_ledger(ledger_path, updated)
        return mutation_inspection_payload(workflow, updated)

    @app.get("/api/agents")
    def api_agents() -> dict[str, Any]:
        return {"agents": [spec.to_dict() for spec in list_agent_specs()]}

    @app.get("/api/agents/{agent_id}/doctor")
    def api_agent_doctor(agent_id: str) -> dict[str, Any]:
        return doctor_agent(agent_id).to_dict()

    @app.get("/api/metrics")
    def api_metrics(path: str, price_snapshot: str | None = None) -> dict[str, Any]:
        snapshot_path = Path(price_snapshot) if price_snapshot else None
        return summarize_metrics(Path(path), snapshot_path)

    @app.post("/api/runtime-demo")
    def api_runtime_demo(request: RuntimeDemoRequest) -> dict[str, Any]:
        paths = prepare_demo_workspace(Path(request.workspace))
        workflow = load_workflow(paths["workflow"])
        ledger = load_ledger(paths["ledger"])
        assignment = export_assignment(
            workflow,
            ledger,
            "implement",
            assignment_id=request.assignment_id,
        )
        assignment_path = paths["assignments_dir"] / "implement_assignment.yaml"
        _write_yaml(assignment_path, assignment.to_dict())

        created_event = build_assignment_created_event(
            workflow,
            assignment,
            request.session_id,
            request.agent,
        )
        ledger = append_ledger_event(ledger, created_event, workflow)
        write_ledger(paths["ledger"], ledger)

        spec = create_session_spec(
            assignment=assignment,
            agent_id=request.agent,
            workdir=Path(request.workspace),
            shell_command=request.shell_command or _runtime_demo_shell_command(request.result_id),
            session_id=request.session_id,
        )
        record = run_session(spec, assignment)
        session_path = paths["sessions_dir"] / "implement_session.yaml"
        _write_yaml(session_path, record.to_dict())

        result = package_session_result(record, assignment, result_id=request.result_id)
        result_path = paths["packaged_results_dir"] / "implement_result.yaml"
        _write_yaml(result_path, result.to_dict())

        ledger = import_result_proposal(workflow, ledger, assignment, result)
        write_ledger(paths["ledger"], ledger)

        return {
            "workspace": str(Path(request.workspace).resolve()),
            "mission_path": str(paths["mission"]),
            "workflow_path": str(paths["workflow"]),
            "ledger_path": str(paths["ledger"]),
            "assignment_path": str(assignment_path),
            "session_path": str(session_path),
            "result_path": str(result_path),
            "agent": request.agent,
            "assignment_id": assignment.assignment_id,
            "session_id": record.session_id,
            "result_id": result.result_id,
            "replay": replay_workflow(workflow, ledger).to_dict(),
            "gatekeeper": evaluate_gatekeeper(workflow, ledger).to_dict(),
            "result": result.to_dict(),
        }

    return app


def dag_payload(dag: Dag) -> dict[str, Any]:
    nodes = [node.to_dict() for node in dag.nodes.values()]
    edges = [
        {"id": f"{dependency}->{node.id}", "source": dependency, "target": node.id}
        for node in dag.nodes.values()
        for dependency in node.dependencies
    ]
    return {
        "schema_version": dag.schema_version,
        "project": dag.project,
        "default_review_model": dag.default_review_model,
        "nodes": nodes,
        "edges": edges,
    }


def state_payload(dag: Dag, records: list[dict[str, Any]]) -> dict[str, Any]:
    ready = {node.id for node in ready_nodes(dag, records)}
    states = {
        node_id: classify_node_state(dag, node_id, records, ready)
        for node_id in dag.nodes
    }
    return {"states": states, "ready": sorted(ready)}


def workflow_payload(workflow) -> dict[str, Any]:
    return {
        "workflow_id": workflow.workflow_id,
        "mission_id": workflow.mission_id,
        "mode": workflow.mode,
        "status": workflow.status,
        "reason": workflow.reason,
        "proposed_by": workflow.proposed_by,
        "roles": {
            role_name: {
                "can_emit": role.can_emit,
                "can_consume": role.can_consume,
            }
            for role_name, role in workflow.roles.items()
        },
        "events": {
            event_name: {"producer_roles": event.producer_roles}
            for event_name, event in workflow.events.items()
        },
        "nodes": [
            {
                "id": node.id,
                "role": node.role,
                "waits_for": node.waits_for,
                "emits": node.emits,
            }
            for node in workflow.nodes.values()
        ],
        "gates": [
            {
                "id": gate.id,
                "node_id": gate.node_id,
                "requires": gate.requires,
            }
            for gate in workflow.gates
        ],
        "terminal_events": workflow.terminal_events,
        "broadcast_policy": workflow.broadcast_policy,
        "budget_policy": workflow.budget_policy,
    }


def mutation_inspection_payload(workflow, ledger) -> dict[str, Any]:
    replay = replay_workflow(workflow, ledger)
    current = materialize_current_workflow(workflow, ledger)
    event_by_id = {
        event.get("event_id"): event
        for event in ledger.event_log
        if isinstance(event.get("event_id"), str)
    }
    assignment_nodes = {
        event.get("assignment_id"): event.get("node_id")
        for event in ledger.event_log
        if isinstance(event.get("assignment_id"), str)
        and isinstance(event.get("node_id"), str)
    }
    proposals = []
    for event_id, mutation in replay.mutation_proposals.items():
        event = event_by_id.get(event_id, {})
        proposal = event.get("mutation_proposal", {})
        affected_assignments = sorted(
            assignment_id
            for assignment_id, node_id in assignment_nodes.items()
            if node_id in mutation.affected_node_ids
        )
        superseded_assignments = sorted(
            event.get("assignment_id")
            for event in ledger.event_log
            if event.get("event_type") == "assignment_superseded"
            and event.get("mutation_event_id") == mutation.decision_event_id
            and isinstance(event.get("assignment_id"), str)
        )
        proposals.append(
            {
                **mutation.to_dict(),
                "proposal": proposal,
                "evidence_refs": (
                    proposal.get("evidence_refs", [])
                    if isinstance(proposal, dict)
                    else []
                ),
                "affected_assignments": affected_assignments,
                "superseded_assignments": superseded_assignments,
            }
        )
    return {
        "workflow_id": workflow.workflow_id,
        "current_workflow": workflow_payload(current),
        "proposals": proposals,
    }


def protocol_error_payload(exc: Exception) -> dict[str, str]:
    return {"error": str(exc)}


def _runtime_demo_shell_command(result_id: str) -> str:
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "effective_model": "shell-dummy",
            "effective_provider": "fixture",
            "emitted_events": ["patch_ready"],
            "artifacts": [
                {
                    "artifact_id": f"artifact-{result_id}-patch",
                    "path": "artifacts/implement_patch.diff",
                }
            ],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    return (
        "mkdir -p artifacts\n"
        "cat <<'EOF' > artifacts/implement_patch.diff\n"
        "--- a/src/demo.py\n"
        "+++ b/src/demo.py\n"
        "@@\n"
        "-print('old')\n"
        "+print('new')\n"
        "EOF\n"
        f"cat <<'EOF'\n{payload}\nEOF"
    )


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def validation_error_from_yaml(exc: yaml.YAMLError) -> dict[str, Any]:
    message = "Invalid YAML syntax"
    if getattr(exc, "problem", None):
        message = f"{message}: {exc.problem}"

    error: dict[str, Any] = {
        "code": "invalid_yaml",
        "message": message,
    }
    mark = getattr(exc, "problem_mark", None)
    if mark is not None:
        error["line"] = mark.line + 1
        error["column"] = mark.column + 1
    return error


def validation_error_from_exception(exc: Exception) -> dict[str, Any]:
    message = str(exc)

    missing_fields_match = re.fullmatch(
        r"Task node is missing required fields: (?P<fields>.+)",
        message,
    )
    if missing_fields_match:
        fields = [field.strip() for field in missing_fields_match.group("fields").split(",")]
        return {
            "code": "missing_required_fields",
            "message": message,
            "fields": fields,
        }

    unknown_dependency_match = re.fullmatch(
        r"(?P<node_id>[^:]+): unknown dependency (?P<dependency>.+)",
        message,
    )
    if unknown_dependency_match:
        dependency = unknown_dependency_match.group("dependency").strip("'")
        return {
            "code": "unknown_dependency",
            "message": message,
            "node_id": unknown_dependency_match.group("node_id"),
            "dependency": dependency,
        }

    duplicate_node_match = re.fullmatch(r"Duplicate node id: (?P<node_id>.+)", message)
    if duplicate_node_match:
        return {
            "code": "duplicate_node",
            "message": message,
            "node_id": duplicate_node_match.group("node_id"),
        }

    cycle_match = re.fullmatch(r"Cycle detected at node (?P<node_id>.+)", message)
    if cycle_match:
        return {
            "code": "cycle_detected",
            "message": message,
            "node_id": cycle_match.group("node_id"),
        }

    field_match = re.fullmatch(r"Field '(?P<field>[^']+)' must be a string", message)
    if field_match:
        return {
            "code": "missing_required_fields",
            "message": message,
            "fields": [field_match.group("field")],
        }

    return {
        "code": "validation_error",
        "message": message,
    }


def classify_node_state(
    dag: Dag,
    node_id: str,
    records: list[dict[str, Any]],
    ready: set[str],
) -> NodeState:
    node_records = [
        record
        for record in records
        if record.get("task_id") == node_id and record.get("status") == "passed"
    ]
    if node_records:
        latest = node_records[-1]
        review_status = latest.get("review_status")
        if review_status in {"pending", "rejected"}:
            return "needs_review"
        node = dag.nodes[node_id]
        if review_status in {
            "auto_pass": {"not_required", "approved"},
            "orchestrator_review": {"orchestrator_approved"},
            "human_review": {"human_approved"},
        }[node.review_gate]:
            return "completed"
        return "needs_review"
    if node_id in ready:
        return "ready"
    return "blocked"


app = create_app()


__all__ = [
    "CreateNodeRequest",
    "NodeMetadataUpdateRequest",
    "ProtocolError",
    "RuntimeDemoRequest",
    "app",
    "classify_node_state",
    "create_app",
    "dag_payload",
    "protocol_error_payload",
    "state_payload",
    "workflow_payload",
]
