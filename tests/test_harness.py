from pathlib import Path

import yaml

from bureauless.agents import CommandOutput, doctor_agent, list_agent_specs
from bureauless.cli import main
from bureauless.core import ProtocolError
from bureauless.protocol import (
    append_ledger_event,
    estimate_cost_from_snapshot,
    export_assignment,
    import_result_proposal,
    load_assignment,
    load_price_snapshot,
    load_result_proposal,
    render_assignment_prompt,
    sha256_file,
    validate_artifact_record,
    verify_ledger_artifacts,
)
from bureauless.protocol.harness import (
    Ledger,
    Workflow,
    compile_workflow,
    load_ledger,
    load_mission,
    load_workflow,
)
from bureauless.runtime import evaluate_gatekeeper, replay_workflow, summarize_metrics
from bureauless.runtime.sessions import (
    cancel_session_record,
    create_session_spec,
    load_session_record,
    run_session,
)


def _workflow(overrides: dict | None = None) -> Workflow:
    data = {
        "workflow_id": "test-workflow",
        "mission_id": "demo",
        "mode": "small_dag",
        "roles": {
            "coder": {
                "can_emit": ["patch_ready"],
                "can_consume": [],
            },
            "reviewer": {
                "can_emit": ["review_approved"],
                "can_consume": ["patch_ready"],
            },
            "committer": {
                "can_emit": ["commit_created"],
                "can_consume": ["patch_ready", "review_approved"],
            },
        },
        "events": {
            "patch_ready": {"producer_roles": ["coder"]},
            "review_approved": {"producer_roles": ["reviewer"]},
            "commit_created": {"producer_roles": ["committer"]},
        },
        "nodes": [
            {"id": "implement", "role": "coder", "emits": ["patch_ready"]},
            {
                "id": "review",
                "role": "reviewer",
                "waits_for": {"all_of": ["patch_ready"]},
                "emits": ["review_approved"],
            },
            {
                "id": "commit",
                "role": "committer",
                "waits_for": {"all_of": ["patch_ready", "review_approved"]},
                "emits": ["commit_created"],
            },
        ],
        "terminal_events": ["commit_created"],
    }
    if overrides:
        data.update(overrides)
    return Workflow.from_dict(data)


def test_loads_demo_mission_and_ledger() -> None:
    mission = load_mission(Path("examples/missions/demo/mission.yaml"))
    ledger = load_ledger(Path("examples/missions/demo/ledger.yaml"))

    assert mission.mission_id == "demo"
    assert mission.default_mode == "single_agent"
    assert ledger.current_plan_ref == "workflows/coder_reviewer_committer.yaml"


def test_compiles_valid_workflow() -> None:
    workflow = load_workflow(Path("examples/missions/demo/workflows/coder_reviewer_committer.yaml"))
    result = compile_workflow(workflow)

    assert result.ok
    assert result.errors == []


def test_compiler_requires_terminal_events() -> None:
    result = compile_workflow(_workflow({"terminal_events": []}))

    assert not result.ok
    assert any(error.code == "missing_terminal_events" for error in result.errors)


def test_compiler_rejects_unauthorized_emit() -> None:
    workflow = _workflow(
        {
            "nodes": [
                {"id": "implement", "role": "coder", "emits": ["review_approved"]},
            ],
            "terminal_events": ["review_approved"],
        }
    )
    result = compile_workflow(workflow)

    assert not result.ok
    assert any(error.code == "unauthorized_emit" for error in result.errors)


def test_compiler_rejects_committer_without_review_gate() -> None:
    workflow = _workflow(
        {
            "nodes": [
                {"id": "implement", "role": "coder", "emits": ["patch_ready"]},
                {
                    "id": "commit",
                    "role": "committer",
                    "waits_for": {"all_of": ["patch_ready"]},
                    "emits": ["commit_created"],
                },
            ],
            "terminal_events": ["commit_created"],
        }
    )
    result = compile_workflow(workflow)

    assert not result.ok
    assert any(error.code == "missing_commit_gate" for error in result.errors)


def test_compiler_supports_node_qualified_event_refs() -> None:
    workflow = Workflow.from_dict(
        {
            "workflow_id": "parallel-inventory",
            "mission_id": "demo",
            "mode": "parallel_swarm",
            "roles": {
                "docs_inventory": {"can_emit": ["inventory_complete"], "can_consume": []},
                "tests_inventory": {"can_emit": ["inventory_complete"], "can_consume": []},
                "ledger_acceptor": {
                    "can_emit": ["ledger_updated"],
                    "can_consume": ["inventory_complete"],
                },
            },
            "events": {
                "inventory_complete": {
                    "producer_roles": ["docs_inventory", "tests_inventory"],
                },
                "ledger_updated": {"producer_roles": ["ledger_acceptor"]},
            },
            "nodes": [
                {
                    "id": "docs_inventory",
                    "role": "docs_inventory",
                    "emits": ["inventory_complete"],
                },
                {
                    "id": "tests_inventory",
                    "role": "tests_inventory",
                    "emits": ["inventory_complete"],
                },
                {
                    "id": "merge_inventory",
                    "role": "ledger_acceptor",
                    "waits_for": {
                        "all_of": [
                            "docs_inventory.inventory_complete",
                            "tests_inventory.inventory_complete",
                        ]
                    },
                    "emits": ["ledger_updated"],
                },
            ],
            "terminal_events": ["ledger_updated"],
        }
    )
    result = compile_workflow(workflow)

    assert result.ok


def test_ledger_findings_require_provenance() -> None:
    data = {
        "mission_id": "demo",
        "ledger_version": 1,
        "current_goal": "Goal",
        "current_plan_ref": "workflow.yaml",
        "public_findings": [{"finding_id": "finding-001", "content": "Fact"}],
        "decisions": [],
        "risks": [],
        "artifacts": [],
        "broadcasts": [],
        "open_questions": [],
        "event_log": [],
    }
    try:
        Ledger.from_dict(data)
    except ProtocolError as exc:
        assert "missing provenance" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_appends_valid_workflow_event() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    event = {
        "event_id": "event-001",
        "event_type": "patch_ready",
        "mission_id": "demo",
        "workflow_id": "test-workflow",
        "node_id": "implement",
        "role": "coder",
    }

    updated = append_ledger_event(ledger, event, workflow)

    assert updated.event_log == [event]


def test_cli_appends_ledger_event(tmp_path) -> None:
    ledger_path = tmp_path / "ledger.yaml"
    event_path = tmp_path / "event.yaml"
    ledger_path.write_text(
        yaml.safe_dump(
            {
                "mission_id": "demo",
                "ledger_version": 1,
                "current_goal": "Goal",
                "current_plan_ref": "workflow.yaml",
                "public_findings": [],
                "decisions": [],
                "risks": [],
                "artifacts": [],
                "broadcasts": [],
                "open_questions": [],
                "event_log": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    event_path.write_text(
        yaml.safe_dump(
            {
                "event_id": "event-001",
                "event_type": "patch_ready",
                "mission_id": "demo",
                "workflow_id": "coder-reviewer-committer-001",
                "node_id": "implement",
                "role": "coder",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "ledger",
            "append",
            str(ledger_path),
            str(event_path),
            "--workflow",
            "examples/missions/demo/workflows/coder_reviewer_committer.yaml",
        ]
    )
    ledger = load_ledger(ledger_path)

    assert exit_code == 0
    assert ledger.event_log[0]["event_id"] == "event-001"


def test_rejects_duplicate_or_unknown_ledger_events() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [
                {
                    "event_id": "event-001",
                    "event_type": "patch_ready",
                    "node_id": "implement",
                    "role": "coder",
                }
            ],
        }
    )

    try:
        append_ledger_event(
            ledger,
            {
                "event_id": "event-001",
                "event_type": "review_approved",
                "node_id": "review",
                "role": "reviewer",
            },
            workflow,
        )
    except ProtocolError as exc:
        assert "Duplicate" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")

    try:
        append_ledger_event(
            ledger,
            {
                "event_id": "event-002",
                "event_type": "made_up_event",
            },
            workflow,
        )
    except ProtocolError as exc:
        assert "Unknown ledger event type" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_replay_and_gatekeeper_derive_workflow_state() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )

    initial = evaluate_gatekeeper(workflow, ledger)
    assert initial.ready == ["implement"]
    assert initial.decisions["review"].state == "blocked"

    with_patch = append_ledger_event(
        ledger,
        {
            "event_id": "event-001",
            "event_type": "patch_ready",
            "node_id": "implement",
            "role": "coder",
        },
        workflow,
    )
    patch_state = evaluate_gatekeeper(workflow, with_patch)
    assert patch_state.ready == ["review"]
    assert patch_state.decisions["implement"].state == "completed"
    assert patch_state.decisions["commit"].state == "blocked"

    with_review = append_ledger_event(
        with_patch,
        {
            "event_id": "event-002",
            "event_type": "review_approved",
            "node_id": "review",
            "role": "reviewer",
        },
        workflow,
    )
    review_state = evaluate_gatekeeper(workflow, with_review)
    assert review_state.ready == ["commit"]

    with_commit = append_ledger_event(
        with_review,
        {
            "event_id": "event-003",
            "event_type": "commit_created",
            "node_id": "commit",
            "role": "committer",
        },
        workflow,
    )
    replay = replay_workflow(workflow, with_commit)
    assert replay.terminal_complete
    assert replay.nodes["commit"].state == "completed"


def test_replay_is_deterministic_and_explains_expired_gate() -> None:
    workflow = _workflow(
        {
            "gates": [
                {
                    "id": "commit_gate",
                    "node_id": "commit",
                    "requires": {"all_of": ["patch_ready", "review_approved"]},
                }
            ]
        }
    )
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [
                {
                    "event_id": "event-001",
                    "event_type": "patch_ready",
                    "node_id": "implement",
                    "role": "coder",
                },
                {
                    "event_id": "event-002",
                    "event_type": "review_approved",
                    "node_id": "review",
                    "role": "reviewer",
                },
                {
                    "event_id": "event-003",
                    "event_type": "gate_expired",
                    "gate_id": "commit_gate",
                },
            ],
        }
    )

    first = replay_workflow(workflow, ledger).to_dict()
    second = replay_workflow(workflow, ledger).to_dict()

    assert first == second
    assert first["nodes"]["commit"]["state"] == "blocked"
    assert first["nodes"]["commit"]["blocked_reasons"] == [
        {
            "code": "gate_expired",
            "message": "Gate commit_gate has expired",
            "gate_id": "commit_gate",
        }
    ]


def test_gatekeeper_supports_any_of_waits() -> None:
    workflow = Workflow.from_dict(
        {
            "workflow_id": "any-of-workflow",
            "mission_id": "demo",
            "mode": "small_dag",
            "roles": {
                "inventory": {"can_emit": ["inventory_complete"], "can_consume": []},
                "merge": {
                    "can_emit": ["merge_ready"],
                    "can_consume": ["inventory_complete"],
                },
            },
            "events": {
                "inventory_complete": {"producer_roles": ["inventory"]},
                "merge_ready": {"producer_roles": ["merge"]},
            },
            "nodes": [
                {"id": "docs", "role": "inventory", "emits": ["inventory_complete"]},
                {"id": "tests", "role": "inventory", "emits": ["inventory_complete"]},
                {
                    "id": "merge",
                    "role": "merge",
                    "waits_for": {
                        "any_of": [
                            "docs.inventory_complete",
                            "tests.inventory_complete",
                        ]
                    },
                    "emits": ["merge_ready"],
                },
            ],
            "terminal_events": ["merge_ready"],
        }
    )
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )

    initial = evaluate_gatekeeper(workflow, ledger)
    assert initial.ready == ["docs", "tests"]
    assert initial.decisions["merge"].state == "blocked"
    assert {
        reason.missing_ref for reason in initial.decisions["merge"].blocked_reasons
    } == {"docs.inventory_complete", "tests.inventory_complete"}

    with_docs = append_ledger_event(
        ledger,
        {
            "event_id": "event-001",
            "event_type": "inventory_complete",
            "node_id": "docs",
            "role": "inventory",
        },
        workflow,
    )
    result = evaluate_gatekeeper(workflow, with_docs)

    assert result.ready == ["merge", "tests"]
    assert result.decisions["merge"].blocked_reasons == []


def test_gatekeeper_respects_node_qualified_refs() -> None:
    workflow = Workflow.from_dict(
        {
            "workflow_id": "qualified-workflow",
            "mission_id": "demo",
            "mode": "small_dag",
            "roles": {
                "inventory": {"can_emit": ["inventory_complete"], "can_consume": []},
                "merge": {
                    "can_emit": ["merge_ready"],
                    "can_consume": ["inventory_complete"],
                },
            },
            "events": {
                "inventory_complete": {"producer_roles": ["inventory"]},
                "merge_ready": {"producer_roles": ["merge"]},
            },
            "nodes": [
                {"id": "docs", "role": "inventory", "emits": ["inventory_complete"]},
                {"id": "tests", "role": "inventory", "emits": ["inventory_complete"]},
                {
                    "id": "merge",
                    "role": "merge",
                    "waits_for": {
                        "all_of": [
                            "docs.inventory_complete",
                            "tests.inventory_complete",
                        ]
                    },
                    "emits": ["merge_ready"],
                },
            ],
            "terminal_events": ["merge_ready"],
        }
    )
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [
                {
                    "event_id": "event-001",
                    "event_type": "inventory_complete",
                    "node_id": "docs",
                    "role": "inventory",
                }
            ],
        }
    )

    partial = evaluate_gatekeeper(workflow, ledger)
    assert partial.decisions["merge"].state == "blocked"
    assert partial.decisions["merge"].blocked_reasons[0].missing_ref == (
        "tests.inventory_complete"
    )

    complete = append_ledger_event(
        ledger,
        {
            "event_id": "event-002",
            "event_type": "inventory_complete",
            "node_id": "tests",
            "role": "inventory",
        },
        workflow,
    )
    assert evaluate_gatekeeper(workflow, complete).ready == ["merge"]


def test_artifact_hash_validation(tmp_path) -> None:
    artifact_path = tmp_path / "artifacts" / "report.md"
    artifact_path.parent.mkdir()
    artifact_path.write_text("result", encoding="utf-8")
    digest = sha256_file(artifact_path)

    result = validate_artifact_record(
        {
            "artifact_id": "artifact-001",
            "path": "artifacts/report.md",
            "sha256": digest,
            "created_by": "coder",
            "source_event": "event-001",
            "mutable": False,
        },
        tmp_path,
    )

    assert result.status == "valid"

    artifact_path.write_text("changed", encoding="utf-8")
    changed = validate_artifact_record(
        {
            "artifact_id": "artifact-001",
            "path": "artifacts/report.md",
            "sha256": digest,
            "created_by": "coder",
            "source_event": "event-001",
            "mutable": False,
        },
        tmp_path,
    )
    assert changed.status == "invalid"


def test_artifact_missing_and_mutable_validation(tmp_path) -> None:
    missing = validate_artifact_record(
        {
            "artifact_id": "artifact-001",
            "path": "artifacts/missing.md",
            "sha256": "0" * 64,
            "created_by": "coder",
            "source_event": "event-001",
            "mutable": False,
        },
        tmp_path,
    )
    assert missing.status == "missing"

    try:
        validate_artifact_record(
            {
                "artifact_id": "artifact-002",
                "path": "artifacts/draft.md",
                "sha256": "0" * 64,
                "created_by": "coder",
                "source_event": "event-001",
                "mutable": True,
            },
            tmp_path,
        )
    except ProtocolError as exc:
        assert "mutable: false" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_artifact_path_cannot_escape_root(tmp_path) -> None:
    try:
        validate_artifact_record(
            {
                "artifact_id": "artifact-001",
                "path": "../outside.md",
                "sha256": "0" * 64,
                "created_by": "coder",
                "source_event": "event-001",
                "mutable": False,
            },
            tmp_path,
        )
    except ProtocolError as exc:
        assert "escapes artifact root" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_cli_artifact_verify(tmp_path) -> None:
    artifact_path = tmp_path / "artifacts" / "report.md"
    artifact_path.parent.mkdir()
    artifact_path.write_text("result", encoding="utf-8")
    digest = sha256_file(artifact_path)
    ledger_path = tmp_path / "ledger.yaml"
    ledger_path.write_text(
        yaml.safe_dump(
            {
                "mission_id": "demo",
                "ledger_version": 1,
                "current_goal": "Goal",
                "current_plan_ref": "workflow.yaml",
                "public_findings": [],
                "decisions": [],
                "risks": [],
                "artifacts": [
                    {
                        "artifact_id": "artifact-001",
                        "path": "artifacts/report.md",
                        "sha256": digest,
                        "created_by": "coder",
                        "source_event": "event-001",
                        "mutable": False,
                    }
                ],
                "broadcasts": [],
                "open_questions": [],
                "event_log": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ledger = load_ledger(ledger_path)

    assert main(["artifact", "verify", str(ledger_path), "--root", str(tmp_path)]) == 0
    assert verify_ledger_artifacts(ledger, tmp_path)[0].status == "valid"


def test_exports_assignment_only_for_runnable_node() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )

    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")

    assert assignment.assignment_id == "assign-001"
    assert assignment.expected_events == ["patch_ready"]
    assert "update_canonical_ledger" in assignment.forbidden_actions
    assert "patch_ready" in render_assignment_prompt(assignment)
    assert load_assignment(assignment.to_dict()) == assignment

    try:
        export_assignment(workflow, ledger, "commit")
    except ProtocolError as exc:
        assert "not runnable" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")

    forced = export_assignment(
        workflow,
        ledger,
        "commit",
        assignment_id="assign-forced",
        force=True,
    )
    assert forced.node_id == "commit"
    assert forced.expected_events == ["commit_created"]


def test_cli_assignment_export(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "assignment",
            "export",
            "examples/missions/demo/workflows/coder_reviewer_committer.yaml",
            "examples/missions/demo/ledger.yaml",
            "implement",
            "--assignment-id",
            "assign-demo",
        ]
    )
    captured = capsys.readouterr()
    payload = yaml.safe_load(captured.out)

    assert exit_code == 0
    assert payload["assignment_id"] == "assign-demo"
    assert payload["node_id"] == "implement"
    assert "visible_context" in payload
    assert "update_canonical_ledger" in payload["forbidden_actions"]


def test_cli_assignment_prompt_export(capsys) -> None:
    exit_code = main(
        [
            "assignment",
            "export",
            "examples/missions/demo/workflows/coder_reviewer_committer.yaml",
            "examples/missions/demo/ledger.yaml",
            "implement",
            "--assignment-id",
            "assign-demo",
            "--prompt",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "# Assignment assign-demo" in captured.out
    assert "## Forbidden Actions" in captured.out
    assert "patch_ready" in captured.out


def test_imports_result_proposal_as_event() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    result = load_result_proposal(
        {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "manual-worker",
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "artifacts": [],
            "outcome_metrics": {
                "wall_time_ms": 1000,
                "changed_files_count": 1,
                "usage_confidence": "none",
            },
            "verification": {"status": "passed"},
            "native_log_refs": [],
        }
    )

    updated = import_result_proposal(workflow, ledger, assignment, result)

    assert updated.event_log[0]["event_type"] == "result_submitted"
    assert updated.event_log[0]["result"]["result_id"] == "result-001"
    assert updated.public_findings == []


def test_rejects_result_with_unauthorized_event() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    result = load_result_proposal(
        {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "manual-worker",
            "status": "completed",
            "emitted_events": ["review_approved"],
        }
    )

    try:
        import_result_proposal(workflow, ledger, assignment, result)
    except ProtocolError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_rejects_result_missing_required_outcome_metrics() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    result = load_result_proposal(
        {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "manual-worker",
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "outcome_metrics": {
                "changed_files_count": 1,
            },
        }
    )

    try:
        import_result_proposal(workflow, ledger, assignment, result)
    except ProtocolError as exc:
        assert "wall_time_ms" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_cli_result_import(tmp_path) -> None:
    workflow_path = Path("examples/missions/demo/workflows/coder_reviewer_committer.yaml")
    ledger_path = tmp_path / "ledger.yaml"
    assignment_path = tmp_path / "assignment.yaml"
    result_path = tmp_path / "result.yaml"
    ledger_path.write_text(
        yaml.safe_dump(
            {
                "mission_id": "demo",
                "ledger_version": 1,
                "current_goal": "Goal",
                "current_plan_ref": "workflow.yaml",
                "public_findings": [],
                "decisions": [],
                "risks": [],
                "artifacts": [],
                "broadcasts": [],
                "open_questions": [],
                "event_log": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assignment_path.write_text(
        yaml.safe_dump(
            export_assignment(
                load_workflow(workflow_path),
                load_ledger(ledger_path),
                "implement",
                assignment_id="assign-001",
            ).to_dict(),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    result_path.write_text(
        yaml.safe_dump(
            {
                "result_id": "result-001",
                "assignment_id": "assign-001",
                "agent_id": "manual-worker",
                "status": "completed",
                "emitted_events": ["patch_ready"],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "changed_files_count": 1,
                },
                "verification": {"status": "passed"},
                "native_log_refs": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "result",
            "import",
            str(workflow_path),
            str(ledger_path),
            str(assignment_path),
            str(result_path),
        ]
    )
    updated = load_ledger(ledger_path)

    assert exit_code == 0
    assert updated.public_findings == []
    assert updated.event_log[0]["event_type"] == "result_submitted"


def test_lists_agent_specs() -> None:
    specs = list_agent_specs()
    agent_ids = [spec.agent_id for spec in specs]

    assert agent_ids == ["claude-code", "codex-cli", "opencode"]
    codex = next(spec for spec in specs if spec.agent_id == "codex-cli")
    assert codex.non_interactive_markers == ["exec"]
    assert codex.model_override_markers == ["--model"]
    assert codex.provider_override_markers == ["--config"]
    assert codex.kind == "local_agent_cli"


def test_agent_doctor_reports_missing_binary() -> None:
    result = doctor_agent("codex-cli", which=lambda _binary: None)

    assert result.status == "unavailable"
    assert result.control_level == "none"
    assert result.binary_path is None
    assert result.warnings == ["Binary not found on PATH: codex"]


def test_agent_doctor_detects_high_control_surface() -> None:
    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=0, stdout="codex 1.0\n", stderr="")
        return CommandOutput(
            returncode=0,
            stdout="exec --model --config --ignore-user-config --cd --json --ephemeral",
            stderr="",
        )

    result = doctor_agent(
        "codex-cli",
        which=lambda _binary: "/usr/bin/codex",
        run_command=fake_run,
    )

    assert result.status == "usable"
    assert result.control_level == "high"
    assert result.version == "codex 1.0"
    assert all(check.status == "passed" for check in result.checks)


def test_agent_doctor_degrades_when_required_marker_is_missing() -> None:
    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=0, stdout="opencode 1.0\n", stderr="")
        return CommandOutput(
            returncode=0,
            stdout="run --model --format --pure",
            stderr="",
        )

    result = doctor_agent(
        "opencode",
        which=lambda _binary: "/usr/bin/opencode",
        run_command=fake_run,
    )

    assert result.status == "degraded"
    assert result.control_level == "low"
    failed = {check.name for check in result.checks if check.status == "failed"}
    assert "working_directory" in failed


def test_agent_doctor_emits_warnings_on_failed_help_or_version() -> None:
    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=2, stdout="", stderr="bad version")
        return CommandOutput(returncode=3, stdout="", stderr="bad help")

    result = doctor_agent(
        "codex-cli",
        which=lambda _binary: "/usr/bin/codex",
        run_command=fake_run,
    )

    assert result.status == "degraded"
    assert "Help command exited with 3" in result.warnings
    assert "Version command exited with 2" in result.warnings


def test_cli_agent_list(capsys) -> None:
    exit_code = main(["agent", "list"])
    captured = capsys.readouterr()
    payload = yaml.safe_load(captured.out)

    assert exit_code == 0
    assert [item["agent_id"] for item in payload] == [
        "claude-code",
        "codex-cli",
        "opencode",
    ]
    assert payload[1]["kind"] == "local_agent_cli"


def test_cli_agent_doctor(capsys) -> None:
    exit_code = main(["agent", "doctor", "codex-cli"])
    captured = capsys.readouterr()
    payload = yaml.safe_load(captured.out)

    assert exit_code == 0
    assert payload["agent_id"] == "codex-cli"
    assert payload["status"] in {"usable", "degraded", "unavailable"}
    assert "checks" in payload


def test_fake_session_produces_result_without_touching_ledger(tmp_path) -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="fake",
        workdir=tmp_path,
        session_id="session-001",
    )

    record = run_session(spec, assignment)

    assert record.status == "completed"
    assert record.result_proposal is not None
    assert record.result_proposal["assignment_id"] == "assign-001"
    assert ledger.event_log == []


def test_session_dry_run_and_cancel(tmp_path) -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="fake",
        workdir=tmp_path,
        dry_run=True,
        session_id="session-001",
    )

    record = run_session(spec, assignment)
    cancelled = cancel_session_record(record)

    assert record.status == "dry_run"
    assert record.result_proposal is None
    assert cancelled.status == "cancelled"
    assert cancelled.exit["reason"] == "cancelled"


def test_shell_dummy_session_timeout(tmp_path) -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=tmp_path,
        shell_command="sleep 1",
        timeout_seconds=0.01,
        session_id="session-001",
    )

    record = run_session(spec, assignment)

    assert record.status == "timed_out"
    assert record.exit["reason"] == "timed_out"
    assert record.result_proposal is None


def test_cli_session_run_and_cancel(tmp_path, capsys) -> None:
    assignment_path = tmp_path / "assignment.yaml"
    session_path = tmp_path / "session.yaml"
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )
    assignment_path.write_text(
        yaml.safe_dump(
            export_assignment(workflow, ledger, "implement", assignment_id="assign-001").to_dict(),
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "session",
            "run",
            str(assignment_path),
            "--agent",
            "fake",
            "--session-id",
            "session-001",
        ]
    )
    payload = yaml.safe_load(capsys.readouterr().out)
    session_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["result_proposal"]["assignment_id"] == "assign-001"

    cancel_exit = main(["session", "cancel", str(session_path), "--reason", "user_cancelled"])
    updated = load_session_record(yaml.safe_load(session_path.read_text(encoding="utf-8")))
    capsys.readouterr()

    assert cancel_exit == 0
    assert updated.status == "cancelled"
    assert updated.exit["reason"] == "user_cancelled"


def test_metrics_summarize_session_and_allow_missing_usage(tmp_path) -> None:
    session_path = tmp_path / "session.yaml"
    session_path.write_text(
        yaml.safe_dump(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                "agent_id": "fake",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "changed_files_count": 0,
                    "usage_confidence": "none",
                },
                "result_proposal": {
                    "assignment_id": "assign-001",
                    "agent_id": "fake",
                    "verification": {"status": "not_run"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = summarize_metrics(session_path)

    assert summary["entries"][0]["agent_id"] == "fake"
    assert summary["entries"][0]["total_tokens"] is None
    assert summary["entries"][0]["usage_confidence"] == "none"
    assert summary["entries"][0]["cost_source"] == "unknown"
    assert summary["summary"][0]["missing_usage_count"] == 1


def test_metrics_summarize_ledger_results(tmp_path) -> None:
    ledger_path = tmp_path / "ledger.yaml"
    ledger_path.write_text(
        yaml.safe_dump(
            {
                "mission_id": "demo",
                "ledger_version": 1,
                "current_goal": "Goal",
                "current_plan_ref": "workflow.yaml",
                "public_findings": [],
                "decisions": [],
                "risks": [],
                "artifacts": [],
                "broadcasts": [],
                "open_questions": [],
                "event_log": [
                    {
                        "event_id": "event-001",
                        "event_type": "result_submitted",
                        "result": {
                            "assignment_id": "assign-001",
                            "agent_id": "fake",
                            "status": "completed",
                            "outcome_metrics": {
                                "wall_time_ms": 500,
                                "input_tokens": 20,
                                "output_tokens": 22,
                                "total_tokens": 42,
                                "cost_usd": 0.01,
                                "changed_files_count": 0,
                                "usage_confidence": "high",
                                "cost_source": "adapter_reported",
                                "cost_confidence": "high",
                            },
                            "verification": {"status": "passed"},
                        },
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = summarize_metrics(ledger_path)

    assert summary["entries"][0]["status"] == "completed"
    assert summary["summary"][0]["completed"] == 1
    assert summary["summary"][0]["total_tokens_total"] == 42
    assert summary["entries"][0]["cost_source"] == "adapter_reported"


def test_cli_metrics_summarize(tmp_path, capsys) -> None:
    session_path = tmp_path / "session.yaml"
    session_path.write_text(
        yaml.safe_dump(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                "agent_id": "fake",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {"wall_time_ms": 1000, "changed_files_count": 0},
                "result_proposal": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(["metrics", "summarize", str(session_path)])
    payload = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["entries"][0]["assignment_id"] == "assign-001"


def test_budget_snapshot_estimates_token_cost_and_preserves_unknowns(tmp_path) -> None:
    snapshot_path = tmp_path / "prices.yaml"
    snapshot_path.write_text(
        yaml.safe_dump(
            {
                "snapshot_id": "price-snapshot-2026-06-20",
                "provider": "mixed",
                "captured_at": "2026-06-20T00:00:00Z",
                "currency": "USD",
                "source": "manual",
                "models": {
                    "gpt-5-mini": {
                        "provider": "openai",
                        "pricing_model": "token",
                        "input_per_million": 0.5,
                        "output_per_million": 1.0,
                        "source": "manual",
                        "confidence": "high",
                    },
                    "m3": {
                        "provider": "minimax",
                        "pricing_model": "bundled_quota",
                        "source": "manual",
                        "confidence": "low",
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    snapshot = load_price_snapshot(snapshot_path)

    token_estimate = estimate_cost_from_snapshot(snapshot, "gpt-5-mini", 1000, 2000)
    bundled_estimate = estimate_cost_from_snapshot(snapshot, "m3", 1000, 2000)
    unknown_estimate = estimate_cost_from_snapshot(snapshot, "unknown-model", 1000, 2000)

    assert token_estimate.cost_usd == 0.0025
    assert token_estimate.source == "manual"
    assert token_estimate.confidence == "high"
    assert bundled_estimate.cost_usd is None
    assert bundled_estimate.pricing_model == "bundled_quota"
    assert bundled_estimate.confidence == "low"
    assert unknown_estimate.cost_usd is None
    assert unknown_estimate.source == "price_snapshot_missing_model"


def test_metrics_summarize_can_apply_price_snapshot(tmp_path) -> None:
    session_path = tmp_path / "session.yaml"
    snapshot_path = tmp_path / "prices.yaml"
    session_path.write_text(
        yaml.safe_dump(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                "agent_id": "fake",
                "effective_model": "gpt-5-mini",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "input_tokens": 1000,
                    "output_tokens": 2000,
                    "total_tokens": 3000,
                    "changed_files_count": 0,
                },
                "result_proposal": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    snapshot_path.write_text(
        yaml.safe_dump(
            {
                "snapshot_id": "price-snapshot-2026-06-20",
                "provider": "mixed",
                "captured_at": "2026-06-20T00:00:00Z",
                "currency": "USD",
                "source": "manual",
                "models": {
                    "gpt-5-mini": {
                        "provider": "openai",
                        "pricing_model": "token",
                        "input_per_million": 0.5,
                        "output_per_million": 1.0,
                        "source": "manual",
                        "confidence": "high",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = summarize_metrics(session_path, snapshot_path)

    assert summary["entries"][0]["cost_usd"] == 0.0025
    assert summary["entries"][0]["cost_source"] == "manual"
    assert summary["entries"][0]["cost_confidence"] == "high"
