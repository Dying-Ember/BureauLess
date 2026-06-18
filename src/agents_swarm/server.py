from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI
from pydantic import BaseModel

from .core import (
    Dag,
    ProtocolError,
    load_dag,
    load_run_records,
    ready_nodes,
    render_prompt,
    update_review_status,
)


NodeState = Literal["ready", "blocked", "completed", "needs_review"]


class ReviewRequest(BaseModel):
    dag_path: str
    runs_dir: str = "runs"
    task_id: str
    review_status: str
    run_id: str | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="agents-swarm workbench")

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
    "state_payload",
]
