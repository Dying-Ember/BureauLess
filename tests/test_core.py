from pathlib import Path

from agents_swarm.core import (
    Dag,
    ProtocolError,
    create_run_record,
    dag_documents_match,
    load_dag,
    load_run_records,
    ready_nodes,
    render_prompt,
    update_review_status,
    write_dag_json,
    write_run_record,
)


def _dag() -> Dag:
    return Dag.from_dict(
        {
            "schema_version": "0.1",
            "project": "test",
            "default_review_model": "gpt-5",
            "nodes": [
                {
                    "id": "a",
                    "title": "A",
                    "goal": "Do A",
                    "dependencies": [],
                    "target_files": ["docs/"],
                    "allowed_models": ["mini", "large"],
                    "recommended_model": "mini",
                    "risk_level": "low",
                    "review_gate": "auto_pass",
                    "acceptance_criteria": ["A done"],
                    "verification_commands": [],
                    "do_not": ["Change runtime"],
                    "prompt_template": "Execute ${id}",
                    "failure_policy": "retry_same_model",
                },
                {
                    "id": "b",
                    "title": "B",
                    "goal": "Do B",
                    "dependencies": ["a"],
                    "target_files": ["src/"],
                    "allowed_models": ["large"],
                    "recommended_model": "large",
                    "risk_level": "high",
                    "review_gate": "orchestrator_review",
                    "acceptance_criteria": ["B done"],
                    "verification_commands": ["pytest -q"],
                    "do_not": ["Rewrite everything"],
                    "prompt_template": "Execute ${title}",
                    "failure_policy": "escalate_to_large_model",
                },
            ],
        }
    )


def test_ready_nodes_respect_dependencies_and_review_gate() -> None:
    dag = _dag()
    assert [node.id for node in ready_nodes(dag, [])] == ["a"]

    a_record = create_run_record(dag, "a", model="mini", status="passed")
    assert [node.id for node in ready_nodes(dag, [a_record])] == ["b"]

    b_pending = create_run_record(dag, "b", model="large", status="passed")
    assert [node.id for node in ready_nodes(dag, [a_record, b_pending])] == []


def test_render_prompt_includes_model_and_boundaries() -> None:
    prompt = render_prompt(_dag(), "b")
    assert "Recommended model: large" in prompt
    assert "- Rewrite everything" in prompt
    assert "Execute B" in prompt


def test_recommended_model_must_be_allowed() -> None:
    data = {
        "schema_version": "0.1",
        "project": "bad",
        "default_review_model": "large",
        "nodes": [
            {
                "id": "x",
                "title": "X",
                "goal": "Bad",
                "dependencies": [],
                "target_files": [],
                "allowed_models": ["mini"],
                "recommended_model": "large",
                "risk_level": "low",
                "review_gate": "auto_pass",
                "acceptance_criteria": [],
                "verification_commands": [],
                "do_not": [],
                "prompt_template": "x",
                "failure_policy": "retry_same_model",
            }
        ],
    }
    try:
        Dag.from_dict(data)
    except ProtocolError as exc:
        assert "recommended_model" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_review_update_unlocks_downstream_node(tmp_path) -> None:
    dag = Dag.from_dict(
        {
            "schema_version": "0.1",
            "project": "review-test",
            "default_review_model": "large",
            "nodes": [
                {
                    "id": "reviewed",
                    "title": "Reviewed",
                    "goal": "Needs review",
                    "dependencies": [],
                    "target_files": [],
                    "allowed_models": ["large"],
                    "recommended_model": "large",
                    "risk_level": "medium",
                    "review_gate": "orchestrator_review",
                    "acceptance_criteria": [],
                    "verification_commands": [],
                    "do_not": [],
                    "prompt_template": "x",
                    "failure_policy": "send_to_human",
                },
                {
                    "id": "after",
                    "title": "After",
                    "goal": "Runs after review",
                    "dependencies": ["reviewed"],
                    "target_files": [],
                    "allowed_models": ["large"],
                    "recommended_model": "large",
                    "risk_level": "low",
                    "review_gate": "auto_pass",
                    "acceptance_criteria": [],
                    "verification_commands": [],
                    "do_not": [],
                    "prompt_template": "x",
                    "failure_policy": "retry_same_model",
                },
            ],
        }
    )
    record = create_run_record(dag, "reviewed", model="large", status="passed")
    write_run_record(tmp_path, record)

    assert [node.id for node in ready_nodes(dag, [record])] == []

    update_review_status(dag, tmp_path, "reviewed", "orchestrator_approved")
    records = load_run_records(tmp_path)
    assert [node.id for node in ready_nodes(dag, records)] == ["after"]


def test_load_yaml_dag() -> None:
    dag = load_dag(Path("examples/optimization_dag.yaml"))
    assert dag.project == "automation-inspection-optimization"
    assert dag.nodes["baseline-inventory"].recommended_model == "gpt-5-mini"


def test_yaml_and_json_examples_are_synced() -> None:
    assert dag_documents_match(
        Path("examples/optimization_dag.yaml"),
        Path("examples/optimization_dag.json"),
    )


def test_export_json_round_trip(tmp_path) -> None:
    dag = load_dag(Path("examples/optimization_dag.yaml"))
    output = write_dag_json(dag, tmp_path / "dag.json")
    assert load_dag(output).to_dict() == dag.to_dict()
