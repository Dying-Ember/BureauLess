from pathlib import Path

from agents_swarm.core import create_run_record, load_dag, write_run_record
from agents_swarm.server import dag_payload, state_payload, update_review_status


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
    from agents_swarm.core import render_prompt

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
