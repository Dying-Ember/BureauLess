from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..agents import doctor_agent, list_agent_specs
from ..core import (
    Dag,
    ProtocolError,
    load_dag,
    load_run_records,
    ready_nodes,
    render_prompt,
    update_review_status,
)
from ..protocol import load_ledger, load_mission, load_workflow
from ..runtime import evaluate_gatekeeper, replay_workflow, summarize_metrics


NodeState = Literal["ready", "blocked", "completed", "needs_review"]


class ReviewRequest(BaseModel):
    dag_path: str
    runs_dir: str = "runs"
    task_id: str
    review_status: str
    run_id: str | None = None


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


def protocol_error_payload(exc: Exception) -> dict[str, str]:
    return {"error": str(exc)}


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
    "ProtocolError",
    "app",
    "classify_node_state",
    "create_app",
    "dag_payload",
    "protocol_error_payload",
    "state_payload",
    "workflow_payload",
]
