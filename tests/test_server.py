from pathlib import Path

import yaml

from bureauless.core import ProtocolError, create_run_record, load_dag, write_run_record
from bureauless.api.server import (
    CreateNodeRequest,
    MutationDecisionRequest,
    NodeDependenciesUpdateRequest,
    NodeMetadataUpdateRequest,
    RuntimeDemoRequest,
    create_app,
    dag_payload,
    protocol_error_payload,
    state_payload,
    update_review_status,
)


def _api_endpoints() -> dict[str, object]:
    app = create_app()
    return {
        route.path: route.endpoint
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/")
    }


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
    endpoints = _api_endpoints()

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


def test_mutation_inspection_and_acceptance_api(tmp_path: Path) -> None:
    workflow_path = tmp_path / "workflow.yaml"
    ledger_path = tmp_path / "ledger.yaml"
    workflow_path.write_text(
        yaml.safe_dump(
            {
                "workflow_id": "workflow-mutation-test",
                "mission_id": "demo",
                "mode": "small_dag",
                "roles": {
                    "producer": {"can_emit": ["ready"], "can_consume": []},
                    "consumer": {"can_emit": ["done"], "can_consume": ["ready"]},
                },
                "events": {
                    "ready": {"producer_roles": ["producer"]},
                    "done": {"producer_roles": ["consumer"]},
                },
                "nodes": [
                    {"id": "start", "role": "producer", "waits_for": [], "emits": ["ready"]},
                    {"id": "finish", "role": "consumer", "waits_for": [], "emits": ["done"]},
                ],
                "gates": [],
                "terminal_events": ["done"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    proposal = {
        "proposal_id": "mutation-001",
        "proposal_type": "workflow_mutation",
        "workflow_id": "workflow-mutation-test",
        "source": {
            "assignment_id": "assign-001",
            "session_id": "session-001",
            "actor": "worker",
        },
        "reason": "discovered_missing_dependency",
        "rationale": "A verification producer must run before finish.",
        "proposed_changes": {
            "add_nodes": [
                {"id": "verify", "role": "producer", "waits_for": [], "emits": ["ready"]}
            ],
            "add_edges": [
                {"from_node": "verify", "to_node": "finish", "event": "ready"}
            ],
            "remove_edges": [],
            "supersede_assignments": [],
        },
        "evidence_refs": ["artifact-impact-report"],
        "requires_approval": "orchestrator",
    }
    ledger_path.write_text(
        yaml.safe_dump(
            {
                "mission_id": "demo",
                "ledger_version": 1,
                "current_goal": "Test mutations",
                "current_plan_ref": "workflow.yaml",
                "public_findings": [],
                "decisions": [],
                "risks": [],
                "artifacts": [],
                "broadcasts": [],
                "open_questions": [],
                "event_log": [
                    {
                        "event_id": "event-mutation-001",
                        "event_type": "workflow_mutation_proposed",
                        "mission_id": "demo",
                        "workflow_id": "workflow-mutation-test",
                        "mutation_proposal": proposal,
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    endpoints = _api_endpoints()

    pending = endpoints["/api/mutations"](
        workflow_path=str(workflow_path), ledger_path=str(ledger_path)
    )
    accepted = endpoints["/api/mutations/decision"](
        MutationDecisionRequest(
            workflow_path=str(workflow_path),
            ledger_path=str(ledger_path),
            proposal_event_id="event-mutation-001",
            decision="accept",
            actor="human",
        )
    )

    assert pending["proposals"][0]["state"] == "pending"
    assert pending["proposals"][0]["evidence_refs"] == ["artifact-impact-report"]
    assert accepted["proposals"][0]["state"] == "accepted"
    assert [node["id"] for node in accepted["current_workflow"]["nodes"]] == [
        "start",
        "finish",
        "verify",
    ]
    saved = yaml.safe_load(ledger_path.read_text(encoding="utf-8"))
    assert saved["event_log"][-1]["event_type"] == "workflow_mutation_accepted"


def test_metrics_api_endpoint(tmp_path: Path) -> None:
    endpoints = _api_endpoints()
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


def test_runtime_demo_api_creates_reviewable_workspace(tmp_path: Path) -> None:
    endpoints = _api_endpoints()

    response = endpoints["/api/runtime-demo"](
        RuntimeDemoRequest(workspace=str(tmp_path / "runtime-demo"))
    )

    assert response["assignment_id"] == "assign-implement-demo"
    assert response["result_id"] == "result-implement-demo"
    assert response["replay"]["nodes"]["implement"]["state"] == "completed"
    assert response["gatekeeper"]["ready"] == ["review"]

    mission = endpoints["/api/mission"](path=response["mission_path"])
    workflow = endpoints["/api/workflow"](path=response["workflow_path"])
    ledger = endpoints["/api/ledger"](path=response["ledger_path"])
    replay = endpoints["/api/replay"](
        workflow_path=response["workflow_path"],
        ledger_path=response["ledger_path"],
    )
    gatekeeper = endpoints["/api/gatekeeper"](
        workflow_path=response["workflow_path"],
        ledger_path=response["ledger_path"],
    )
    metrics = endpoints["/api/metrics"](path=response["session_path"])

    assert mission["mission_id"] == "demo"
    assert workflow["workflow_id"] == "coder-reviewer-committer-001"
    assert ledger["event_log"][0]["event_type"] == "assignment_created"
    assert ledger["event_log"][1]["event_type"] == "result_submitted"
    assert ledger["event_log"][2]["event_type"] == "patch_ready"
    assert replay["nodes"]["implement"]["state"] == "completed"
    assert replay["nodes"]["review"]["state"] == "runnable"
    assert gatekeeper["ready"] == ["review"]
    assert metrics["entries"][0]["assignment_id"] == "assign-implement-demo"


def test_validate_api_returns_ok_for_valid_dag() -> None:
    endpoints = _api_endpoints()

    response = endpoints["/api/validate"](path="examples/optimization_dag.yaml")

    assert response == {"ok": True, "errors": []}


def test_validate_api_reports_invalid_yaml(tmp_path: Path) -> None:
    endpoints = _api_endpoints()
    dag_path = tmp_path / "invalid.yaml"
    dag_path.write_text("project: demo\nnodes: [\n", encoding="utf-8")

    response = endpoints["/api/validate"](path=str(dag_path))

    assert response["ok"] is False
    assert response["errors"][0]["code"] == "invalid_yaml"
    assert "Traceback" not in response["errors"][0]["message"]
    assert response["errors"][0]["line"] == 3


def test_validate_api_reports_missing_required_fields(tmp_path: Path) -> None:
    endpoints = _api_endpoints()
    dag_path = tmp_path / "missing-fields.yaml"
    dag_path.write_text(
        """
schema_version: "1"
project: demo
default_review_model: gpt-5
nodes:
  - id: first-task
    title: First task
    goal: Do the thing
    dependencies: []
    target_files: []
    allowed_models: [gpt-5]
    recommended_model: gpt-5
    risk_level: low
    review_gate: auto_pass
    acceptance_criteria: []
    verification_commands: []
    do_not: []
    failure_policy: retry_same_model
""".strip()
        + "\n",
        encoding="utf-8",
    )

    response = endpoints["/api/validate"](path=str(dag_path))

    assert response["ok"] is False
    assert response["errors"] == [
        {
            "code": "missing_required_fields",
            "message": "Task node is missing required fields: prompt_template",
            "fields": ["prompt_template"],
        }
    ]


def test_validate_api_reports_unknown_dependency(tmp_path: Path) -> None:
    endpoints = _api_endpoints()
    dag_path = tmp_path / "unknown-dependency.yaml"
    dag_path.write_text(
        """
schema_version: "1"
project: demo
default_review_model: gpt-5
nodes:
  - id: first-task
    title: First task
    goal: Do the thing
    dependencies: [missing-task]
    target_files: []
    context_files: []
    allowed_models: [gpt-5]
    recommended_model: gpt-5
    risk_level: low
    review_gate: auto_pass
    acceptance_criteria: []
    verification_commands: []
    do_not: []
    prompt_template: "Hello"
    failure_policy: retry_same_model
""".strip()
        + "\n",
        encoding="utf-8",
    )

    response = endpoints["/api/validate"](path=str(dag_path))

    assert response["ok"] is False
    assert response["errors"] == [
        {
            "code": "unknown_dependency",
            "message": "first-task: unknown dependency 'missing-task'",
            "node_id": "first-task",
            "dependency": "missing-task",
        }
    ]


def test_validate_api_reports_duplicate_nodes(tmp_path: Path) -> None:
    endpoints = _api_endpoints()
    dag_path = tmp_path / "duplicate-node.yaml"
    dag_path.write_text(
        """
schema_version: "1"
project: demo
default_review_model: gpt-5
nodes:
  - id: repeated-task
    title: First task
    goal: Do the thing
    dependencies: []
    target_files: []
    context_files: []
    allowed_models: [gpt-5]
    recommended_model: gpt-5
    risk_level: low
    review_gate: auto_pass
    acceptance_criteria: []
    verification_commands: []
    do_not: []
    prompt_template: "Hello"
    failure_policy: retry_same_model
  - id: repeated-task
    title: Second task
    goal: Do the other thing
    dependencies: []
    target_files: []
    context_files: []
    allowed_models: [gpt-5]
    recommended_model: gpt-5
    risk_level: low
    review_gate: auto_pass
    acceptance_criteria: []
    verification_commands: []
    do_not: []
    prompt_template: "Hello"
    failure_policy: retry_same_model
""".strip()
        + "\n",
        encoding="utf-8",
    )

    response = endpoints["/api/validate"](path=str(dag_path))

    assert response["ok"] is False
    assert response["errors"] == [
        {
            "code": "duplicate_node",
            "message": "Duplicate node id: repeated-task",
            "node_id": "repeated-task",
        }
    ]


def test_validate_api_reports_cycles(tmp_path: Path) -> None:
    endpoints = _api_endpoints()
    dag_path = tmp_path / "cycle.yaml"
    dag_path.write_text(
        """
schema_version: "1"
project: demo
default_review_model: gpt-5
nodes:
  - id: first-task
    title: First task
    goal: Do the thing
    dependencies: [second-task]
    target_files: []
    context_files: []
    allowed_models: [gpt-5]
    recommended_model: gpt-5
    risk_level: low
    review_gate: auto_pass
    acceptance_criteria: []
    verification_commands: []
    do_not: []
    prompt_template: "Hello"
    failure_policy: retry_same_model
  - id: second-task
    title: Second task
    goal: Do the other thing
    dependencies: [first-task]
    target_files: []
    context_files: []
    allowed_models: [gpt-5]
    recommended_model: gpt-5
    risk_level: low
    review_gate: auto_pass
    acceptance_criteria: []
    verification_commands: []
    do_not: []
    prompt_template: "Hello"
    failure_policy: retry_same_model
""".strip()
        + "\n",
        encoding="utf-8",
    )

    response = endpoints["/api/validate"](path=str(dag_path))

    assert response["ok"] is False
    assert response["errors"] == [
        {
            "code": "cycle_detected",
            "message": "Cycle detected at node first-task",
            "node_id": "first-task",
        }
    ]


def test_runtime_api_returns_structured_error_without_traceback() -> None:
    payload = protocol_error_payload(FileNotFoundError("missing-workflow.yaml"))

    assert "error" in payload
    assert "Traceback" not in payload["error"]


def test_api_update_node_metadata_returns_updated_node(tmp_path: Path) -> None:
    dag_path = tmp_path / "dag.yaml"
    dag_path.write_text(
        """
schema_version: "1"
project: metadata-test
default_review_model: gpt-5
nodes:
  - id: alpha
    title: Alpha
    goal: Do alpha
    dependencies: []
    target_files: [src/a.py]
    context_files: []
    allowed_models: [gpt-5-mini, gpt-5]
    recommended_model: gpt-5-mini
    risk_level: low
    review_gate: auto_pass
    acceptance_criteria: []
    verification_commands: []
    do_not: []
    prompt_template: "Alpha ${id}"
    failure_policy: retry_same_model
    tags: [core]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    endpoints = _api_endpoints()
    response = endpoints["/api/dag/node-metadata"](
        NodeMetadataUpdateRequest(
            dag_path=str(dag_path),
            task_id="alpha",
            updates={"risk_level": "medium"},
        )
    )

    assert response["path"] == str(dag_path)
    assert response["backup_path"].endswith(".bak")
    assert response["node"]["risk_level"] == "medium"
    assert load_dag(dag_path).nodes["alpha"].risk_level == "medium"


def test_api_update_node_metadata_rejects_invalid_value(tmp_path: Path) -> None:
    dag_path = tmp_path / "dag.yaml"
    dag_path.write_text(
        """
schema_version: "1"
project: metadata-test
default_review_model: gpt-5
nodes:
  - id: alpha
    title: Alpha
    goal: Do alpha
    dependencies: []
    target_files: [src/a.py]
    context_files: []
    allowed_models: [gpt-5-mini]
    recommended_model: gpt-5-mini
    risk_level: low
    review_gate: auto_pass
    acceptance_criteria: []
    verification_commands: []
    do_not: []
    prompt_template: "Alpha ${id}"
    failure_policy: retry_same_model
""".strip()
        + "\n",
        encoding="utf-8",
    )

    endpoints = _api_endpoints()
    try:
        endpoints["/api/dag/node-metadata"](
            NodeMetadataUpdateRequest(
                dag_path=str(dag_path),
                task_id="alpha",
                updates={"review_gate": "ship_it"},
            )
        )
    except ProtocolError as exc:
        assert "invalid review_gate" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_api_update_node_dependencies_returns_updated_node(tmp_path: Path) -> None:
    dag_path = tmp_path / "dag.yaml"
    dag_path.write_text(
        """
schema_version: "1"
project: dependency-test
default_review_model: gpt-5
nodes:
  - id: alpha
    title: Alpha
    goal: Do alpha
    dependencies: []
    target_files: [src/a.py]
    context_files: []
    allowed_models: [gpt-5-mini]
    recommended_model: gpt-5-mini
    risk_level: low
    review_gate: auto_pass
    acceptance_criteria: []
    verification_commands: []
    do_not: []
    prompt_template: "Alpha ${id}"
    failure_policy: retry_same_model
  - id: beta
    title: Beta
    goal: Do beta
    dependencies: []
    target_files: [src/b.py]
    context_files: []
    allowed_models: [gpt-5]
    recommended_model: gpt-5
    risk_level: medium
    review_gate: human_review
    acceptance_criteria: []
    verification_commands: []
    do_not: []
    prompt_template: "Beta ${id}"
    failure_policy: send_to_human
""".strip()
        + "\n",
        encoding="utf-8",
    )

    endpoints = _api_endpoints()
    response = endpoints["/api/dag/node-dependencies"](
        NodeDependenciesUpdateRequest(
            dag_path=str(dag_path),
            task_id="beta",
            dependencies=["alpha"],
        )
    )

    assert response["path"] == str(dag_path)
    assert response["backup_path"].endswith(".bak")
    assert response["node"]["dependencies"] == ["alpha"]
    assert load_dag(dag_path).nodes["beta"].dependencies == ["alpha"]


def test_api_update_node_dependencies_rejects_unknown_dependency(tmp_path: Path) -> None:
    dag_path = tmp_path / "dag.yaml"
    dag_path.write_text(
        """
schema_version: "1"
project: dependency-test
default_review_model: gpt-5
nodes:
  - id: alpha
    title: Alpha
    goal: Do alpha
    dependencies: []
    target_files: [src/a.py]
    context_files: []
    allowed_models: [gpt-5-mini]
    recommended_model: gpt-5-mini
    risk_level: low
    review_gate: auto_pass
    acceptance_criteria: []
    verification_commands: []
    do_not: []
    prompt_template: "Alpha ${id}"
    failure_policy: retry_same_model
""".strip()
        + "\n",
        encoding="utf-8",
    )

    endpoints = _api_endpoints()
    try:
        endpoints["/api/dag/node-dependencies"](
            NodeDependenciesUpdateRequest(
                dag_path=str(dag_path),
                task_id="alpha",
                dependencies=["missing"],
            )
        )
    except ProtocolError as exc:
        assert "unknown dependency" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_api_update_node_dependencies_rejects_cycles(tmp_path: Path) -> None:
    dag_path = tmp_path / "dag.yaml"
    dag_path.write_text(
        """
schema_version: "1"
project: dependency-test
default_review_model: gpt-5
nodes:
  - id: alpha
    title: Alpha
    goal: Do alpha
    dependencies: []
    target_files: [src/a.py]
    context_files: []
    allowed_models: [gpt-5-mini]
    recommended_model: gpt-5-mini
    risk_level: low
    review_gate: auto_pass
    acceptance_criteria: []
    verification_commands: []
    do_not: []
    prompt_template: "Alpha ${id}"
    failure_policy: retry_same_model
  - id: beta
    title: Beta
    goal: Do beta
    dependencies: [alpha]
    target_files: [src/b.py]
    context_files: []
    allowed_models: [gpt-5]
    recommended_model: gpt-5
    risk_level: medium
    review_gate: human_review
    acceptance_criteria: []
    verification_commands: []
    do_not: []
    prompt_template: "Beta ${id}"
    failure_policy: send_to_human
""".strip()
        + "\n",
        encoding="utf-8",
    )

    endpoints = _api_endpoints()
    try:
        endpoints["/api/dag/node-dependencies"](
            NodeDependenciesUpdateRequest(
                dag_path=str(dag_path),
                task_id="alpha",
                dependencies=["beta"],
            )
        )
    except ProtocolError as exc:
        assert "Cycle detected" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_api_create_node_returns_created_node(tmp_path: Path) -> None:
    dag_path = tmp_path / "dag.yaml"
    dag_path.write_text(
        """
schema_version: "1"
project: create-node-test
default_review_model: gpt-5
nodes:
  - id: alpha
    title: Alpha
    goal: Do alpha
    dependencies: []
    target_files: [src/a.py]
    context_files: []
    allowed_models: [gpt-5-mini, gpt-5]
    recommended_model: gpt-5-mini
    risk_level: low
    review_gate: auto_pass
    acceptance_criteria: []
    verification_commands: []
    do_not: []
    prompt_template: "Alpha ${id}"
    failure_policy: retry_same_model
    outputs: []
    tags: [core]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    endpoints = _api_endpoints()
    response = endpoints["/api/dag/nodes"](
        CreateNodeRequest(
            dag_path=str(dag_path),
            node={
                "id": "beta",
                "title": "Beta",
                "goal": "Do beta",
                "dependencies": ["alpha"],
                "target_files": ["src/b.py"],
                "context_files": [],
                "allowed_models": ["gpt-5"],
                "recommended_model": "gpt-5",
                "risk_level": "medium",
                "review_gate": "human_review",
                "acceptance_criteria": ["done"],
                "verification_commands": ["pytest -q"],
                "do_not": ["do not drift"],
                "prompt_template": "Beta ${id}",
                "failure_policy": "send_to_human",
                "outputs": ["patch"],
                "tags": ["new"],
            },
        )
    )

    assert response["path"] == str(dag_path)
    assert response["backup_path"].endswith(".bak")
    assert response["node"]["id"] == "beta"
    assert load_dag(dag_path).nodes["beta"].dependencies == ["alpha"]


def test_api_create_node_rejects_missing_required_field(tmp_path: Path) -> None:
    dag_path = tmp_path / "dag.yaml"
    dag_path.write_text(
        """
schema_version: "1"
project: create-node-test
default_review_model: gpt-5
nodes:
  - id: alpha
    title: Alpha
    goal: Do alpha
    dependencies: []
    target_files: [src/a.py]
    context_files: []
    allowed_models: [gpt-5-mini]
    recommended_model: gpt-5-mini
    risk_level: low
    review_gate: auto_pass
    acceptance_criteria: []
    verification_commands: []
    do_not: []
    prompt_template: "Alpha ${id}"
    failure_policy: retry_same_model
""".strip()
        + "\n",
        encoding="utf-8",
    )

    endpoints = _api_endpoints()
    try:
        endpoints["/api/dag/nodes"](
            CreateNodeRequest(
                dag_path=str(dag_path),
                node={
                    "id": "beta",
                    "title": "Beta",
                    "dependencies": [],
                    "target_files": ["src/b.py"],
                    "context_files": [],
                    "allowed_models": ["gpt-5-mini"],
                    "recommended_model": "gpt-5-mini",
                    "risk_level": "low",
                    "review_gate": "auto_pass",
                    "acceptance_criteria": [],
                    "verification_commands": [],
                    "do_not": [],
                    "prompt_template": "Beta ${id}",
                    "failure_policy": "retry_same_model",
                },
            )
        )
    except ProtocolError as exc:
        assert "missing required fields" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")
