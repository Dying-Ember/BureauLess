from pathlib import Path
from dataclasses import replace
import subprocess

import pytest
import yaml

from bureauless.agents import (
    CommandOutput,
    assess_agent_compatibility,
    assess_dispatch_readiness,
    doctor_agent,
    list_agent_compatibility,
    list_agent_specs,
    resolve_agent_binding,
)
from bureauless.cli import main
from bureauless.cli.main import prepare_mutation_demo_workspace, run_live_demo
from bureauless.core import ProtocolError
from bureauless.protocol import (
    append_ledger_event,
    build_node_outcome_decision_event,
    estimate_cost_from_snapshot,
    evaluate_pre_dispatch_policy,
    export_assignment,
    import_result_proposal,
    load_assignment,
    load_price_snapshot,
    load_result_proposal,
    load_node_outcome,
    materialize_current_workflow,
    node_outcome_from_session,
    render_assignment_prompt,
    sha256_file,
    validate_artifact_record,
    validate_workflow_mutation_proposal,
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
from bureauless.runtime import (
    build_mutation_supersession_events,
    evaluate_assignment_impacts,
    evaluate_gatekeeper,
    replay_workflow,
    summarize_metrics,
)
from bureauless.runtime.sessions import (
    assess_workspace_isolation,
    build_assignment_created_event,
    build_session_terminal_event,
    cancel_session_record,
    create_session_spec,
    import_session_record,
    load_session_record,
    package_session_result,
    run_session,
    supersede_session_record,
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


def _mutation_proposal(overrides: dict | None = None) -> dict:
    data = {
        "proposal_id": "mutation-001",
        "proposal_type": "workflow_mutation",
        "workflow_id": "test-workflow",
        "source": {
            "assignment_id": "assign-001",
            "session_id": "session-001",
            "actor": "worker",
        },
        "reason": "discovered_missing_dependency",
        "rationale": "Review needs a focused verification step before approval.",
        "proposed_changes": {
            "add_nodes": [
                {
                    "id": "verify",
                    "role": "reviewer",
                    "waits_for": {"all_of": ["implement.patch_ready"]},
                    "emits": ["review_approved"],
                }
            ],
            "add_edges": [
                {
                    "from_node": "verify",
                    "to_node": "commit",
                    "event": "review_approved",
                }
            ],
            "remove_edges": [],
            "supersede_assignments": ["assign-review-001"],
        },
        "evidence_refs": ["artifact-impact-report"],
        "requires_approval": "orchestrator",
    }
    if overrides:
        data.update(overrides)
    return data


def _empty_ledger() -> Ledger:
    return Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Test controlled workflow mutation.",
            "current_plan_ref": "test-workflow",
            "public_findings": [],
            "decisions": [],
            "risks": [],
            "artifacts": [],
            "broadcasts": [],
            "open_questions": [],
            "event_log": [],
        }
    )


def _mutation_workflow() -> Workflow:
    return Workflow.from_dict(
        {
            "workflow_id": "test-workflow",
            "mission_id": "demo",
            "mode": "small_dag",
            "roles": {
                "producer": {
                    "can_emit": ["ready"],
                    "can_consume": ["done"],
                },
                "consumer": {
                    "can_emit": ["done"],
                    "can_consume": ["ready"],
                },
            },
            "events": {
                "ready": {"producer_roles": ["producer"]},
                "done": {"producer_roles": ["consumer"]},
            },
            "nodes": [
                {
                    "id": "start",
                    "role": "producer",
                    "waits_for": [],
                    "emits": ["ready"],
                },
                {
                    "id": "finish",
                    "role": "consumer",
                    "waits_for": [],
                    "emits": ["done"],
                },
            ],
            "gates": [],
            "terminal_events": ["done"],
        }
    )


def _impact_workflows() -> tuple[Workflow, Workflow]:
    base = {
        "workflow_id": "test-workflow",
        "mission_id": "demo",
        "mode": "small_dag",
        "roles": {
            "worker": {
                "can_emit": ["b_done", "c_done", "d_done", "x_done"],
                "can_consume": ["b_done", "c_done", "d_done", "x_done"],
            }
        },
        "events": {
            event: {"producer_roles": ["worker"]}
            for event in ("b_done", "c_done", "d_done", "x_done")
        },
        "gates": [],
        "terminal_events": ["d_done", "x_done"],
    }
    before = Workflow.from_dict(
        {
            **base,
            "nodes": [
                {"id": "B", "role": "worker", "waits_for": [], "emits": ["b_done"]},
                {
                    "id": "D",
                    "role": "worker",
                    "waits_for": ["B.b_done"],
                    "emits": ["d_done"],
                },
                {
                    "id": "E",
                    "role": "worker",
                    "waits_for": ["D.d_done"],
                    "emits": ["x_done"],
                },
                {"id": "X", "role": "worker", "waits_for": [], "emits": ["x_done"]},
            ],
        }
    )
    after = Workflow.from_dict(
        {
            **base,
            "nodes": [
                {"id": "B", "role": "worker", "waits_for": [], "emits": ["b_done"]},
                {
                    "id": "C",
                    "role": "worker",
                    "waits_for": ["B.b_done"],
                    "emits": ["c_done"],
                },
                {
                    "id": "D",
                    "role": "worker",
                    "waits_for": ["C.c_done"],
                    "emits": ["d_done"],
                },
                {
                    "id": "E",
                    "role": "worker",
                    "waits_for": ["D.d_done"],
                    "emits": ["x_done"],
                },
                {"id": "X", "role": "worker", "waits_for": [], "emits": ["x_done"]},
            ],
        }
    )
    return before, after


def _mutation_proposed_event() -> dict:
    return {
        "event_id": "event-mutation-001",
        "event_type": "workflow_mutation_proposed",
        "mission_id": "demo",
        "workflow_id": "test-workflow",
        "mutation_proposal": _mutation_proposal(),
    }


def test_validates_inert_workflow_mutation_proposal() -> None:
    workflow = _workflow()
    original_nodes = list(workflow.nodes)

    result = validate_workflow_mutation_proposal(_mutation_proposal())

    assert result.ok
    assert result.errors == []
    assert result.proposal is not None
    assert result.proposal.proposed_changes.add_edges[0].event_ref == (
        "verify.review_approved"
    )
    assert result.proposal.to_dict()["proposed_changes"]["add_nodes"][0][
        "waits_for"
    ] == ["implement.patch_ready"]
    assert list(workflow.nodes) == original_nodes


def test_prepares_isolated_mutation_e2e_demo(tmp_path) -> None:
    paths = prepare_mutation_demo_workspace(tmp_path / "mutation-demo")
    mission = load_mission(paths["mission"])
    workflow = load_workflow(paths["workflow"])
    ledger = load_ledger(paths["ledger"])
    replay = replay_workflow(workflow, ledger)
    artifacts = verify_ledger_artifacts(ledger, tmp_path / "mutation-demo")

    assert mission.mission_id == "mutation-e2e-demo"
    assert compile_workflow(workflow).ok
    assert artifacts[0].status == "valid"
    assert replay.mutation_proposals["event-mutation-proposed"].state == "pending"
    assert replay.mutation_proposals[
        "event-mutation-proposed"
    ].affected_node_ids == ["review"]
    assert replay.nodes["prepare"].state == "completed"


def test_rejects_forbidden_workflow_mutation_operations_with_structured_errors() -> None:
    proposal = _mutation_proposal()
    proposal["proposed_changes"]["ledger_events"] = [
        {"event_id": "rewrite-history"}
    ]
    proposal["proposed_changes"]["create_assignments"] = [
        {"assignment_id": "assign-forged"}
    ]

    result = validate_workflow_mutation_proposal(proposal)

    assert not result.ok
    assert result.proposal is None
    assert {
        error.path for error in result.errors if error.code == "forbidden_mutation_operation"
    } == {
        "proposed_changes.create_assignments",
        "proposed_changes.ledger_events",
    }


def test_rejects_empty_or_ambiguous_workflow_mutation() -> None:
    empty = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [],
                "add_edges": [],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    ambiguous = _mutation_proposal()
    ambiguous["proposed_changes"]["add_edges"] = [
        {"from_node": "verify", "to_node": "commit"}
    ]

    empty_result = validate_workflow_mutation_proposal(empty)
    ambiguous_result = validate_workflow_mutation_proposal(ambiguous)

    assert {error.code for error in empty_result.errors} == {"empty_mutation"}
    assert {error.code for error in ambiguous_result.errors} == {"invalid_schema"}


def test_rejects_conflicting_workflow_mutation_edges() -> None:
    proposal = _mutation_proposal()
    proposal["proposed_changes"]["remove_edges"] = [
        {
            "from_node": "verify",
            "to_node": "commit",
            "event": "review_approved",
        }
    ]

    result = validate_workflow_mutation_proposal(proposal)

    assert not result.ok
    assert {error.code for error in result.errors} == {"conflicting_edge_change"}


def test_records_workflow_mutation_proposal_and_partial_acceptance() -> None:
    workflow = _workflow()
    proposed = append_ledger_event(
        _empty_ledger(), _mutation_proposed_event(), workflow
    )

    accepted = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-accepted-001",
            "event_type": "workflow_mutation_accepted",
            "mission_id": "demo",
            "workflow_id": "test-workflow",
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "applied_changes": {
                "supersede_assignments": ["assign-review-001"],
            },
        },
        workflow,
    )

    assert [event["event_type"] for event in accepted.event_log] == [
        "workflow_mutation_proposed",
        "workflow_mutation_accepted",
    ]
    assert replay_workflow(workflow, accepted).mutation_proposals[
        "event-mutation-001"
    ].affected_node_ids == []


def test_records_workflow_mutation_rejection() -> None:
    workflow = _workflow()
    proposed = append_ledger_event(
        _empty_ledger(), _mutation_proposed_event(), workflow
    )

    rejected = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-rejected-001",
            "event_type": "workflow_mutation_rejected",
            "source_event_id": "event-mutation-001",
            "actor": "human",
            "reason": "The evidence does not justify changing the workflow.",
        },
        workflow,
    )

    assert rejected.event_log[-1]["source_event_id"] == "event-mutation-001"


def test_rejects_mutation_decision_without_valid_proposal_reference() -> None:
    with pytest.raises(ProtocolError, match="must reference an existing"):
        append_ledger_event(
            _empty_ledger(),
            {
                "event_id": "event-mutation-accepted-001",
                "event_type": "workflow_mutation_accepted",
                "source_event_id": "missing-proposal-event",
                "actor": "orchestrator",
                "applied_changes": {"supersede_assignments": ["assign-001"]},
            },
            _workflow(),
        )


def test_rejects_unproposed_mutation_change_and_second_decision() -> None:
    workflow = _workflow()
    proposed = append_ledger_event(
        _empty_ledger(), _mutation_proposed_event(), workflow
    )
    with pytest.raises(ProtocolError, match="not present in the source proposal"):
        append_ledger_event(
            proposed,
            {
                "event_id": "event-mutation-accepted-001",
                "event_type": "workflow_mutation_accepted",
                "source_event_id": "event-mutation-001",
                "actor": "orchestrator",
                "applied_changes": {
                    "supersede_assignments": ["assign-not-proposed"]
                },
            },
            workflow,
        )

    rejected = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-rejected-001",
            "event_type": "workflow_mutation_rejected",
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "reason": "Rejected once.",
        },
        workflow,
    )
    with pytest.raises(ProtocolError, match="already has a decision"):
        append_ledger_event(
            rejected,
            {
                "event_id": "event-mutation-rejected-002",
                "event_type": "workflow_mutation_rejected",
                "source_event_id": "event-mutation-001",
                "actor": "human",
                "reason": "Cannot decide twice.",
            },
            workflow,
        )


def test_imports_completed_result_with_mutation_proposal_ref_without_applying_it() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    result = load_result_proposal(
        {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "worker-001",
            "status": "completed_with_proposal",
            "emitted_events": [],
            "artifacts": [
                {
                    "artifact_id": "artifact-mutation-001",
                    "path": "artifacts/mutation-001.yaml",
                    "sha256": "a" * 64,
                    "created_by": "worker-001",
                    "source_event": "event-result-001",
                    "mutable": False,
                }
            ],
            "mutation_proposal_refs": ["artifact-mutation-001"],
            "outcome_metrics": {
                "wall_time_ms": 10,
                "changed_files_count": 1,
            },
            "verification": {"status": "passed"},
        }
    )

    updated = import_result_proposal(workflow, ledger, assignment, result)

    assert [event["event_type"] for event in updated.event_log] == [
        "result_submitted"
    ]
    assert updated.event_log[0]["result"]["mutation_proposal_refs"] == [
        "artifact-mutation-001"
    ]
    assert workflow.nodes.keys() == _workflow().nodes.keys()


def test_rejects_invalid_result_mutation_proposal_ref_contract() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    result = load_result_proposal(
        {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "worker-001",
            "status": "completed_with_proposal",
            "emitted_events": [],
            "artifacts": [],
            "mutation_proposal_refs": ["artifact-missing"],
            "outcome_metrics": {
                "wall_time_ms": 10,
                "changed_files_count": 0,
            },
        }
    )

    with pytest.raises(ProtocolError, match="does not match a result artifact"):
        import_result_proposal(workflow, ledger, assignment, result)


def test_pending_mutation_blocks_only_affected_workflow_branch() -> None:
    workflow = _workflow(
        {
            "nodes": [
                {"id": "left", "role": "coder", "waits_for": [], "emits": ["patch_ready"]},
                {"id": "right", "role": "coder", "waits_for": [], "emits": ["patch_ready"]},
            ],
            "gates": [],
            "terminal_events": ["patch_ready"],
        }
    )
    proposal = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [
                    {
                        "id": "verify",
                        "role": "coder",
                        "waits_for": [],
                        "emits": ["patch_ready"],
                    }
                ],
                "add_edges": [
                    {
                        "from_node": "verify",
                        "to_node": "left",
                        "event": "patch_ready",
                    }
                ],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = proposal
    ledger = append_ledger_event(_empty_ledger(), proposed_event, workflow)

    replay = replay_workflow(workflow, ledger)
    gatekeeper = evaluate_gatekeeper(workflow, ledger)

    mutation = replay.mutation_proposals["event-mutation-001"]
    assert mutation.state == "pending"
    assert mutation.affected_node_ids == ["left"]
    assert gatekeeper.ready == ["right"]
    assert gatekeeper.decisions["left"].blocked_reasons[0].code == (
        "mutation_pending"
    )


def test_rejected_mutation_releases_affected_workflow_branch() -> None:
    workflow = _workflow(
        {
            "nodes": [
                {"id": "left", "role": "coder", "waits_for": [], "emits": ["patch_ready"]},
                {"id": "right", "role": "coder", "waits_for": [], "emits": ["patch_ready"]},
            ],
            "gates": [],
            "terminal_events": ["patch_ready"],
        }
    )
    proposal = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [],
                "add_edges": [
                    {
                        "from_node": "right",
                        "to_node": "left",
                        "event": "patch_ready",
                    }
                ],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = proposal
    proposed = append_ledger_event(_empty_ledger(), proposed_event, workflow)
    rejected = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-rejected-001",
            "event_type": "workflow_mutation_rejected",
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "reason": "Keep the branches independent.",
        },
        workflow,
    )

    replay = replay_workflow(workflow, rejected)
    gatekeeper = evaluate_gatekeeper(workflow, rejected)

    assert replay.mutation_proposals["event-mutation-001"].state == "rejected"
    assert gatekeeper.ready == ["left", "right"]


def test_materializes_current_workflow_from_accepted_mutation() -> None:
    initial = _mutation_workflow()
    proposal = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [
                    {
                        "id": "verify",
                        "role": "producer",
                        "waits_for": [],
                        "emits": ["ready"],
                    }
                ],
                "add_edges": [
                    {
                        "from_node": "verify",
                        "to_node": "finish",
                        "event": "ready",
                    }
                ],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = proposal
    proposed = append_ledger_event(_empty_ledger(), proposed_event, initial)
    accepted = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-accepted-001",
            "event_type": "workflow_mutation_accepted",
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "applied_changes": proposal["proposed_changes"],
        },
        initial,
    )

    current = materialize_current_workflow(initial, accepted)
    current_again = materialize_current_workflow(initial, accepted)
    replay = replay_workflow(initial, accepted)

    assert list(initial.nodes) == ["start", "finish"]
    assert list(current.nodes) == ["start", "finish", "verify"]
    assert current.nodes["finish"].waits_for_all == ["verify.ready"]
    assert current == current_again
    assert list(replay.nodes) == ["start", "finish", "verify"]
    assert replay.nodes["finish"].state == "blocked"


def test_rejected_mutation_does_not_change_current_workflow() -> None:
    initial = _mutation_workflow()
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [
                    {
                        "id": "verify",
                        "role": "producer",
                        "waits_for": [],
                        "emits": ["ready"],
                    }
                ],
                "add_edges": [],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    proposed = append_ledger_event(_empty_ledger(), proposed_event, initial)
    rejected = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-rejected-001",
            "event_type": "workflow_mutation_rejected",
            "source_event_id": "event-mutation-001",
            "actor": "human",
            "reason": "Not needed.",
        },
        initial,
    )

    assert materialize_current_workflow(initial, rejected) == initial


def test_exports_and_imports_assignment_for_mutation_added_node() -> None:
    initial = _mutation_workflow()
    proposal = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [
                    {
                        "id": "verify",
                        "role": "producer",
                        "waits_for": [],
                        "emits": ["ready"],
                    }
                ],
                "add_edges": [],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = proposal
    ledger = append_ledger_event(_empty_ledger(), proposed_event, initial)
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-mutation-accepted-001",
            "event_type": "workflow_mutation_accepted",
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "applied_changes": proposal["proposed_changes"],
        },
        initial,
    )

    assignment = export_assignment(
        initial, ledger, "verify", assignment_id="assign-verify"
    )
    result = load_result_proposal(
        {
            "result_id": "result-verify",
            "assignment_id": "assign-verify",
            "agent_id": "worker-verify",
            "status": "completed",
            "emitted_events": ["ready"],
            "artifacts": [],
            "outcome_metrics": {
                "wall_time_ms": 5,
                "changed_files_count": 0,
            },
        }
    )
    updated = import_result_proposal(initial, ledger, assignment, result)

    assert assignment.node_id == "verify"
    assert updated.event_log[-1]["node_id"] == "verify"
    assert replay_workflow(initial, updated).nodes["verify"].state == "completed"


def test_rejects_accepted_mutation_that_produces_invalid_workflow() -> None:
    initial = _mutation_workflow()
    proposal = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [],
                "add_edges": [
                    {
                        "from_node": "missing",
                        "to_node": "finish",
                        "event": "ready",
                    }
                ],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = proposal
    proposed = append_ledger_event(_empty_ledger(), proposed_event, initial)
    accepted = append_ledger_event(
        proposed,
        {
            "event_id": "event-mutation-accepted-001",
            "event_type": "workflow_mutation_accepted",
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "applied_changes": proposal["proposed_changes"],
        },
        initial,
    )

    with pytest.raises(ProtocolError, match="unknown source"):
        materialize_current_workflow(initial, accepted)


def test_classifies_changed_dependency_chain_and_unchanged_sibling() -> None:
    before, after = _impact_workflows()
    ledger = append_ledger_event(
        _empty_ledger(),
        {
            "event_id": "event-assign-D",
            "event_type": "assignment_created",
            "assignment_id": "assign-D",
            "node_id": "D",
        },
        before,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-assign-X",
            "event_type": "assignment_created",
            "assignment_id": "assign-X",
            "node_id": "X",
        },
        before,
    )

    impacts = evaluate_assignment_impacts(before, after, ledger)

    assert impacts["assign-D"].classification == "affected"
    assert impacts["assign-D"].reasons == [
        "node_contract_changed",
        "dependency_closure_changed",
    ]
    assert impacts["assign-X"].classification == "unaffected"
    assert impacts["assign-X"].reasons == ["execution_context_unchanged"]


def test_assignment_impact_honors_explicit_supersession_and_ambiguity() -> None:
    before, after = _impact_workflows()
    ledger = append_ledger_event(
        _empty_ledger(),
        {
            "event_id": "event-assign-X",
            "event_type": "assignment_created",
            "assignment_id": "assign-X",
            "node_id": "X",
        },
        before,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-assign-unknown",
            "event_type": "assignment_created",
            "assignment_id": "assign-unknown",
        },
        before,
    )

    impacts = evaluate_assignment_impacts(
        before,
        after,
        ledger,
        {"supersede_assignments": ["assign-X"]},
    )

    assert impacts["assign-X"].classification == "affected"
    assert impacts["assign-X"].reasons == ["explicitly_superseded"]
    assert impacts["assign-unknown"].classification == "needs_review"
    assert impacts["assign-unknown"].reasons == ["assignment_node_missing"]


def test_mutation_supersession_preserves_history_but_revokes_old_success() -> None:
    before, _ = _impact_workflows()
    ledger = append_ledger_event(
        _empty_ledger(),
        {
            "event_id": "event-assign-D",
            "event_type": "assignment_created",
            "assignment_id": "assign-D",
            "node_id": "D",
        },
        before,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-D-done",
            "event_type": "d_done",
            "assignment_id": "assign-D",
            "node_id": "D",
            "role": "worker",
        },
        before,
    )
    assert replay_workflow(before, ledger).nodes["D"].state == "completed"

    proposal = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [
                    {
                        "id": "C",
                        "role": "worker",
                        "waits_for": ["B.b_done"],
                        "emits": ["c_done"],
                    }
                ],
                "add_edges": [
                    {"from_node": "C", "to_node": "D", "event": "c_done"}
                ],
                "remove_edges": [
                    {"from_node": "B", "to_node": "D", "event": "b_done"}
                ],
                "supersede_assignments": [],
            }
        }
    )
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = proposal
    ledger = append_ledger_event(ledger, proposed_event, before)
    accepted_event = {
        "event_id": "event-mutation-accepted-001",
        "event_type": "workflow_mutation_accepted",
        "source_event_id": "event-mutation-001",
        "actor": "orchestrator",
        "applied_changes": proposal["proposed_changes"],
    }
    ledger = append_ledger_event(ledger, accepted_event, before)
    current = materialize_current_workflow(before, ledger)
    impacts = evaluate_assignment_impacts(
        before, current, ledger, accepted_event["applied_changes"]
    )
    supersession_events = build_mutation_supersession_events(
        current, accepted_event, impacts
    )

    assert len(supersession_events) == 1
    assert supersession_events[0]["assignment_id"] == "assign-D"
    assert supersession_events[0]["mutation_event_id"] == (
        "event-mutation-accepted-001"
    )
    ledger = append_ledger_event(ledger, supersession_events[0], current)
    replay = replay_workflow(before, ledger)

    assert any(event["event_id"] == "event-D-done" for event in ledger.event_log)
    assert replay.nodes["D"].state == "blocked"
    assert replay.nodes["D"].emitted_events == []
    assert replay.nodes["D"].assignment_attempts[0].state == "superseded"
    assert replay.nodes["D"].assignment_attempts[0].superseded_by == (
        "event-mutation-accepted-001"
    )
    assert replay.nodes["E"].blocked_reasons[0].code == "superseded"
    assert replay.nodes["E"].blocked_reasons[0].assignment_id == "assign-D"


def test_gatekeeper_blocks_assignment_that_needs_mutation_review() -> None:
    initial = _mutation_workflow()
    ledger = append_ledger_event(
        _empty_ledger(),
        {
            "event_id": "event-assign-verify",
            "event_type": "assignment_created",
            "assignment_id": "assign-verify",
            "node_id": "verify",
        },
    )
    proposal = _mutation_proposal(
        {
            "proposed_changes": {
                "add_nodes": [
                    {
                        "id": "verify",
                        "role": "producer",
                        "waits_for": [],
                        "emits": ["ready"],
                    }
                ],
                "add_edges": [],
                "remove_edges": [],
                "supersede_assignments": [],
            }
        }
    )
    proposed_event = _mutation_proposed_event()
    proposed_event["mutation_proposal"] = proposal
    ledger = append_ledger_event(ledger, proposed_event, initial)
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-mutation-accepted-001",
            "event_type": "workflow_mutation_accepted",
            "source_event_id": "event-mutation-001",
            "actor": "orchestrator",
            "applied_changes": proposal["proposed_changes"],
        },
        initial,
    )

    gatekeeper = evaluate_gatekeeper(initial, ledger)

    assert gatekeeper.decisions["verify"].state == "blocked"
    assert any(
        reason.code == "needs_review"
        and reason.assignment_id == "assign-verify"
        for reason in gatekeeper.decisions["verify"].blocked_reasons
    )


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


def test_load_ledger_rebuilds_projection_when_cursor_missing(tmp_path) -> None:
    ledger_path = tmp_path / "ledger.yaml"
    ledger_path.write_text(
        yaml.safe_dump(
            {
                "mission_id": "demo",
                "ledger_version": 1,
                "current_goal": "Goal",
                "current_plan_ref": "workflow.yaml",
                "public_findings": [
                    {
                        "finding_id": "finding-001",
                        "content": "obsolete",
                        "source_event": "event-001",
                        "source_agent": "worker",
                        "accepted_by": "harness",
                    }
                ],
                "decisions": [{"decision_id": "decision-001"}],
                "risks": [{"risk_id": "risk-001"}],
                "artifacts": [],
                "broadcasts": [],
                "open_questions": [{"question_id": "question-001"}],
                "event_log": [
                    {
                        "event_id": "event-001",
                        "event_type": "node_outcome_decided",
                        "mission_id": "demo",
                        "workflow_id": "test-workflow",
                        "assignment_id": "assign-001",
                        "node_id": "implement",
                        "role": "coder",
                        "agent_id": "codex-cli",
                        "session_id": "session-001",
                        "source_outcome_id": "outcome-001",
                        "outcome_status": "completed",
                        "actor": "harness",
                        "disposition": "accepted",
                        "accepted_event_types": ["patch_ready"],
                        "post_state_ref": "workspace:abc123",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    loaded = load_ledger(ledger_path)

    assert loaded.public_findings == []
    assert loaded.decisions == []
    assert loaded.risks == []
    assert loaded.open_questions == []
    assert loaded.projection["through_event_id"] == "event-001"
    assert loaded.projection["accepted_workspace_ref"] == "workspace:abc123"


def test_appends_valid_workflow_event() -> None:
    workflow = _workflow()
    ledger = Ledger.from_dict(
        {
            "mission_id": "demo",
            "ledger_version": 1,
            "current_goal": "Goal",
            "current_plan_ref": "workflow.yaml",
            "projection": {},
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
    assert updated.event_log[1]["event_type"] == "patch_ready"
    assert updated.event_log[1]["source_event_id"] == "event-result-001"
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
    assert updated.event_log[1]["event_type"] == "patch_ready"


def test_cli_session_import(tmp_path, capsys) -> None:
    workflow_path = Path("examples/missions/demo/workflows/coder_reviewer_committer.yaml")
    ledger_path = tmp_path / "ledger.yaml"
    assignment_path = tmp_path / "assignment.yaml"
    session_path = tmp_path / "session.yaml"
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
    assignment = export_assignment(
        load_workflow(workflow_path),
        load_ledger(ledger_path),
        "implement",
        assignment_id="assign-001",
    )
    assignment_path.write_text(yaml.safe_dump(assignment.to_dict(), sort_keys=False), encoding="utf-8")
    session_path.write_text(
        yaml.safe_dump(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                "agent_id": "codex-cli",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "workspace": {
                    "path": str(tmp_path),
                    "source_root": str(tmp_path),
                    "session_root": str(tmp_path),
                },
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "changed_files_count": 0,
                },
                "extraction": {"status": "native_stream_captured"},
                "result_proposal": {
                    "result_id": "result-session-001",
                    "assignment_id": "assign-001",
                    "agent_id": "codex-cli",
                    "status": "completed",
                    "effective_model": "gpt-5.4-mini",
                    "effective_provider": "openai-compatible",
                    "emitted_events": ["patch_ready"],
                    "artifacts": [],
                    "outcome_metrics": {
                        "wall_time_ms": 1000,
                        "changed_files_count": 0,
                    },
                    "verification": {"status": "passed"},
                    "native_log_refs": [],
                    "mutation_proposal_refs": [],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "session",
            "import",
            str(workflow_path),
            str(ledger_path),
            str(assignment_path),
            str(session_path),
        ]
    )
    updated = load_ledger(ledger_path)
    payload = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert [event["event_type"] for event in updated.event_log] == [
        "result_submitted",
        "patch_ready",
        "node_outcome_decided",
    ]
    assert payload[-1]["event_type"] == "node_outcome_decided"


def test_result_import_advances_gatekeeper_and_replay_state() -> None:
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
            },
            "verification": {"status": "passed"},
            "native_log_refs": [],
        }
    )

    updated = import_result_proposal(workflow, ledger, assignment, result)
    gatekeeper = evaluate_gatekeeper(workflow, updated)
    replay = replay_workflow(workflow, updated)

    assert gatekeeper.ready == ["review"]
    assert replay.nodes["implement"].state == "completed"
    assert replay.nodes["review"].state == "runnable"


def test_builds_node_outcome_from_session_record() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    session_record = {
        "session_id": "session-001",
        "assignment_id": "assign-001",
        "agent_id": "codex-cli",
        "status": "completed",
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:00:01Z",
        "exit": {"code": 0, "reason": "completed"},
        "native_logs": {"stdout": "", "stderr": ""},
        "diff_refs": [{"kind": "inline_patch", "bytes": 12}],
        "artifacts": [],
        "workspace": {
            "pre_state_ref": "workspace:before",
            "post_state_ref": "workspace:after",
        },
        "outcome_metrics": {
            "wall_time_ms": 1000,
            "changed_files_count": 1,
            "patch_bytes": 12,
            "input_tokens": 100,
            "output_tokens": 20,
        },
        "extraction": {"status": "native_stream_captured"},
        "result_proposal": {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "codex-cli",
            "status": "completed",
            "effective_model": "gpt-5.4-mini",
            "effective_provider": "openai-compatible",
            "emitted_events": [],
            "artifacts": [],
            "outcome_metrics": {},
            "verification": {"status": "not_run"},
            "native_log_refs": [],
            "mutation_proposal_refs": [],
        },
    }

    outcome = node_outcome_from_session(assignment, session_record, outcome_id="outcome-001")
    loaded = load_node_outcome(outcome.to_dict())

    assert loaded.outcome_id == "outcome-001"
    assert loaded.status == "completed"
    assert loaded.node_id == "implement"
    assert loaded.effective_model == "gpt-5.4-mini"
    assert loaded.pre_state_ref == "workspace:before"
    assert loaded.post_state_ref == "workspace:after"
    assert loaded.observed_delta["changed_files_count"] == 1
    assert loaded.observed_delta["patch_bytes"] == 12


def test_appends_node_outcome_decision_event() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    outcome = node_outcome_from_session(
        assignment,
        {
            "session_id": "session-001",
            "assignment_id": "assign-001",
            "agent_id": "codex-cli",
            "status": "completed",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "exit": {"code": 0, "reason": "completed"},
            "native_logs": {"stdout": "", "stderr": ""},
            "diff_refs": [],
            "artifacts": [],
            "workspace": {},
            "outcome_metrics": {"wall_time_ms": 1000, "changed_files_count": 0},
            "extraction": {"status": "native_stream_captured"},
            "result_proposal": {
                "result_id": "result-001",
                "assignment_id": "assign-001",
                "agent_id": "codex-cli",
                "status": "completed",
                "effective_model": "gpt-5.4-mini",
                "effective_provider": "openai-compatible",
                "emitted_events": [],
                "artifacts": [],
                "outcome_metrics": {},
                "verification": {"status": "not_run"},
                "native_log_refs": [],
                "mutation_proposal_refs": [],
            },
        },
        outcome_id="outcome-001",
    )
    event = build_node_outcome_decision_event(
        outcome,
        event_id="event-outcome-001",
        mission_id=workflow.mission_id,
        workflow_id=workflow.workflow_id,
        actor="harness",
        disposition="accepted",
        accepted_event_types=["patch_ready"],
        validation_rule="manual_test_v1",
        created_at="2026-01-01T00:00:02Z",
    )

    updated = append_ledger_event(ledger, event, workflow)

    assert updated.event_log[0]["event_type"] == "node_outcome_decided"
    assert updated.event_log[0]["source_outcome_id"] == "outcome-001"
    assert updated.event_log[0]["accepted_event_types"] == ["patch_ready"]


def test_import_session_record_appends_result_and_outcome_decision(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "effective_model": "gpt-5.4-mini",
            "effective_provider": "openai-compatible",
            "emitted_events": ["patch_ready"],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    record = run_session(
        create_session_spec(
            assignment=assignment,
            agent_id="shell-dummy",
            workdir=source_root,
            shell_command=f"cat <<'EOF'\n{payload}\nEOF",
            session_id="session-001",
        ),
        assignment,
    )

    updated = import_session_record(workflow, ledger, assignment, record)
    replay = replay_workflow(workflow, updated)

    assert [event["event_type"] for event in updated.event_log] == [
        "result_submitted",
        "patch_ready",
        "node_outcome_decided",
    ]
    assert updated.event_log[-1]["source_outcome_id"] == "outcome-session-001"
    assert updated.event_log[-1]["accepted_event_types"] == ["patch_ready"]
    assert replay.nodes["implement"].state == "completed"
    assert replay.nodes["review"].state == "runnable"


def test_import_session_record_marks_outcome_stale_when_pre_state_is_outdated(
    tmp_path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    workflow = _workflow()
    ledger = _empty_ledger()
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-outcome-old",
            "event_type": "node_outcome_decided",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "assignment_id": "assign-old",
            "node_id": "implement",
            "role": "coder",
            "agent_id": "codex-cli",
            "session_id": "session-old",
            "source_outcome_id": "outcome-old",
            "outcome_status": "completed",
            "actor": "harness",
            "disposition": "accepted",
            "accepted_event_types": [],
            "post_state_ref": "workspace:accepted-current",
        },
        workflow,
    )
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001", force=True)
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow,
            assignment,
            session_id="session-001",
            agent_id="shell-dummy",
        ),
        workflow,
    )
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "effective_model": "gpt-5.4-mini",
            "effective_provider": "openai-compatible",
            "emitted_events": ["patch_ready"],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    record = run_session(
        create_session_spec(
            assignment=assignment,
            agent_id="shell-dummy",
            workdir=source_root,
            shell_command=f"cat <<'EOF'\n{payload}\nEOF",
            session_id="session-001",
        ),
        assignment,
    )
    record = replace(
        record,
        workspace={
            **record.workspace,
            "pre_state_ref": "workspace:older-pre-state",
            "post_state_ref": "workspace:new-post-state",
        },
    )

    updated = import_session_record(workflow, ledger, assignment, record)
    replay = replay_workflow(workflow, updated)

    assert updated.event_log[-1]["event_type"] == "node_outcome_decided"
    assert updated.event_log[-1]["outcome_status"] == "stale"
    assert updated.event_log[-1]["accepted_event_types"] == []
    assert replay.nodes["implement"].state == "blocked"
    assert replay.nodes["review"].state == "blocked"


def test_replay_accepts_outcome_decision_without_raw_workflow_event() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow,
            assignment,
            session_id="session-001",
            agent_id="codex-cli",
        ),
        workflow,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-result-001",
            "event_type": "result_submitted",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "assignment_id": "assign-001",
            "node_id": "implement",
            "role": "coder",
            "agent_id": "codex-cli",
            "result": {
                "result_id": "result-001",
                "assignment_id": "assign-001",
                "agent_id": "codex-cli",
                "status": "completed",
                "emitted_events": [],
                "artifacts": [],
                "outcome_metrics": {},
                "verification": {"status": "passed"},
                "native_log_refs": [],
                "mutation_proposal_refs": [],
            },
        },
        workflow,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-outcome-001",
            "event_type": "node_outcome_decided",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "assignment_id": "assign-001",
            "node_id": "implement",
            "role": "coder",
            "agent_id": "codex-cli",
            "session_id": "session-001",
            "source_outcome_id": "outcome-001",
            "outcome_status": "completed",
            "actor": "harness",
            "disposition": "accepted",
            "accepted_event_types": ["patch_ready"],
        },
        workflow,
    )

    replay = replay_workflow(workflow, ledger)
    gatekeeper = evaluate_gatekeeper(workflow, ledger)

    assert replay.nodes["implement"].state == "completed"
    assert replay.nodes["review"].state == "runnable"
    assert gatekeeper.ready == ["review"]


def test_replay_rejects_raw_workflow_event_when_outcome_decision_rejects_it() -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    ledger = append_ledger_event(
        ledger,
        build_assignment_created_event(
            workflow,
            assignment,
            session_id="session-001",
            agent_id="codex-cli",
        ),
        workflow,
    )
    result = load_result_proposal(
        {
            "result_id": "result-001",
            "assignment_id": "assign-001",
            "agent_id": "codex-cli",
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "artifacts": [],
            "outcome_metrics": {
                "wall_time_ms": 1000,
                "changed_files_count": 1,
            },
            "verification": {"status": "passed"},
            "native_log_refs": [],
        }
    )
    ledger = import_result_proposal(
        workflow,
        ledger,
        assignment,
        result,
    )
    ledger = append_ledger_event(
        ledger,
        {
            "event_id": "event-outcome-001",
            "event_type": "node_outcome_decided",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "assignment_id": "assign-001",
            "node_id": "implement",
            "role": "coder",
            "agent_id": "codex-cli",
            "session_id": "session-001",
            "source_outcome_id": "outcome-001",
            "outcome_status": "completed",
            "actor": "harness",
            "disposition": "rejected",
            "accepted_event_types": [],
        },
        workflow,
    )

    replay = replay_workflow(workflow, ledger)
    gatekeeper = evaluate_gatekeeper(workflow, ledger)

    assert replay.nodes["implement"].state == "blocked"
    assert replay.nodes["review"].state == "blocked"
    assert gatekeeper.ready == []
    assert replay.nodes["review"].blocked_reasons[0].missing_ref == "patch_ready"


def test_cli_mission_golden_path_prepares_manifest_and_executes_end_to_end(
    tmp_path, capsys
) -> None:
    workspace = tmp_path / "golden-path"
    exit_code = main(["mission", "golden-path", str(workspace)])
    manifest = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert Path(manifest["mission_path"]).exists()
    assert Path(manifest["workflow_path"]).exists()
    assert Path(manifest["ledger_path"]).exists()
    assert Path(manifest["results"]["implement"]).exists()
    assert Path(manifest["results"]["review"]).exists()
    assert Path(manifest["results"]["commit"]).exists()
    assert Path(manifest["artifacts_root"]).exists()

    implement_result = yaml.safe_load(
        Path(manifest["results"]["implement"]).read_text(encoding="utf-8")
    )
    assert implement_result["artifacts"][0]["path"] == "artifacts/implement_patch.diff"
    assert len(implement_result["artifacts"][0]["sha256"]) == 64

    for step in manifest["steps"]:
        step_exit = main(step["argv"])
        captured = capsys.readouterr()
        assert step_exit == 0, step["id"]
        expects = step["expects"]

        if "capture_to" in step:
            capture_path = Path(step["capture_to"])
            capture_path.parent.mkdir(parents=True, exist_ok=True)
            capture_path.write_text(captured.out, encoding="utf-8")
            payload = yaml.safe_load(captured.out)
            assert payload["assignment_id"] == expects["assignment_id"]
            assert payload["node_id"] == expects["node_id"]
            assert payload["expected_events"] == expects["expected_events"]
            continue

        if "ready" in expects:
            ready = [line.strip() for line in captured.out.splitlines() if line.strip()]
            assert ready == expects["ready"]
            continue

        if "terminal_complete" in expects:
            replay_payload = yaml.safe_load(captured.out)
            assert replay_payload["terminal_complete"] is expects["terminal_complete"]
            node_states = {
                node_id: node_payload["state"]
                for node_id, node_payload in replay_payload["nodes"].items()
            }
            assert node_states == expects["node_states"]
            if "blocked_refs" in expects:
                blocked_refs = {
                    node_id: sorted(
                        {
                            reason["missing_ref"]
                            for reason in node_payload["blocked_reasons"]
                            if "missing_ref" in reason
                        }
                    )
                    for node_id, node_payload in replay_payload["nodes"].items()
                    if node_payload["blocked_reasons"]
                }
                assert blocked_refs == expects["blocked_refs"]
            continue

        assert expects["stdout_contains"] in captured.out

    updated = load_ledger(Path(manifest["ledger_path"]))
    assert [event["event_type"] for event in updated.event_log] == [
        "result_submitted",
        "patch_ready",
        "result_submitted",
        "review_approved",
        "result_submitted",
        "commit_created",
    ]


def test_run_live_demo_executes_three_node_session_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        prompt = kwargs["input"]
        if "Node: implement" in prompt:
            event_name = "patch_ready"
        elif "Node: review" in prompt:
            event_name = "review_approved"
        elif "Node: commit" in prompt:
            event_name = "commit_created"
        else:
            raise AssertionError(prompt)
        stdout = (
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"'
            f'status: completed\\nemitted_events:\\n  - {event_name}\\nverification:\\n  status: passed'
            '"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20}}\n'
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=stdout,
            stderr="",
        )

    manifest = run_live_demo(
        tmp_path / "live-demo",
        agent_id="codex-cli",
        target_model="gpt-5",
        target_provider="openai",
        timeout_seconds=10.0,
        command_runner=fake_runner,
    )

    assert manifest["terminal_complete"] is True
    assert manifest["ready"] == []
    assert manifest["node_states"] == {
        "implement": "completed",
        "review": "completed",
        "commit": "completed",
    }
    assert [step["node_id"] for step in manifest["steps"]] == [
        "implement",
        "review",
        "commit",
    ]
    assert manifest["steps"][0]["ready_after"] == ["review"]
    assert manifest["steps"][1]["ready_after"] == ["commit"]
    assert manifest["steps"][2]["ready_after"] == []


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


def test_agent_compatibility_reports_dispatchable_for_full_control_surface() -> None:
    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=0, stdout="codex 1.0\n", stderr="")
        return CommandOutput(
            returncode=0,
            stdout="exec --model --config --ignore-user-config --cd --json --ephemeral",
            stderr="",
        )

    compatibility = assess_agent_compatibility(
        "codex-cli",
        which=lambda _binary: "/usr/bin/codex",
        run_command=fake_run,
    )

    assert compatibility.compatibility_state == "dispatchable"
    assert compatibility.capabilities["non_interactive_execution"] == "strong"
    assert compatibility.capabilities["working_directory_control"] == "strong"
    assert compatibility.capabilities["timeout_control"] == "strong"
    assert compatibility.capabilities["cancellation_control"] == "strong"


def test_agent_compatibility_reports_limited_for_partial_config_isolation() -> None:
    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=0, stdout="claude 1.0\n", stderr="")
        return CommandOutput(
            returncode=0,
            stdout="--print --model --settings --bare --worktree --add-dir --output-format --no-session-persistence",
            stderr="",
        )

    compatibility = assess_agent_compatibility(
        "claude-code",
        which=lambda _binary: "/usr/bin/claude",
        run_command=fake_run,
    )

    assert compatibility.compatibility_state == "limited"
    assert compatibility.capabilities["config_isolation"] == "weak"
    assert "config_isolation" in compatibility.reasons


def test_agent_compatibility_reports_manual_only_when_binary_missing() -> None:
    compatibility = assess_agent_compatibility(
        "codex-cli",
        which=lambda _binary: None,
    )

    assert compatibility.compatibility_state == "manual_only"
    assert compatibility.capabilities["non_interactive_execution"] == "none"
    assert compatibility.reasons == ["binary_unavailable"]


def test_workspace_isolation_reports_ready_for_copy_and_blocked_for_missing_root(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()

    ready = assess_workspace_isolation(source_root, isolation_mode="copy")
    blocked = assess_workspace_isolation(tmp_path / "missing", isolation_mode="copy")

    assert ready.status == "ready"
    assert ready.effective_mode == "copy"
    assert blocked.status == "blocked"
    assert blocked.reasons == ["source_root_missing"]


def test_dispatch_readiness_reports_dispatchable_for_strong_agent_and_copy_workspace(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()

    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=0, stdout="codex 1.0\n", stderr="")
        return CommandOutput(
            returncode=0,
            stdout="exec --model --config --ignore-user-config --cd --json --ephemeral",
            stderr="",
        )

    readiness = assess_dispatch_readiness(
        "codex-cli",
        source_root,
        isolation_mode="copy",
        which=lambda _binary: "/usr/bin/codex",
        run_command=fake_run,
    )

    assert readiness.readiness_state == "dispatchable"
    assert readiness.compatibility_state == "dispatchable"
    assert readiness.isolation.status == "ready"
    assert readiness.isolation.effective_mode == "copy"


def test_dispatch_readiness_reports_manual_only_for_limited_agent(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()

    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=0, stdout="claude 1.0\n", stderr="")
        return CommandOutput(
            returncode=0,
            stdout="--print --model --settings --bare --worktree --add-dir --output-format --no-session-persistence",
            stderr="",
        )

    readiness = assess_dispatch_readiness(
        "claude-code",
        source_root,
        isolation_mode="copy",
        which=lambda _binary: "/usr/bin/claude",
        run_command=fake_run,
    )

    assert readiness.readiness_state == "manual_only"
    assert readiness.compatibility_state == "limited"
    assert "config_isolation" in readiness.reasons
    assert readiness.isolation.status == "ready"


def test_dispatch_readiness_reports_blocked_when_worktree_is_unavailable(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()

    def fake_run(command: list[str]) -> CommandOutput:
        if "--version" in command:
            return CommandOutput(returncode=0, stdout="codex 1.0\n", stderr="")
        return CommandOutput(
            returncode=0,
            stdout="exec --model --config --ignore-user-config --cd --json --ephemeral",
            stderr="",
        )

    readiness = assess_dispatch_readiness(
        "codex-cli",
        source_root,
        isolation_mode="worktree",
        which=lambda _binary: "/usr/bin/codex",
        run_command=fake_run,
    )

    assert readiness.readiness_state == "blocked"
    assert readiness.compatibility_state == "dispatchable"
    assert readiness.isolation.status == "blocked"
    assert readiness.isolation.reasons == ["worktree_unavailable"]


def test_resolve_codex_openai_binding_defaults_to_codex_api_key() -> None:
    binding = resolve_agent_binding(
        "codex-cli",
        target_model="gpt-5",
        target_provider="openai",
    )

    assert binding.agent_id == "codex-cli"
    assert binding.provider_id == "openai"
    assert binding.model == "gpt-5"
    assert binding.api_key_env == "OPENAI_API_KEY"
    assert binding.codex_config_overrides == {"model_provider": "openai"}


def test_resolve_codex_openai_compatible_binding_requires_base_url_and_api_key_env() -> None:
    with pytest.raises(ProtocolError, match="requires provider_base_url"):
        resolve_agent_binding(
            "codex-cli",
            target_model="gpt-5",
            target_provider="openai-compatible",
        )

    with pytest.raises(ProtocolError, match="requires provider_api_key_env"):
        resolve_agent_binding(
            "codex-cli",
            target_model="gpt-5",
            target_provider="openai-compatible",
            provider_base_url="https://proxy.example.com/v1",
        )

    binding = resolve_agent_binding(
        "codex-cli",
        target_model="gpt-5-mini",
        target_provider="openai-compatible",
        provider_base_url="https://proxy.example.com/v1",
        provider_api_key_env="OPENAI_API_KEY",
    )

    assert binding.provider_id == "openai-compatible"
    assert binding.base_url == "https://proxy.example.com/v1"
    assert binding.api_key_env == "OPENAI_API_KEY"
    assert binding.codex_config_overrides["model_provider"] == "bureauless"
    assert (
        binding.codex_config_overrides["model_providers.bureauless.base_url"]
        == "https://proxy.example.com/v1"
    )
    assert (
        binding.codex_config_overrides[
            "model_providers.bureauless.requires_openai_auth"
        ]
        is True
    )


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


def test_list_agent_compatibility_returns_known_agent_ids() -> None:
    payload = list_agent_compatibility(which=lambda _binary: None)

    assert [entry.agent_id for entry in payload] == [
        "claude-code",
        "codex-cli",
        "opencode",
    ]
    assert all(entry.compatibility_state == "manual_only" for entry in payload)


def test_cli_agent_matrix(capsys) -> None:
    exit_code = main(["agent", "matrix"])
    payload = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert [item["agent_id"] for item in payload] == [
        "claude-code",
        "codex-cli",
        "opencode",
    ]
    assert all(item["compatibility_state"] in {"dispatchable", "limited", "manual_only"} for item in payload)


def test_cli_agent_readiness(tmp_path, capsys) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()

    exit_code = main(["agent", "readiness", "codex-cli", "--workdir", str(source_root)])
    payload = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["agent_id"] == "codex-cli"
    assert payload["readiness_state"] in {"dispatchable", "manual_only", "blocked"}
    assert payload["isolation"]["status"] == "ready"


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
    assert record.extraction["status"] == "synthetic"
    assert record.result_proposal is not None
    assert record.result_proposal["assignment_id"] == "assign-001"
    assert record.result_proposal["effective_model"] == "fake"
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
    assert record.extraction["status"] == "dry_run"
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
    assert record.extraction["status"] == "timed_out"
    assert record.result_proposal is None


def test_shell_dummy_failed_run_reports_partial_workspace_effects(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")

    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=source_root,
        shell_command=(
            "python3 -c \"from pathlib import Path; "
            "Path('tracked.txt').write_text('changed\\n', encoding='utf-8'); "
            "raise SystemExit(3)\""
        ),
        session_id="session-001",
    )

    record = run_session(spec, assignment)

    assert record.status == "failed"
    assert record.result_proposal is None
    assert record.outcome_metrics["changed_files_count"] == 1
    assert record.workspace["pre_state_ref"] != record.workspace["post_state_ref"]


def test_shell_dummy_extracts_structured_native_output(tmp_path) -> None:
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
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "effective_model": "gpt-5.4-mini",
            "effective_provider": "openai",
            "review_status": "not_required",
            "emitted_events": ["patch_ready"],
            "changed_files": ["src/app.py", "tests/test_app.py"],
            "patch": "--- a/src/app.py\n+++ b/src/app.py\n",
            "verification": {"status": "passed"},
            "native_log_refs": [{"kind": "stdout", "path": "logs/stdout.txt"}],
            "artifacts": [
                {
                    "artifact_id": "artifact-001",
                    "path": "artifacts/report.md",
                    "sha256": "a" * 64,
                    "created_by": "shell-dummy",
                    "source_event": "event-result-session-001",
                    "mutable": False,
                }
            ],
            "outcome_metrics": {
                "input_tokens": 120,
                "output_tokens": 80,
                "cost_usd": 0.012,
                "cost_source": "adapter_reported",
                "cost_confidence": "high",
                "usage_confidence": "high",
            },
        },
        sort_keys=False,
    ).strip()
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=tmp_path,
        shell_command=f"cat <<'EOF'\n{payload}\nEOF",
        session_id="session-001",
    )

    record = run_session(spec, assignment)

    assert record.status == "completed"
    assert record.extraction["status"] == "extracted"
    assert record.result_proposal is not None
    assert record.result_proposal["effective_model"] == "gpt-5.4-mini"
    assert record.result_proposal["effective_provider"] == "openai"
    assert record.result_proposal["review_status"] == "not_required"
    assert record.result_proposal["emitted_events"] == ["patch_ready"]
    assert record.outcome_metrics["input_tokens"] == 120
    assert record.outcome_metrics["output_tokens"] == 80
    assert record.outcome_metrics["total_tokens"] == 200
    assert record.outcome_metrics["cost_usd"] == 0.012
    assert record.outcome_metrics["patch_bytes"] > 0
    assert record.outcome_metrics["changed_files_count"] == 2
    assert record.diff_refs[0]["kind"] == "inline_patch"
    assert record.artifacts[0]["artifact_id"] == "artifact-001"


def test_shell_dummy_marks_unstructured_output_as_agent_not_emitting_usage(tmp_path) -> None:
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
        shell_command="printf 'plain text output only\\n'",
        session_id="session-001",
    )

    record = run_session(spec, assignment)

    assert record.status == "completed"
    assert record.extraction["status"] == "agent_does_not_emit_usage"
    assert record.result_proposal is not None
    assert record.result_proposal["emitted_events"] == []
    assert record.outcome_metrics["usage_confidence"] == "none"
    assert record.outcome_metrics["cost_source"] == "agent_not_supported"
    assert "total_tokens" not in record.outcome_metrics


def test_shell_dummy_reports_wrapper_failed_to_extract(tmp_path) -> None:
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
        shell_command="printf 'status: [broken\\n'",
        session_id="session-001",
    )

    record = run_session(spec, assignment)

    assert record.status == "completed"
    assert record.extraction["status"] == "wrapper_failed_to_extract"
    assert record.result_proposal is not None
    assert record.result_proposal["emitted_events"] == []
    assert record.extraction["warnings"] != []


def test_shell_dummy_copy_isolation_preserves_source_root(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")

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
        workdir=source_root,
        isolation_mode="copy",
        shell_command=(
            "python3 -c \"from pathlib import Path; "
            "Path('tracked.txt').write_text('changed\\n', encoding='utf-8')\""
        ),
        session_id="session-001",
    )

    record = run_session(spec, assignment)
    workspace_file = Path(record.workspace["path"]) / "tracked.txt"

    assert record.workspace["mode"] == "copy"
    assert tracked.read_text(encoding="utf-8") == "original\n"
    assert workspace_file.read_text(encoding="utf-8") == "changed\n"
    assert Path(record.native_logs["stdout_path"]).exists()
    assert Path(record.native_logs["stderr_path"]).exists()
    assert str(workspace_file.parent) in record.workspace["retained_paths"]


def test_shell_dummy_ignores_preexisting_dirty_workspace_in_delta_metrics(tmp_path) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked.write_text("dirty-before-session\n", encoding="utf-8")

    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=source_root,
        isolation_mode="copy",
        shell_command="printf 'plain text output only\\n'",
        session_id="session-001",
    )

    record = run_session(spec, assignment)

    assert record.status == "completed"
    assert record.outcome_metrics["changed_files_count"] == 0
    assert "patch_bytes" not in record.outcome_metrics
    assert record.diff_refs == []


def test_shell_dummy_worktree_isolation_when_git_available(tmp_path) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )

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
        workdir=source_root,
        isolation_mode="worktree",
        shell_command=(
            "python3 -c \"from pathlib import Path; "
            "Path('tracked.txt').write_text('changed\\n', encoding='utf-8')\""
        ),
        session_id="session-001",
    )

    record = run_session(spec, assignment)
    workspace_file = Path(record.workspace["path"]) / "tracked.txt"

    assert record.workspace["mode"] == "worktree"
    assert tracked.read_text(encoding="utf-8") == "original\n"
    assert workspace_file.read_text(encoding="utf-8") == "changed\n"


def test_codex_session_requires_target_model_and_provider(tmp_path) -> None:
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")

    with pytest.raises(ProtocolError, match="requires target_model and target_provider"):
        create_session_spec(
            assignment=assignment,
            agent_id="codex-cli",
            workdir=tmp_path,
            session_id="session-001",
        )


def test_codex_session_produces_importable_result_from_completed_run(tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )

    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="codex-cli",
        workdir=source_root,
        target_model="gpt-5",
        target_provider="openai",
        session_id="session-001",
    )

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        assert command[:4] == ["codex", "--ask-for-approval", "never", "exec"]
        assert "--json" in command
        assert "--ignore-user-config" in command
        assert "--ephemeral" in command
        assert "--model" in command
        assert "gpt-5" in command
        assert '-c' in command
        assert 'model_provider="openai"' in command
        assert kwargs["env"]["OPENAI_API_KEY"] == "test-key"
        assert "CODEX_HOME" in kwargs["env"]
        auth_path = Path(kwargs["env"]["CODEX_HOME"]) / "auth.json"
        assert auth_path.exists()
        auth_payload = yaml.safe_load(auth_path.read_text(encoding="utf-8"))
        assert auth_payload["OPENAI_API_KEY"] == "test-key"
        Path(kwargs["cwd"]) .joinpath("tracked.txt").write_text("changed\n", encoding="utf-8")
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='{"type":"message","role":"assistant","content":"done"}\n',
            stderr="",
        )

    record = run_session(spec, assignment, command_runner=fake_runner)

    assert record.status == "completed"
    assert record.result_proposal is not None
    assert record.result_proposal["effective_model"] == "gpt-5"
    assert record.result_proposal["effective_provider"] == "openai"
    assert record.outcome_metrics["changed_files_count"] == 1
    assert record.outcome_metrics["patch_bytes"] > 0
    assert record.diff_refs[0]["kind"] == "inline_patch"


def test_codex_session_ignores_preexisting_dirty_workspace_in_delta_metrics(tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked.write_text("dirty-before-session\n", encoding="utf-8")

    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="codex-cli",
        workdir=source_root,
        target_model="gpt-5",
        target_provider="openai",
        session_id="session-001",
    )

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='{"type":"message","role":"assistant","content":"OK"}\n',
            stderr="",
        )

    record = run_session(spec, assignment, command_runner=fake_runner)

    assert record.status == "completed"
    assert record.outcome_metrics["changed_files_count"] == 0
    assert "patch_bytes" not in record.outcome_metrics
    assert record.diff_refs == []


def test_codex_session_extracts_usage_from_jsonl(tmp_path, monkeypatch) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )

    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="codex-cli",
        workdir=source_root,
        target_model="gpt-5",
        target_provider="openai",
        session_id="session-001",
    )

    stdout = (
        '{"type":"thread.started","thread_id":"x"}\n'
        '{"type":"turn.started"}\n'
        '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"OK"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":25,"output_tokens":20,"reasoning_output_tokens":10}}\n'
    )

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=stdout,
            stderr="",
        )

    record = run_session(spec, assignment, command_runner=fake_runner)

    assert record.outcome_metrics["input_tokens"] == 100
    assert record.outcome_metrics["output_tokens"] == 20
    assert record.outcome_metrics["total_tokens"] == 120
    assert record.outcome_metrics["cached_input_tokens"] == 25
    assert record.outcome_metrics["reasoning_output_tokens"] == 10
    assert record.outcome_metrics["usage_confidence"] == "high"
    assert record.extraction["assistant_text"] == "OK"
    assert not Path(record.workspace["session_root"]).joinpath("codex-home").exists()


def test_codex_session_extracts_structured_result_from_assistant_text(
    tmp_path, monkeypatch
) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )

    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="codex-cli",
        workdir=source_root,
        target_model="gpt-5",
        target_provider="openai",
        session_id="session-001",
    )

    stdout = (
        '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"status: completed\\n'
        'emitted_events:\\n  - patch_ready\\nverification:\\n  status: passed"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20}}\n'
    )

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        assert "Output Contract" in kwargs["input"]
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=stdout,
            stderr="",
        )

    record = run_session(spec, assignment, command_runner=fake_runner)

    assert record.result_proposal is not None
    assert record.result_proposal["status"] == "completed"
    assert record.result_proposal["emitted_events"] == ["patch_ready"]
    assert record.result_proposal["verification"] == {"status": "passed"}
    assert record.extraction["emitted_events"] == ["patch_ready"]
    assert record.extraction["verification"] == {"status": "passed"}
    assert record.outcome_metrics["input_tokens"] == 100
    assert record.outcome_metrics["total_tokens"] == 120


def test_codex_session_tolerates_backticks_in_structured_assistant_text(
    tmp_path, monkeypatch
) -> None:
    source_root = tmp_path / "repo"
    source_root.mkdir()
    tracked = source_root / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=source_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )

    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    spec = create_session_spec(
        assignment=assignment,
        agent_id="codex-cli",
        workdir=source_root,
        target_model="gpt-5",
        target_provider="openai",
        session_id="session-001",
    )

    stdout = (
        '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"status: completed\\n'
        'emitted_events:\\n  - patch_ready\\nverification:\\n  status: passed\\n  details:\\n'
        '  - updated `src/demo.py`"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20}}\n'
    )

    def fake_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=stdout,
            stderr="",
        )

    record = run_session(spec, assignment, command_runner=fake_runner)

    assert record.result_proposal is not None
    assert record.result_proposal["emitted_events"] == ["patch_ready"]
    assert record.result_proposal["verification"]["status"] == "passed"


def test_package_session_result_normalizes_artifacts_and_native_logs(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
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
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "effective_model": "gpt-5.4-mini",
            "effective_provider": "openai",
            "emitted_events": ["patch_ready"],
            "artifacts": [
                {
                    "artifact_id": "artifact-report",
                    "path": "artifacts/report.md",
                }
            ],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=source_root,
        shell_command=(
            "mkdir -p artifacts\n"
            "printf 'report\\n' > artifacts/report.md\n"
            f"cat <<'EOF'\n{payload}\nEOF"
        ),
        session_id="session-001",
    )

    record = run_session(spec, assignment)
    packaged = package_session_result(record, assignment)
    packaged_again = package_session_result(record, assignment)

    assert packaged.to_dict() == packaged_again.to_dict()
    assert packaged.result_id == "result-session-001"
    assert packaged.artifacts[0]["artifact_id"] == "artifact-report"
    assert packaged.artifacts[0]["path"] == "workspace/artifacts/report.md"
    assert packaged.artifacts[0]["source_event"] == "event-result-session-001"
    assert packaged.native_log_refs[0]["path"] == "logs/stdout.log"
    assert packaged.native_log_refs[1]["path"] == "logs/stderr.log"
    assert packaged.native_log_refs[0]["sha256"]


def test_session_packages_mutation_proposal_artifact_ref(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    workflow = _workflow()
    ledger = _empty_ledger()
    assignment = export_assignment(
        workflow, ledger, "implement", assignment_id="assign-001"
    )
    payload = yaml.safe_dump(
        {
            "status": "completed_with_proposal",
            "emitted_events": [],
            "artifacts": [
                {
                    "artifact_id": "artifact-mutation-001",
                    "path": "artifacts/mutation-001.yaml",
                }
            ],
            "mutation_proposal_refs": ["artifact-mutation-001"],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=source_root,
        shell_command=(
            "mkdir -p artifacts\n"
            "printf 'proposal_type: workflow_mutation\\n' > artifacts/mutation-001.yaml\n"
            f"cat <<'EOF'\n{payload}\nEOF"
        ),
        session_id="session-001",
    )

    record = run_session(spec, assignment)
    packaged = package_session_result(record, assignment)

    assert record.extraction["mutation_proposal_refs"] == [
        "artifact-mutation-001"
    ]
    assert packaged.status == "completed_with_proposal"
    assert packaged.mutation_proposal_refs == ["artifact-mutation-001"]
    assert packaged.artifacts[0]["artifact_id"] == "artifact-mutation-001"
    assert packaged.artifacts[0]["path"] == (
        "workspace/artifacts/mutation-001.yaml"
    )
    assert len(packaged.artifacts[0]["sha256"]) == 64
    assert packaged.artifacts[0]["mutable"] is False


def test_package_session_result_rejects_missing_artifact_or_assignment_mismatch(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
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
    wrong_assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-002")
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "artifacts": [{"path": "artifacts/missing.md"}],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    spec = create_session_spec(
        assignment=assignment,
        agent_id="shell-dummy",
        workdir=source_root,
        shell_command=f"cat <<'EOF'\n{payload}\nEOF",
        session_id="session-001",
    )
    record = run_session(spec, assignment)

    try:
        package_session_result(record, wrong_assignment)
    except ProtocolError as exc:
        assert "assignment_id does not match" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")

    try:
        package_session_result(record, assignment)
    except ProtocolError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("Expected ProtocolError")


def test_packaged_session_result_reuses_manual_result_import_path(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
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
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "artifacts": [{"artifact_id": "artifact-report", "path": "artifacts/report.md"}],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    record = run_session(
        create_session_spec(
            assignment=assignment,
            agent_id="shell-dummy",
            workdir=source_root,
            shell_command=(
                "mkdir -p artifacts\n"
                "printf 'report\\n' > artifacts/report.md\n"
                f"cat <<'EOF'\n{payload}\nEOF"
            ),
            session_id="session-001",
        ),
        assignment,
    )

    packaged = package_session_result(record, assignment)
    updated = import_result_proposal(workflow, ledger, assignment, packaged)
    replay = replay_workflow(workflow, updated)

    assert updated.event_log[0]["event_type"] == "result_submitted"
    assert updated.event_log[1]["event_type"] == "patch_ready"
    assert updated.event_log[0]["result"]["artifacts"][0]["path"] == "workspace/artifacts/report.md"
    assert updated.event_log[0]["result"]["native_log_refs"][0]["path"] == "logs/stdout.log"
    assert replay.nodes["implement"].state == "completed"
    assert replay.nodes["review"].state == "runnable"


def test_session_lifecycle_events_map_timeout_cancel_and_supersede(tmp_path) -> None:
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
    created = build_assignment_created_event(workflow, assignment, spec.session_id, spec.agent_id)
    timed_out = build_session_terminal_event(
        workflow,
        assignment,
        run_session(
            create_session_spec(
                assignment=assignment,
                agent_id="shell-dummy",
                workdir=tmp_path,
                shell_command="sleep 1",
                timeout_seconds=0.01,
                session_id="session-timeout",
            ),
            assignment,
        ),
    )
    cancelled = build_session_terminal_event(
        workflow,
        assignment,
        cancel_session_record(run_session(spec, assignment), reason="user_cancelled"),
    )
    superseded = build_session_terminal_event(
        workflow,
        assignment,
        supersede_session_record(run_session(spec, assignment)),
        superseded_by="assign-002",
    )

    assert created["event_type"] == "assignment_created"
    assert created["assignment_id"] == "assign-001"
    assert timed_out is not None and timed_out["event_type"] == "worker_timeout"
    assert cancelled is not None and cancelled["event_type"] == "assignment_cancelled"
    assert cancelled["reason"] == "user_cancelled"
    assert superseded is not None and superseded["event_type"] == "assignment_superseded"
    assert superseded["superseded_by"] == "assign-002"


def test_replay_blocks_duplicate_dispatch_while_assignment_is_in_flight() -> None:
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
                    "event_id": "event-assign-001-created",
                    "event_type": "assignment_created",
                    "mission_id": "demo",
                    "workflow_id": "test-workflow",
                    "assignment_id": "assign-001",
                    "node_id": "implement",
                    "role": "coder",
                    "agent_id": "shell-dummy",
                    "session_id": "session-001",
                }
            ],
        }
    )

    gatekeeper = evaluate_gatekeeper(workflow, ledger)
    replay = replay_workflow(workflow, ledger)

    assert gatekeeper.ready == []
    assert gatekeeper.decisions["implement"].state == "blocked"
    assert gatekeeper.decisions["implement"].blocked_reasons[0].code == "assignment_in_flight"
    assert replay.nodes["implement"].assignment_attempts[0].state == "in_flight"


def test_replay_reopens_node_after_timeout_or_cancellation() -> None:
    workflow = _workflow()
    timeout_ledger = Ledger.from_dict(
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
                    "event_id": "event-assign-001-created",
                    "event_type": "assignment_created",
                    "assignment_id": "assign-001",
                    "node_id": "implement",
                    "role": "coder",
                },
                {
                    "event_id": "event-assign-001-timeout",
                    "event_type": "worker_timeout",
                    "assignment_id": "assign-001",
                    "node_id": "implement",
                    "role": "coder",
                },
            ],
        }
    )
    cancelled_ledger = Ledger.from_dict(
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
                    "event_id": "event-assign-002-created",
                    "event_type": "assignment_created",
                    "assignment_id": "assign-002",
                    "node_id": "implement",
                    "role": "coder",
                },
                {
                    "event_id": "event-assign-002-cancelled",
                    "event_type": "assignment_cancelled",
                    "assignment_id": "assign-002",
                    "node_id": "implement",
                    "role": "coder",
                },
            ],
        }
    )

    timeout_result = evaluate_gatekeeper(workflow, timeout_ledger)
    cancelled_result = evaluate_gatekeeper(workflow, cancelled_ledger)
    timeout_replay = replay_workflow(workflow, timeout_ledger)
    cancelled_replay = replay_workflow(workflow, cancelled_ledger)

    assert timeout_result.ready == ["implement"]
    assert cancelled_result.ready == ["implement"]
    assert timeout_replay.nodes["implement"].assignment_attempts[0].state == "timed_out"
    assert cancelled_replay.nodes["implement"].assignment_attempts[0].state == "cancelled"
    assert timeout_replay.nodes["implement"].state == "runnable"
    assert cancelled_replay.nodes["implement"].state == "runnable"


def test_replay_tracks_superseded_assignment_without_marking_completed() -> None:
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
                    "event_id": "event-assign-001-created",
                    "event_type": "assignment_created",
                    "assignment_id": "assign-001",
                    "node_id": "implement",
                    "role": "coder",
                },
                {
                    "event_id": "event-assign-001-superseded",
                    "event_type": "assignment_superseded",
                    "assignment_id": "assign-001",
                    "node_id": "implement",
                    "role": "coder",
                    "superseded_by": "assign-002",
                },
                {
                    "event_id": "event-assign-002-created",
                    "event_type": "assignment_created",
                    "assignment_id": "assign-002",
                    "node_id": "implement",
                    "role": "coder",
                },
            ],
        }
    )

    replay = replay_workflow(workflow, ledger)
    gatekeeper = evaluate_gatekeeper(workflow, ledger)

    assert gatekeeper.ready == []
    assert replay.nodes["implement"].state == "blocked"
    assert [attempt.state for attempt in replay.nodes["implement"].assignment_attempts] == [
        "superseded",
        "in_flight",
    ]
    assert replay.nodes["implement"].assignment_attempts[0].superseded_by == "assign-002"
    assert replay.nodes["implement"].emitted_events == []


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
    assert payload["extraction"]["status"] == "synthetic"
    assert payload["result_proposal"]["assignment_id"] == "assign-001"

    cancel_exit = main(["session", "cancel", str(session_path), "--reason", "user_cancelled"])
    updated = load_session_record(yaml.safe_load(session_path.read_text(encoding="utf-8")))
    capsys.readouterr()

    assert cancel_exit == 0
    assert updated.status == "cancelled"
    assert updated.exit["reason"] == "user_cancelled"


def test_cli_result_package(tmp_path, capsys) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
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
    assignment = export_assignment(workflow, ledger, "implement", assignment_id="assign-001")
    assignment_path.write_text(
        yaml.safe_dump(assignment.to_dict(), sort_keys=False),
        encoding="utf-8",
    )
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "emitted_events": ["patch_ready"],
            "artifacts": [{"artifact_id": "artifact-report", "path": "artifacts/report.md"}],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    record = run_session(
        create_session_spec(
            assignment=assignment,
            agent_id="shell-dummy",
            workdir=source_root,
            shell_command=(
                "mkdir -p artifacts\n"
                "printf 'report\\n' > artifacts/report.md\n"
                f"cat <<'EOF'\n{payload}\nEOF"
            ),
            session_id="session-001",
        ),
        assignment,
    )
    session_path.write_text(yaml.safe_dump(record.to_dict(), sort_keys=False), encoding="utf-8")

    exit_code = main(["result", "package", str(assignment_path), str(session_path)])
    packaged = yaml.safe_load(capsys.readouterr().out)

    assert exit_code == 0
    assert packaged["result_id"] == "result-session-001"
    assert packaged["artifacts"][0]["path"] == "workspace/artifacts/report.md"
    assert packaged["native_log_refs"][0]["path"] == "logs/stdout.log"


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


def test_metrics_summarize_includes_observed_budget_snapshot(tmp_path) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "single.yaml").write_text(
        yaml.safe_dump(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                "agent_id": "fake",
                "workflow_mode": "single_agent",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "cost_usd": 0.01,
                    "changed_files_count": 0,
                },
                "result_proposal": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (sessions_dir / "dag.yaml").write_text(
        yaml.safe_dump(
            {
                "session_id": "session-002",
                "assignment_id": "assign-002",
                "agent_id": "fake",
                "workflow_mode": "small_dag",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:01Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [],
                "artifacts": [],
                "outcome_metrics": {
                    "wall_time_ms": 1000,
                    "input_tokens": 200,
                    "output_tokens": 40,
                    "total_tokens": 240,
                    "cost_usd": 0.02,
                    "changed_files_count": 0,
                },
                "result_proposal": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = summarize_metrics(sessions_dir)

    assert summary["observed_budget"]["session_count"] == 2
    assert summary["observed_budget"]["completed_count"] == 2
    assert summary["observed_budget"]["total_tokens_used"] == 360
    assert summary["observed_budget"]["known_cost_usd_total"] == 0.03
    assert summary["observed_budget"]["observed_coordination_ratio"] == 0.666667


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


def test_pre_dispatch_policy_rejects_hard_budget_limit_from_observed_usage() -> None:
    decision = evaluate_pre_dispatch_policy(
        mission_budget={
            "max_total_tokens": 300,
            "max_coordination_ratio": 0.25,
            "max_usd": 1.0,
        },
        routing_facts={
            "selected_mode": "small_dag",
            "predicted_total_tokens": 40,
            "predicted_cost_usd": 0.1,
            "coordination_ratio_prediction": 0.2,
        },
        observed_budget={
            "total_tokens_used": 280,
            "known_cost_usd_total": 0.2,
            "observed_coordination_ratio": 0.1,
        },
    )

    assert decision.decision == "reject"
    assert decision.budget_state == "hard_limit"
    assert "budget_hard_limit_tokens" in decision.triggered_rules


def test_pre_dispatch_policy_adjusts_parallel_swarm_to_review_mode() -> None:
    decision = evaluate_pre_dispatch_policy(
        mission_budget={
            "max_total_tokens": 100000,
            "max_coordination_ratio": 0.25,
            "max_usd": 10.0,
        },
        routing_facts={
            "selected_mode": "parallel_swarm",
            "risk_level": "medium",
            "shared_file_overlap": "high",
            "budget_confidence": "high",
            "coordination_ratio_prediction": 0.1,
            "merge_complexity": "low",
            "expected_wall_clock_savings": "material",
            "predicted_total_tokens": 1000,
            "predicted_cost_usd": 0.1,
        },
        observed_budget={
            "total_tokens_used": 1000,
            "known_cost_usd_total": 0.1,
            "observed_coordination_ratio": 0.2,
        },
    )

    assert decision.decision == "adjust"
    assert decision.selected_mode == "parallel_swarm"
    assert decision.recommended_mode == "single_agent_with_review"
    assert "reject_parallel_swarm_if" in decision.triggered_rules


def test_pre_dispatch_policy_adjusts_single_agent_for_review_floor() -> None:
    decision = evaluate_pre_dispatch_policy(
        mission_budget={
            "max_total_tokens": 100000,
            "max_coordination_ratio": 0.25,
            "max_usd": 10.0,
        },
        routing_facts={
            "selected_mode": "single_agent",
            "risk_level": "high",
            "predicted_total_tokens": 1000,
            "predicted_cost_usd": 0.1,
        },
        observed_budget={
            "total_tokens_used": 1000,
            "known_cost_usd_total": 0.1,
            "observed_coordination_ratio": 0.0,
        },
    )

    assert decision.decision == "adjust"
    assert decision.recommended_mode == "single_agent_with_review"
