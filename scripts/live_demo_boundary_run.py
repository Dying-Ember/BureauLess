#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
LIVE_DEMO_ROOT = ROOT / "live-demos" / "2026-07-10-完整流程真实试跑"
INPUTS_DIR = LIVE_DEMO_ROOT / "inputs"


def _read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_yaml(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _load_task_inputs() -> dict[str, Any]:
    return {
        "task": (INPUTS_DIR / "task.md").read_text(encoding="utf-8"),
        "orchestrator_request": (
            INPUTS_DIR / "orchestrator_request.md"
        ).read_text(encoding="utf-8"),
        "assignment_expectations": (
            INPUTS_DIR / "assignment_expectations.md"
        ).read_text(encoding="utf-8"),
        "workflow_proposal": (
            INPUTS_DIR / "workflow_proposal.md"
        ).read_text(encoding="utf-8"),
        "control_plane_requirements": {
            "independent_verification": True,
            "terminal_commit": True,
        },
        "provider_allowed_worker_models": ["gpt-5.5"],
    }


def _overlay_boundary_task(paths: dict[str, Path], orchestrator_model: str) -> None:
    task_inputs = _load_task_inputs()

    mission_path = paths["mission"]
    mission = _read_yaml(mission_path)
    if not isinstance(mission, dict):
        raise ValueError("mission.yaml must be an object")
    mission["models"] = {
        orchestrator_model: {"role": "orchestrator"},
    }
    mission["goal"] = task_inputs["task"]
    mission["status"] = "active"
    _write_yaml(mission_path, mission)
    ledger_path = paths.get("ledger")
    if ledger_path is not None:
        ledger = _read_yaml(ledger_path)
        if not isinstance(ledger, dict):
            raise ValueError("ledger.yaml must be an object")
        ledger["current_goal"] = task_inputs["task"]
        _write_yaml(ledger_path, ledger)
    workflow_path = paths["workflow"]
    workflow = _read_yaml(workflow_path)
    if not isinstance(workflow, dict):
        raise ValueError("workflow YAML must be an object")
    workflow["status"] = "proposed"
    _write_yaml(workflow_path, workflow)

    readme = (
        "# BureauLess Boundary Demo Workspace\n\n"
        "这是任务发布人侧的高压 live-demo 工作区。\n\n"
        "外部硬约束：\n"
        "- 最终产物必须是最小 CLI，而不是单纯把 old 改成 new\n"
        "- 必须支持 --check\n"
        "- 最终验收验证不得由实现者本人执行\n"
        "- 如果现有 workflow 不足，必须显式 proposal / mutation\n\n"
        "模型边界：\n"
        "- 发布方只约束 orchestrator 的启动模型\n"
        "- 派生 worker / agent 的模型必须由 orchestrator 显式上报，再由 harness 审批\n\n"
        "请优先阅读以下输入，而不是沿用旧 demo helper 的默认语义：\n"
        "- task-publisher/task.md\n"
        "- task-publisher/orchestrator_request.md\n"
        "- task-publisher/assignment_expectations.md\n"
        "- task-publisher/workflow_proposal.md\n"
    )
    (paths["mission"].parent / "README.md").write_text(readme, encoding="utf-8")

    task_dir = mission_path.parent / "task-publisher"
    task_dir.mkdir(parents=True, exist_ok=True)
    for name, content in task_inputs.items():
        if not isinstance(content, str):
            continue
        (task_dir / f"{name}.md").write_text(content, encoding="utf-8")

    # Keep a sentinel patch so the post-run audit can detect helper contamination
    # instead of silently accepting the legacy one-line patch.
    sentinel_patch = (
        "# sentinel: legacy old->new patch must not be treated as sufficient\n"
        "# boundary task requires CLI, --check, and independent verification\n"
    )
    (mission_path.parent / "artifacts" / "implement_patch.diff").write_text(
        sentinel_patch,
        encoding="utf-8",
    )
    (mission_path.parent / "artifacts" / "review_report.md").write_text(
        "# Boundary Review Placeholder\n\n"
        "Review text alone is not sufficient. Independent verification evidence is required.\n",
        encoding="utf-8",
    )
    (mission_path.parent / "artifacts" / "commit_note.md").write_text(
        "# Boundary Commit Placeholder\n\n"
        "Commit must depend on explicit verification evidence, not only review approval.\n",
        encoding="utf-8",
    )


def _cli_supports_task(workspace: Path) -> bool:
    try:
        default = subprocess.run(
            [sys.executable, "-B", "src/demo.py"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=5,
        )
        check = subprocess.run(
            [sys.executable, "-B", "src/demo.py", "--check"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return (
        default.returncode == 0
        and default.stdout.strip() == "new"
        and check.returncode == 0
        and "passed" in check.stdout.lower()
    )


def _load_optional(path: Path) -> Any:
    if not path.exists():
        return None
    return _read_yaml(path)


def _summarize_audit(workspace: Path) -> dict[str, Any]:
    manifest_path = workspace / "generated" / "telemetry" / "m3_integrated_demo_manifest.yaml"
    metrics_path = workspace / "generated" / "telemetry" / "metrics_summary.yaml"
    src_path = workspace / "src" / "demo.py"
    workflow_path = workspace / "workflows" / "coder_reviewer_committer.yaml"
    ledger_path = workspace / "ledger.yaml"

    manifest = _read_yaml(manifest_path)
    metrics = _read_yaml(metrics_path)
    if isinstance(manifest, dict) and isinstance(manifest.get("workflow_path"), str):
        workflow_path = Path(manifest["workflow_path"])
    if isinstance(manifest, dict) and isinstance(manifest.get("ledger_path"), str):
        ledger_path = Path(manifest["ledger_path"])
    workflow = _load_optional(workflow_path)
    ledger = _load_optional(ledger_path)
    workflow_nodes = workflow.get("nodes", []) if isinstance(workflow, dict) else []
    review_node = next(
        (
            node
            for node in workflow_nodes
            if isinstance(node, dict)
            and any(
                isinstance(event, str) and "review" in event.casefold()
                for event in node.get("emits", [])
            )
        ),
        None,
    )
    verification_nodes = [
        node
        for node in workflow_nodes
        if isinstance(node, dict)
        and any(
            isinstance(event, str) and "verification" in event.casefold()
            for event in node.get("emits", [])
        )
    ]
    review_node_id = review_node.get("id") if isinstance(review_node, dict) else "review"
    review_result_path = workspace / "generated" / "results" / f"{review_node_id}_result.yaml"
    review_assignment_path = workspace / "generated" / "assignments" / f"{review_node_id}_assignment.yaml"
    review_result = _load_optional(review_result_path)
    review_assignment = _load_optional(review_assignment_path)

    metric_entries = metrics.get("entries", []) if isinstance(metrics, dict) else []
    provider_attributed_count = sum(
        1
        for entry in metric_entries
        if isinstance(entry, dict) and entry.get("usage_source") == "provider_attributed"
    )
    ledger_events = ledger.get("event_log", []) if isinstance(ledger, dict) else []
    mutation_refs = [
        event.get("event_id")
        for event in ledger_events
        if isinstance(event, dict)
        and event.get("event_type") == "workflow_mutation_proposed"
    ]

    review_role = None
    if isinstance(review_assignment, dict):
        review_role = review_assignment.get("role")

    step_record_statuses = []
    for step in manifest.get("steps", []) if isinstance(manifest, dict) else []:
        attempts = step.get("attempts") if isinstance(step, dict) else None
        if isinstance(attempts, list) and attempts:
            step_record_statuses.extend(
                {
                    "node_id": step.get("node_id"),
                    "record_status": attempt.get("record_status"),
                    "control_plane": True,
                    "attempt": attempt.get("attempt"),
                }
                for attempt in attempts
                if isinstance(attempt, dict)
            )
            continue
        if isinstance(step, dict):
            step_record_statuses.append(
                {
                    "node_id": step.get("node_id"),
                    "record_status": step.get("record_status"),
                    "control_plane": step.get("control_plane", False),
                }
            )
    timed_out_nodes = [
        step["node_id"]
        for step in step_record_statuses
        if step["record_status"] == "timed_out"
    ]
    completed_nodes = [
        step["node_id"]
        for step in step_record_statuses
        if step["record_status"] == "completed"
    ]
    workflow_is_proposed = isinstance(workflow, dict) and workflow.get("status") == "proposed"
    failure = manifest.get("failure", {}) if isinstance(manifest, dict) else {}
    bootstrap_rejected = (
        isinstance(failure, dict)
        and failure.get("reason") == "control_plane_bootstrap_rejected"
    )
    terminal_complete = bool(manifest.get("terminal_complete")) if isinstance(manifest, dict) else False
    findings: list[dict[str, Any]] = []

    if timed_out_nodes:
        findings.append(
            {
                "severity": "high",
                "code": "provider_runtime_timeout",
                "message": (
                    "节点在产出结果前超时；本轮未覆盖后续 workflow、"
                    "独立 verify 或 commit，不能归因为 workflow 或 harness 逻辑。"
                ),
                "evidence": str(manifest_path),
            }
        )
    elif bootstrap_rejected:
        findings.append(
            {
                "severity": "high",
                "code": "control_plane_bootstrap_rejected",
                "message": "orchestrator 控制面产物未通过 harness 协议校验；没有派发 worker。",
                "evidence": str(manifest_path),
            }
        )
    elif workflow_is_proposed:
        findings.append(
            {
                "severity": "high",
                "code": "legacy_helper_workflow_unaccepted",
                "message": (
                    "旧三节点 helper workflow 仍为 proposed，却被 runner 用作执行入口；"
                    "这属于控制面污染，不能作为任务执行或验收链覆盖。"
                ),
                "evidence": str(workflow_path),
            }
        )
    elif not _cli_supports_task(workspace):
        findings.append(
            {
                "severity": "high",
                "code": "task_not_implemented",
                "message": "最终代码没有实现 CLI / --check，高压任务目标未完成。",
                "evidence": str(src_path),
            }
        )

    expected_review_role = (
        review_node.get("role") if isinstance(review_node, dict) else None
    )
    if (
        not bootstrap_rejected
        and not timed_out_nodes
        and not workflow_is_proposed
        and review_assignment is not None
        and expected_review_role is not None
        and review_role != expected_review_role
    ):
        findings.append(
            {
                "severity": "medium",
                "code": "unexpected_review_role",
                "message": "review assignment 角色异常，需人工确认。",
                "evidence": str(review_assignment_path),
            }
        )

    if (
        not bootstrap_rejected
        and not timed_out_nodes
        and not workflow_is_proposed
        and isinstance(review_result, dict)
        and not verification_nodes
    ):
        verification = review_result.get("verification", {})
        command = verification.get("command") if isinstance(verification, dict) else None
        if isinstance(command, str) and "python" in command and "src/demo.py" in command:
            findings.append(
                {
                    "severity": "high",
                    "code": "independent_verification_not_proven",
                    "message": "review 节点只是直接运行 src/demo.py，没有出现独立 verification assignment / artifact。",
                    "evidence": str(review_result_path),
                }
            )

    if (
        not bootstrap_rejected
        and not timed_out_nodes
        and not workflow_is_proposed
        and isinstance(workflow, dict)
    ):
        if not verification_nodes:
            findings.append(
                {
                    "severity": "high",
                    "code": "independent_verification_assignment_missing",
                    "message": "accepted workflow 没有独立 verification assignment，不能满足发布方约束。",
                    "evidence": str(workflow_path),
                }
            )
        for node in verification_nodes:
            node_id = node.get("id")
            if not isinstance(node_id, str):
                continue
            assignment_path = (
                workspace / "generated" / "assignments" / f"{node_id}_assignment.yaml"
            )
            result_path = workspace / "generated" / "results" / f"{node_id}_result.yaml"
            assignment = _load_optional(assignment_path)
            result = _load_optional(result_path)
            if terminal_complete and (assignment is None or result is None):
                findings.append(
                    {
                        "severity": "high",
                        "code": "independent_verification_evidence_missing",
                        "message": "workflow 已终止但独立 verification assignment/result 证据缺失。",
                        "evidence": str(result_path),
                    }
                )
                continue
            if not isinstance(result, dict):
                continue
            verification = result.get("verification", {})
            verification_passed = (
                isinstance(verification, dict)
                and verification.get("status") == "passed"
            )
            structured_evidence = (
                isinstance(verification, dict)
                and any(
                    key not in {"status", "final_independent_verification"}
                    and value not in (None, "", [], {})
                    for key, value in verification.items()
                )
            )
            task_artifact = any(
                isinstance(artifact, dict)
                and artifact.get("artifact_type") != "provider_usage_capture"
                for artifact in result.get("artifacts", [])
            )
            if not verification_passed or not (structured_evidence or task_artifact):
                findings.append(
                    {
                        "severity": "high",
                        "code": "independent_verification_not_proven",
                        "message": "独立 verifier 未留下 passed 的结构化执行证据或任务 artifact。",
                        "evidence": str(result_path),
                    }
                )

    if (
        not bootstrap_rejected
        and not timed_out_nodes
        and not workflow_is_proposed
        and review_result is not None
        and not mutation_refs
        and not verification_nodes
        and isinstance(workflow, dict)
    ):
        findings.append(
            {
                "severity": "medium",
                "code": "no_mutation_evidence",
                "message": "本轮未出现 mutation proposal 证据；若任务确实需要结构升级，当前入口没有给它触发机会。",
                "evidence": str(review_result_path),
            }
        )

    if completed_nodes and provider_attributed_count < len(completed_nodes):
        findings.append(
            {
                "severity": "medium",
                "code": "telemetry_missing_for_executed_nodes",
                "message": "provider_attributed 未覆盖全部已执行节点，需检查 usage capture。",
                "evidence": str(metrics_path),
            }
        )

    if not terminal_complete and not timed_out_nodes and not bootstrap_rejected and not workflow_is_proposed:
        findings.append(
            {
                "severity": "high",
                "code": "workflow_incomplete",
                "message": "本轮未达到 workflow terminal event，不能验收为通过。",
                "evidence": str(manifest_path),
            }
        )

    overall = "inconclusive" if timed_out_nodes else (
        "failed" if any(item["severity"] == "high" for item in findings) else "passed"
    )

    return {
        "overall": overall,
        "workspace": str(workspace),
        "manifest_path": str(manifest_path),
        "metrics_summary_path": str(metrics_path),
        "provider_attributed_count": provider_attributed_count,
        "completed_node_count": len(completed_nodes),
        "execution_status": (
            "provider_runtime_timeout" if timed_out_nodes
            else "control_plane_bootstrap_rejected"
            if bootstrap_rejected
            else "workflow_not_accepted" if workflow_is_proposed
            else "completed" if terminal_complete else "workflow_incomplete"
        ),
        "failure": failure,
        "timed_out_nodes": timed_out_nodes,
        "step_record_statuses": step_record_statuses,
        "findings": findings,
    }


def _write_markdown_report(path: Path, audit: dict[str, Any]) -> None:
    lines = [
        "# 任务发布人侧审计结果",
        "",
        f"- 总体结论：`{audit['overall']}`",
        f"- 工作区：`{audit['workspace']}`",
        f"- manifest：`{audit['manifest_path']}`",
        f"- metrics：`{audit['metrics_summary_path']}`",
        f"- provider_attributed 节点数：`{audit['provider_attributed_count']}`",
        f"- 执行判定：`{audit.get('execution_status', 'completed')}`",
        "",
        "## 节点状态",
        "",
    ]
    for step in audit.get("step_record_statuses", []):
        label = "control-plane" if step.get("control_plane") else "worker"
        lines.append(
            f"- `{step.get('node_id')}` ({label}): `{step.get('record_status')}`"
        )
    failure = audit.get("failure") or {}
    if audit.get("execution_status") == "control_plane_bootstrap_rejected":
        lines.extend(
            [
                "",
                "## 控制面拒绝",
                "",
                "- orchestrator 会话已完成，但控制面产物未通过 harness 协议校验；没有派发 worker。",
                f"- 拒绝原因：`{failure.get('message', 'unavailable')}`",
                f"- 会话证据：`{failure.get('session_path', 'unavailable')}`",
            ]
        )
    if audit.get("timed_out_nodes"):
        lines.extend(
            [
                "",
                "## 覆盖边界",
                "",
                "- 节点在产出结果前被 240 秒 timeout 截断；未进入后续 workflow、独立 verify 或 commit。",
                "- 该轮只能归类为 provider/runtime 执行链路问题，不能作为 workflow 或 harness 逻辑失败的证据。",
                f"- 会话证据：`{failure.get('session_path', 'unavailable')}`",
            ]
        )
    lines.extend(["", "## 发现", ""])
    for finding in audit.get("findings", []):
        lines.append(
            f"- [{finding['severity']}] `{finding['code']}`: {finding['message']}  "
            f"证据：`{finding['evidence']}`"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the maintained live demo through a task-publisher wrapper and audit boundary coverage."
    )
    parser.add_argument("workspace", help="Run workspace directory")
    parser.add_argument("--agent", default="codex-cli")
    parser.add_argument("--target-model", required=True)
    parser.add_argument("--target-provider", default="openai-compatible")
    parser.add_argument("--provider-base-url", required=True)
    parser.add_argument("--provider-api-key-env", required=True)
    parser.add_argument("--provider-wire-api", default="responses")
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    cli = importlib.import_module("bureauless.cli.main")
    original_prepare = cli.prepare_demo_workspace

    def patched_prepare_demo_workspace(workspace_path: Path, **kwargs: Any) -> dict[str, Path]:
        paths = original_prepare(workspace_path, **kwargs)
        _overlay_boundary_task(paths, args.target_model)
        return paths

    cli.prepare_demo_workspace = patched_prepare_demo_workspace
    try:
        manifest = cli.run_live_demo(
            workspace,
            agent_id=args.agent,
            target_model=args.target_model,
            target_provider=args.target_provider,
            provider_base_url=args.provider_base_url,
            provider_api_key_env=args.provider_api_key_env,
            provider_wire_api=args.provider_wire_api,
            timeout_seconds=args.timeout_seconds,
            bootstrap_context=_load_task_inputs(),
        )
    finally:
        cli.prepare_demo_workspace = original_prepare

    audit = _summarize_audit(workspace)
    audit["terminal_complete"] = manifest.get("terminal_complete")
    audit["failure"] = manifest.get("failure")

    audit_json_path = workspace / "notes" / "publisher_audit.json"
    audit_md_path = workspace / "notes" / "publisher_audit.md"
    audit_json_path.parent.mkdir(parents=True, exist_ok=True)
    audit_json_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_markdown_report(audit_md_path, audit)

    print(
        json.dumps(
            {
                "manifest_path": str(
                    workspace / "generated" / "telemetry" / "m3_integrated_demo_manifest.yaml"
                ),
                "audit_json_path": str(audit_json_path),
                "audit_md_path": str(audit_md_path),
                "overall": audit["overall"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
