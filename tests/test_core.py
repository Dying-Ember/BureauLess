from pathlib import Path

import yaml

from bureauless.core import (
    Dag,
    ProtocolError,
    create_node,
    create_run_record,
    load_dag,
    load_run_records,
    ready_nodes,
    render_prompt,
    update_node_dependencies,
    update_node_metadata,
    update_review_status,
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


def test_rejects_non_yaml_dag_path(tmp_path) -> None:
    path = tmp_path / "dag.txt"
    path.write_text("{}", encoding="utf-8")
    try:
        load_dag(path)
    except ProtocolError as exc:
        assert ".yaml or .yml" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_run_records_are_written_as_yaml(tmp_path) -> None:
    dag = _dag()
    record = create_run_record(dag, "a", model="mini", status="passed")
    path = write_run_record(tmp_path, record)
    assert path.suffix == ".yaml"
    records = load_run_records(tmp_path)
    assert records[0]["task_id"] == "a"


def test_update_node_metadata_updates_one_field_and_creates_backup(tmp_path) -> None:
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
    context_files: [docs/a.md]
    allowed_models: [gpt-5-mini, gpt-5]
    recommended_model: gpt-5-mini
    risk_level: low
    review_gate: auto_pass
    acceptance_criteria: [done]
    verification_commands: [pytest -q]
    do_not: [break api]
    prompt_template: "Alpha ${id}"
    failure_policy: retry_same_model
    outputs: [report.md]
    tags: [core]
    owner_hint: team-a
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
    acceptance_criteria: [done]
    verification_commands: []
    do_not: []
    prompt_template: "Beta ${id}"
    failure_policy: send_to_human
    tags: [followup]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    path, backup_path, dag = update_node_metadata(
        dag_path,
        "alpha",
        {"risk_level": "medium"},
    )

    assert path == dag_path
    assert backup_path.exists()
    assert dag.nodes["alpha"].risk_level == "medium"
    assert load_dag(path).nodes["alpha"].risk_level == "medium"
    assert "risk_level: low" in backup_path.read_text(encoding="utf-8")


def test_update_node_metadata_rejects_invalid_enum_value(tmp_path) -> None:
    dag_path = tmp_path / "dag.yaml"
    original = """
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
""".strip() + "\n"
    dag_path.write_text(original, encoding="utf-8")

    try:
        update_node_metadata(dag_path, "alpha", {"review_gate": "ship_it"})
    except ProtocolError as exc:
        assert "invalid review_gate" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")

    assert dag_path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("*.bak")) == []


def test_update_node_metadata_preserves_unrelated_fields_and_node_order(tmp_path) -> None:
    dag_path = tmp_path / "dag.yaml"
    dag_path.write_text(
        """
schema_version: "1"
project: metadata-test
default_review_model: gpt-5
extra_top_level:
  owner: workbench
nodes:
  - id: alpha
    title: Alpha
    goal: Do alpha
    dependencies: []
    target_files: [src/a.py]
    context_files: [docs/a.md]
    allowed_models: [gpt-5-mini, gpt-5]
    recommended_model: gpt-5-mini
    risk_level: low
    review_gate: auto_pass
    acceptance_criteria: [done]
    verification_commands: [pytest -q]
    do_not: [break api]
    prompt_template: "Alpha ${id}"
    failure_policy: retry_same_model
    tags: [core]
    owner_hint: team-a
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
    acceptance_criteria: [done]
    verification_commands: []
    do_not: []
    prompt_template: "Beta ${id}"
    failure_policy: send_to_human
    tags: [followup]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    update_node_metadata(dag_path, "alpha", {"tags": ["core", "ui"]})

    with dag_path.open("r", encoding="utf-8") as handle:
        written = yaml.safe_load(handle)

    assert written["extra_top_level"] == {"owner": "workbench"}
    assert [node["id"] for node in written["nodes"]] == ["alpha", "beta"]
    assert written["nodes"][0]["dependencies"] == []
    assert written["nodes"][0]["prompt_template"] == "Alpha ${id}"
    assert written["nodes"][0]["owner_hint"] == "team-a"
    assert written["nodes"][0]["tags"] == ["core", "ui"]
    assert load_dag(dag_path).nodes["beta"].dependencies == ["alpha"]


def test_update_node_dependencies_updates_existing_node_and_creates_backup(tmp_path) -> None:
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

    path, backup_path, dag = update_node_dependencies(dag_path, "beta", ["alpha"])

    assert path == dag_path
    assert backup_path.exists()
    assert dag.nodes["beta"].dependencies == ["alpha"]
    assert load_dag(dag_path).nodes["beta"].dependencies == ["alpha"]
    assert "dependencies: []" in backup_path.read_text(encoding="utf-8")


def test_update_node_dependencies_rejects_unknown_dependency(tmp_path) -> None:
    dag_path = tmp_path / "dag.yaml"
    original = """
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
""".strip() + "\n"
    dag_path.write_text(original, encoding="utf-8")

    try:
        update_node_dependencies(dag_path, "alpha", ["missing"])
    except ProtocolError as exc:
        assert "unknown dependency" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")

    assert dag_path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("*.bak")) == []


def test_update_node_dependencies_rejects_cycles(tmp_path) -> None:
    dag_path = tmp_path / "dag.yaml"
    original = """
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
""".strip() + "\n"
    dag_path.write_text(original, encoding="utf-8")

    try:
        update_node_dependencies(dag_path, "alpha", ["beta"])
    except ProtocolError as exc:
        assert "Cycle detected" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")

    assert dag_path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("*.bak")) == []


def test_create_node_appends_node_and_creates_backup(tmp_path) -> None:
    dag_path = tmp_path / "dag.yaml"
    dag_path.write_text(
        """
schema_version: "1"
project: create-node-test
default_review_model: gpt-5
extra_top_level:
  owner: workbench
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

    path, backup_path, dag = create_node(
        dag_path,
        {
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

    with dag_path.open("r", encoding="utf-8") as handle:
        written = yaml.safe_load(handle)

    assert path == dag_path
    assert backup_path.exists()
    assert written["extra_top_level"] == {"owner": "workbench"}
    assert [node["id"] for node in written["nodes"]] == ["alpha", "beta"]
    assert dag.nodes["beta"].dependencies == ["alpha"]


def test_create_node_rejects_missing_required_field(tmp_path) -> None:
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

    try:
        create_node(
            dag_path,
            {
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
    except ProtocolError as exc:
        assert "missing required fields" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")
