from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "live_demo_boundary_run.py"
SPEC = importlib.util.spec_from_file_location("live_demo_boundary_run", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
live_demo_boundary_run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live_demo_boundary_run)


def test_boundary_audit_marks_implement_timeout_inconclusive(tmp_path: Path) -> None:
    telemetry = tmp_path / "generated" / "telemetry"
    telemetry.mkdir(parents=True)
    (telemetry / "m3_integrated_demo_manifest.yaml").write_text(
        yaml.safe_dump({"steps": [{"node_id": "implement", "record_status": "timed_out"}]}),
        encoding="utf-8",
    )
    (telemetry / "metrics_summary.yaml").write_text(
        yaml.safe_dump({"entries": []}), encoding="utf-8"
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "demo.py").write_text("print('old')\n", encoding="utf-8")

    audit = live_demo_boundary_run._summarize_audit(tmp_path)

    assert audit["overall"] == "inconclusive"
    assert audit["execution_status"] == "provider_runtime_timeout"
    assert [finding["code"] for finding in audit["findings"]] == ["provider_runtime_timeout"]


def test_boundary_overlay_only_constrains_the_orchestrator_model(tmp_path: Path) -> None:
    (tmp_path / "artifacts").mkdir()
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    mission_path = tmp_path / "mission.yaml"
    mission_path.write_text(
        yaml.safe_dump(
            {
                "mission_id": "demo",
                "models": {
                    "gpt-5": {"role": "large_reasoning"},
                    "gpt-5.4-mini": {"role": "bounded_execution"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    workflow_path = workflows / "coder_reviewer_committer.yaml"
    workflow_path.write_text(
        yaml.safe_dump({"status": "accepted"}), encoding="utf-8"
    )
    ledger_path = tmp_path / "ledger.yaml"
    ledger_path.write_text(
        yaml.safe_dump({"current_goal": "legacy demo goal"}), encoding="utf-8"
    )
    live_demo_boundary_run._overlay_boundary_task(
        {"mission": mission_path, "workflow": workflow_path, "ledger": ledger_path},
        "gpt-5.5",
    )

    mission = yaml.safe_load(mission_path.read_text(encoding="utf-8"))
    assert mission["models"] == {"gpt-5.5": {"role": "orchestrator"}}
    assert mission["goal"] == live_demo_boundary_run._load_task_inputs()["task"]
    assert yaml.safe_load(ledger_path.read_text(encoding="utf-8"))["current_goal"] == mission["goal"]
    assert live_demo_boundary_run._load_task_inputs()["provider_allowed_worker_models"] == ["gpt-5.5"]
    assert yaml.safe_load(workflow_path.read_text(encoding="utf-8"))["status"] == "proposed"


def test_boundary_yaml_writer_preserves_unicode(tmp_path: Path) -> None:
    path = tmp_path / "artifact.yaml"

    live_demo_boundary_run._write_yaml(path, {"goal": "中文任务"})

    assert "中文任务" in path.read_text(encoding="utf-8")


def test_boundary_audit_reports_proposed_helper_workflow_not_telemetry(tmp_path: Path) -> None:
    telemetry = tmp_path / "generated" / "telemetry"
    telemetry.mkdir(parents=True)
    (telemetry / "m3_integrated_demo_manifest.yaml").write_text(
        yaml.safe_dump({"steps": [{"node_id": "implement", "record_status": "completed"}]}),
        encoding="utf-8",
    )
    (telemetry / "metrics_summary.yaml").write_text(
        yaml.safe_dump({"entries": [{"usage_source": "provider_attributed"}]}),
        encoding="utf-8",
    )
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "coder_reviewer_committer.yaml").write_text(
        yaml.safe_dump({"status": "proposed"}), encoding="utf-8"
    )

    audit = live_demo_boundary_run._summarize_audit(tmp_path)

    assert audit["overall"] == "failed"
    assert audit["execution_status"] == "workflow_not_accepted"
    assert [finding["code"] for finding in audit["findings"]] == [
        "legacy_helper_workflow_unaccepted"
    ]


def test_boundary_audit_reports_rejected_control_plane_without_worker_regressions(tmp_path: Path) -> None:
    telemetry = tmp_path / "generated" / "telemetry"
    telemetry.mkdir(parents=True)
    (telemetry / "m3_integrated_demo_manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "steps": [
                    {
                        "node_id": "orchestrate",
                        "control_plane": True,
                        "record_status": "completed",
                    }
                ],
                "failure": {
                    "reason": "control_plane_bootstrap_rejected",
                    "message": "Initial control-plane workflow must be an object",
                },
            }
        ),
        encoding="utf-8",
    )
    (telemetry / "metrics_summary.yaml").write_text(
        yaml.safe_dump({"entries": [{"usage_source": "provider_attributed"}]}),
        encoding="utf-8",
    )

    audit = live_demo_boundary_run._summarize_audit(tmp_path)

    assert audit["overall"] == "failed"
    assert audit["execution_status"] == "control_plane_bootstrap_rejected"
    assert [finding["code"] for finding in audit["findings"]] == [
        "control_plane_bootstrap_rejected"
    ]


def test_boundary_audit_marks_timed_out_control_plane_inconclusive(tmp_path: Path) -> None:
    telemetry = tmp_path / "generated" / "telemetry"
    telemetry.mkdir(parents=True)
    (telemetry / "m3_integrated_demo_manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "steps": [{"node_id": "orchestrate", "control_plane": True, "record_status": "timed_out"}],
                "failure": {"reason": "control_plane_bootstrap_rejected"},
            }
        ),
        encoding="utf-8",
    )
    (telemetry / "metrics_summary.yaml").write_text(yaml.safe_dump({"entries": []}), encoding="utf-8")

    audit = live_demo_boundary_run._summarize_audit(tmp_path)

    assert audit["overall"] == "inconclusive"
    assert audit["execution_status"] == "provider_runtime_timeout"


def test_boundary_audit_rejects_nonterminal_run(tmp_path: Path) -> None:
    telemetry = tmp_path / "generated" / "telemetry"
    telemetry.mkdir(parents=True)
    (telemetry / "m3_integrated_demo_manifest.yaml").write_text(
        yaml.safe_dump({"steps": [], "terminal_complete": False}), encoding="utf-8"
    )
    (telemetry / "metrics_summary.yaml").write_text(
        yaml.safe_dump({"entries": []}), encoding="utf-8"
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "demo.py").write_text(
        "import sys\nprint('self-check passed' if '--check' in sys.argv else 'new')\n",
        encoding="utf-8",
    )

    audit = live_demo_boundary_run._summarize_audit(tmp_path)

    assert audit["overall"] == "failed"
    assert [finding["code"] for finding in audit["findings"]] == ["workflow_incomplete"]


def test_boundary_audit_executes_cli_instead_of_matching_source_text(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "demo.py").write_text(
        "import sys\nprint('self-check passed' if '--check' in sys.argv else 'new')\n",
        encoding="utf-8",
    )

    assert live_demo_boundary_run._cli_supports_task(tmp_path) is True


def test_boundary_audit_accepts_terminal_independent_verification_evidence(
    tmp_path: Path,
) -> None:
    telemetry = tmp_path / "generated" / "telemetry"
    assignments = tmp_path / "generated" / "assignments"
    results = tmp_path / "generated" / "results"
    workflows = tmp_path / "workflows"
    src = tmp_path / "src"
    for directory in (telemetry, assignments, results, workflows, src):
        directory.mkdir(parents=True, exist_ok=True)

    workflow_path = workflows / "accepted.yaml"
    workflow_path.write_text(
        yaml.safe_dump(
            {
                "status": "accepted",
                "nodes": [
                    {"id": "write_cli", "role": "coder", "emits": ["patch_ready"]},
                    {
                        "id": "inspect_patch",
                        "role": "reviewer",
                        "emits": ["review_approved"],
                    },
                    {
                        "id": "accept_cli",
                        "role": "verifier",
                        "emits": ["verification_passed"],
                    },
                    {
                        "id": "publish_release",
                        "role": "committer",
                        "emits": ["commit_complete"],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    manifest = {
        "workflow_path": str(workflow_path),
        "ledger_path": str(tmp_path / "ledger.yaml"),
        "terminal_complete": True,
        "steps": [
            {"node_id": "orchestrate", "control_plane": True, "record_status": "completed"},
            {"node_id": "write_cli", "record_status": "completed"},
            {"node_id": "inspect_patch", "record_status": "completed"},
            {"node_id": "accept_cli", "record_status": "completed"},
            {"node_id": "publish_release", "record_status": "completed"},
        ],
    }
    (telemetry / "m3_integrated_demo_manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    (telemetry / "metrics_summary.yaml").write_text(
        yaml.safe_dump(
            {"entries": [{"usage_source": "provider_attributed"}] * 5},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "ledger.yaml").write_text(
        yaml.safe_dump({"event_log": []}), encoding="utf-8"
    )
    (assignments / "inspect_patch_assignment.yaml").write_text(
        yaml.safe_dump({"role": "reviewer"}), encoding="utf-8"
    )
    (results / "inspect_patch_result.yaml").write_text(
        yaml.safe_dump({"verification": {"status": "passed"}}), encoding="utf-8"
    )
    (assignments / "accept_cli_assignment.yaml").write_text(
        yaml.safe_dump({"role": "verifier"}), encoding="utf-8"
    )
    (results / "accept_cli_result.yaml").write_text(
        yaml.safe_dump(
            {
                "verification": {
                    "status": "passed",
                    "evidence": {"command": "verify-demo", "observed": "passed"},
                }
            }
        ),
        encoding="utf-8",
    )
    (src / "demo.py").write_text(
        "import sys\nprint('self-check passed' if '--check' in sys.argv else 'new')\n",
        encoding="utf-8",
    )

    audit = live_demo_boundary_run._summarize_audit(tmp_path)

    assert audit["overall"] == "passed"
    assert audit["execution_status"] == "completed"
    assert audit["findings"] == []
