from pathlib import Path

from bureauless.core import ProtocolError
from bureauless.harness import (
    Ledger,
    Workflow,
    compile_workflow,
    load_ledger,
    load_mission,
    load_workflow,
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
