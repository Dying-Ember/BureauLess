from pathlib import Path

from bureauless.core import create_run_record, load_dag, write_run_record
from bureauless.api.server import (
    create_app,
    dag_payload,
    protocol_error_payload,
    state_payload,
    update_review_status,
)


def test_api_dag_reads_yaml_dag() -> None:
    body = dag_payload(load_dag(Path("examples/optimization_dag.yaml")))
    assert body["project"] == "automation-inspection-optimization"
    assert {"source": "baseline-inventory", "target": "field-resolver-skeleton"} in [
        {"source": edge["source"], "target": edge["target"]}
        for edge in body["edges"]
    ]


def test_api_state_reports_ready_and_blocked() -> None:
    dag = load_dag(Path("examples/optimization_dag.yaml"))
    body = state_payload(dag, [])
    assert body["states"]["baseline-inventory"] == "ready"
    assert body["states"]["field-resolver-skeleton"] == "blocked"


def test_api_prompt_renders_node_prompt() -> None:
    from bureauless.core import render_prompt

    prompt = render_prompt(load_dag(Path("examples/optimization_dag.yaml")), "baseline-inventory")
    assert "Recommended model: gpt-5-mini" in prompt


def test_api_review_updates_yaml_record(tmp_path: Path) -> None:
    dag = load_dag(Path("examples/optimization_dag.yaml"))
    record = create_run_record(
        dag,
        "field-resolver-skeleton",
        model="gpt-5-mini",
        status="passed",
    )
    write_run_record(tmp_path, record)

    path = update_review_status(
        dag,
        tmp_path,
        "field-resolver-skeleton",
        "orchestrator_approved",
    )
    assert "field-resolver-skeleton" in str(path)


def test_runtime_api_endpoints() -> None:
    app = create_app()
    endpoints = {
        route.path: route.endpoint
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/")
    }

    mission = endpoints["/api/mission"]()
    workflow = endpoints["/api/workflow"]()
    ledger = endpoints["/api/ledger"]()
    replay = endpoints["/api/replay"]()
    gatekeeper = endpoints["/api/gatekeeper"]()
    agents = endpoints["/api/agents"]()
    doctor = endpoints["/api/agents/{agent_id}/doctor"]("codex-cli")

    assert mission["mission_id"] == "demo"
    assert workflow["workflow_id"] == "coder-reviewer-committer-001"
    assert ledger["mission_id"] == "demo"
    assert replay["nodes"]["implement"]["state"] == "runnable"
    assert gatekeeper["ready"] == ["implement"]
    assert any(agent["agent_id"] == "codex-cli" for agent in agents["agents"])
    assert doctor["agent_id"] == "codex-cli"


def test_metrics_api_endpoint(tmp_path: Path) -> None:
    app = create_app()
    endpoints = {
        route.path: route.endpoint
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/")
    }
    session_path = tmp_path / "session.yaml"
    session_path.write_text(
        """
session_id: session-001
assignment_id: assign-001
agent_id: fake
status: completed
started_at: 2026-01-01T00:00:00Z
finished_at: 2026-01-01T00:00:01Z
exit:
  code: 0
  reason: completed
native_logs:
  stdout: ""
  stderr: ""
diff_refs: []
artifacts: []
outcome_metrics:
  wall_time_ms: 1000
  changed_files_count: 0
result_proposal: {}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    response = endpoints["/api/metrics"](path=str(session_path))

    assert response["entries"][0]["assignment_id"] == "assign-001"


def test_runtime_api_returns_structured_error_without_traceback() -> None:
    payload = protocol_error_payload(FileNotFoundError("missing-workflow.yaml"))

    assert "error" in payload
    assert "Traceback" not in payload["error"]
