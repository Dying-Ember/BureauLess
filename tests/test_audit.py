from pathlib import Path
import hashlib
import shlex
import sys

import pytest
import yaml

from bureauless.cli.audit import (
    _verification_freshness,
    build_capability_contribution,
    load_route_observations,
)
from bureauless.cli.main import main
from bureauless.errors import ProtocolError
from bureauless.agents import list_agent_route_evidence, resolve_agent_binding, route_agent
from bureauless.runtime.sessions import (
    _build_claude_code_environment,
    _extract_claude_json,
    _extract_claude_stream_json,
    _extract_opencode_jsonl,
    _extract_pi_jsonl,
    load_session_record,
    run_independent_verification,
)
from bureauless.runtime.metrics import summarize_metrics
from bureauless.protocol.harness import load_ledger, load_mission, load_workflow


def test_audit_init_creates_valid_single_agent_control_plane(tmp_path: Path) -> None:
    assert main(["audit", "init", "--workspace", str(tmp_path), "--task", "Fix the parser"]) == 0

    root = tmp_path / ".bureauless"
    assert load_mission(root / "mission.yaml").goal == "Fix the parser"
    assert load_workflow(root / "workflow.yaml").mode == "single_agent"
    assert load_ledger(root / "ledger.yaml").ledger_version == 2


def test_audit_run_materializes_the_canonical_dry_run_evidence_chain(
    tmp_path: Path, capsys
) -> None:
    assert main(["audit", "init", "--workspace", str(tmp_path), "--task", "Fix parser"]) == 0
    capsys.readouterr()

    assert main(
        [
            "audit",
            "run",
            "--workspace",
            str(tmp_path),
            "--agent",
            "codex-cli",
            "--target-model",
            "gpt-5",
            "--target-provider",
            "openai",
            "--cohort-id",
            "parser-benchmark-v1",
            "--session-id",
            "session-dry-run",
            "--dry-run",
        ]
    ) == 0

    result = yaml.safe_load(capsys.readouterr().out)
    assert result["status"] == "dry_run"
    for key in (
        "assignment",
        "routing",
        "registration",
        "dispatch",
        "session",
        "report",
        "route_observation",
        "archive_manifest",
    ):
        assert Path(result[key]).is_file()
    session = yaml.safe_load(Path(result["session"]).read_text(encoding="utf-8"))
    assert session["agent_id"] == "codex-cli"
    assert session["dispatch"]["session_spec"]["target_model"] == "gpt-5"
    assert session["dispatch"]["agent_registration"]["route"]["wire_api"] is None
    assert session["dispatch"]["agent_registration"]["doctor"] is None
    assert session["dispatch"]["agent_registration"]["verification_freshness"] == "not_checked"
    assert session["outcome_metrics"]["cost_source"] == "unavailable"
    assert session["audit_evidence"]["independent_verification"] == {
        "source": "harness",
        "status": "not_run",
        "reason": "not_requested",
    }
    assert session["audit_evidence"]["decision_points"][0]["decision_type"] == "dispatch"
    assert session["audit_evidence"]["decision_points"][0]["later_outcome"] == {
        "session_status": "dry_run",
        "exit_reason": "dry_run",
        "changed_files_count": 0,
        "agent_verification_status": "not_run",
        "independent_verification_status": "not_run",
    }
    benchmark = session["audit_evidence"]["benchmark_identity"]
    assert benchmark["cohort_id"] == "parser-benchmark-v1"
    assert benchmark["cohort_declared"] is True
    assert benchmark["trial_id"] == "session-dry-run"
    assert benchmark["schema"] == "bureauless_benchmark_identity_v2"
    assert len(benchmark["task_contract_sha256"]) == 64
    assert len(benchmark["context_contract_sha256"]) == 64
    assert len(benchmark["execution_contract_sha256"]) == 64
    assert benchmark["execution_contract"]["target_model"] == "gpt-5"
    assert benchmark["execution_contract"]["assignment_renderer_version"] == "assignment_prompt_v1"
    assert benchmark["workspace_baseline_ref"] is None
    assert benchmark["acceptance_contract_sha256"] is None
    assert {
        key: value["status"]
        for key, value in session["audit_evidence"]["side_effect_coverage"].items()
    } == {
        "workspace": "none",
        "process": "not_applicable",
        "network": "none",
        "credential": "none",
        "payment": "none",
    }
    decision = session["audit_evidence"]["decision_points"][0]
    assert decision["candidate_set"][0]["disposition"] == "selected"
    assert len(decision["candidate_set"]) == 5
    assert decision["selection_scope"]["agent_id"] == "operator_fixed"
    assert decision["selection_basis"]["budget_confidence"] == "low"
    assert result["verification"] is None
    report = Path(result["report"]).read_text(encoding="utf-8")
    assert "Review status: `not_run`" in report
    assert "Review status: `awaiting_human_review`" not in report
    assert Path(result["archive_manifest"]).with_name("route-observation.yaml").is_file()
    metrics = summarize_metrics(tmp_path / ".bureauless" / "runs")
    assert metrics["observed_budget"]["session_count"] == 1
    assert metrics["comparison"]["token_usage"]["eligibility"] == "unavailable"
    assert main(["audit", "observations", "--workspace", str(tmp_path)]) == 0
    observations = yaml.safe_load(capsys.readouterr().out)
    assert observations[0]["route_instance_id"] == "unidentified"
    assert observations[0]["outcome"]["session_status"] == "dry_run"
    assert observations[0]["benchmark_identity"] == benchmark

    runs = tmp_path / ".bureauless" / "runs"
    assert main(
        ["agent", "matrix", "--evidence", "--observations", str(runs)]
    ) == 0
    matrix = yaml.safe_load(capsys.readouterr().out)
    assert len(matrix["observations"]) == 1
    assert matrix["observations"][0]["session_id"] == "session-dry-run"

    observation_path = Path(result["route_observation"])
    tampered = yaml.safe_load(observation_path.read_text(encoding="utf-8"))
    tampered["outcome"]["session_status"] = "completed"
    observation_path.write_text(yaml.safe_dump(tampered, sort_keys=False), encoding="utf-8")
    with pytest.raises(ProtocolError, match="does not match session evidence"):
        load_route_observations(runs)


def test_runtime_version_freshness_does_not_inherit_old_route_verification() -> None:
    route = {"verified_runtime_version": "1.17.18"}

    assert _verification_freshness(route, {"version": "opencode 1.17.18"}) == "matching"
    assert _verification_freshness(route, {"version": "opencode 1.17.20"}) == "version_drift"


def test_independent_verifier_isolated_workspace_and_credentials(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace.joinpath("source.txt").write_text("ready\n", encoding="utf-8")
    monkeypatch.setenv("TEST_PROVIDER_SECRET_TOKEN", "must-not-leak")
    script = (
        "import os; from pathlib import Path; "
        "assert Path('source.txt').read_text() == 'ready\\n'; "
        "Path('verifier.tmp').write_text('created'); "
        "print(os.getenv('TEST_PROVIDER_SECRET_TOKEN', 'missing'))"
    )

    evidence = run_independent_verification(
        f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}",
        workspace,
    )

    assert evidence["status"] == "passed"
    assert evidence["source"] == "harness"
    assert evidence["stdout"].strip() == "missing"
    assert len(evidence["acceptance_contract_sha256"]) == 64
    assert evidence["environment_policy"] == "secret_named_variables_removed"
    assert not workspace.joinpath("verifier.tmp").exists()


def test_capability_contribution_requires_matched_verified_pair(
    tmp_path: Path, capsys
) -> None:
    identity = {
        "schema": "bureauless_benchmark_identity_v2",
        "cohort_id": "cohort-1",
        "cohort_declared": True,
        "trial_id": "placeholder",
        "task_contract_sha256": "task-sha",
        "context_contract_sha256": "context-sha",
        "execution_contract_sha256": "execution-sha",
        "execution_contract": {
            "agent_id": "codex-cli",
            "target_model": "gpt-5",
            "target_provider": "openai",
        },
        "workspace_baseline_ref": "workspace-sha",
        "acceptance_contract_sha256": "verify-sha",
    }

    def write_session(name: str, wall_time: int, changed_files: int) -> Path:
        path = tmp_path / f"{name}.yaml"
        execution_contract = {
            **identity["execution_contract"],
            "target_model": "gpt-5.1" if name == "candidate" else "gpt-5",
        }
        benchmark = {
            **identity,
            "trial_id": name,
            "execution_contract_sha256": hashlib.sha256(
                yaml.safe_dump(execution_contract, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "execution_contract": execution_contract,
        }
        path.write_text(
            yaml.safe_dump(
                {
                    "session_id": name,
                    "assignment_id": f"assign-{name}",
                    "agent_id": "codex-cli",
                    "status": "completed",
                    "started_at": "2026-07-15T00:00:00Z",
                    "finished_at": "2026-07-15T00:00:01Z",
                    "exit": {"code": 0, "reason": "completed"},
                    "native_logs": {},
                    "diff_refs": [],
                    "artifacts": [],
                    "workspace": {},
                    "outcome_metrics": {
                        "wall_time_ms": wall_time,
                        "changed_files_count": changed_files,
                        "total_tokens": wall_time,
                        "usage_source": "provider_reported",
                        "cost_usd": wall_time / 1000,
                        "cost_source": "provider_reported",
                    },
                    "extraction": {},
                    "result_proposal": None,
                    "audit_evidence": {
                        "benchmark_identity": benchmark,
                        "independent_verification": {
                            "source": "harness",
                            "status": "passed",
                        },
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return path

    baseline = write_session("baseline", 100, 1)
    candidate = write_session("candidate", 80, 2)
    contribution = build_capability_contribution(
        baseline,
        candidate,
        capability_id="workspace-edit",
        invoked=True,
    )

    record = contribution["capability_contribution"]
    assert record["invoked"] is True
    assert record["result_used"] == "unknown"
    assert record["measurable_delta"]["wall_time_ms"]["delta"] == -20
    assert record["measurable_delta"]["total_tokens"]["eligibility"] == "conditional"
    assert contribution["causal_claim"] == "not_established"
    assert contribution["schema"] == "bureauless_capability_contribution_v2"
    assert contribution["treatment_diff"]["target_model"] == {
        "baseline": "gpt-5",
        "candidate": "gpt-5.1",
    }
    assert "network_conditions_not_controlled" in contribution["uncontrolled_confounders"]
    output = tmp_path / "contribution.yaml"
    assert main(
        [
            "audit",
            "contribution",
            str(baseline),
            str(candidate),
            "--capability-id",
            "workspace-edit",
            "--invoked",
            "true",
            "--output",
            str(output),
        ]
    ) == 0
    assert yaml.safe_load(output.read_text(encoding="utf-8")) == contribution
    capsys.readouterr()

    tampered = yaml.safe_load(candidate.read_text(encoding="utf-8"))
    tampered["audit_evidence"]["benchmark_identity"]["task_contract_sha256"] = "other-task"
    candidate.write_text(yaml.safe_dump(tampered, sort_keys=False), encoding="utf-8")
    with pytest.raises(ProtocolError, match="identity mismatch: task_contract_sha256"):
        build_capability_contribution(
            baseline,
            candidate,
            capability_id="workspace-edit",
            invoked=True,
        )
    tampered["audit_evidence"]["benchmark_identity"]["task_contract_sha256"] = "task-sha"
    tampered["audit_evidence"]["benchmark_identity"]["context_contract_sha256"] = "other-context"
    candidate.write_text(yaml.safe_dump(tampered, sort_keys=False), encoding="utf-8")
    with pytest.raises(ProtocolError, match="identity mismatch: context_contract_sha256"):
        build_capability_contribution(
            baseline,
            candidate,
            capability_id="workspace-edit",
            invoked=True,
        )


def test_benchmark_context_identity_ignores_transport_assignment_ids(
    tmp_path: Path, capsys
) -> None:
    assert main(["audit", "init", "--workspace", str(tmp_path), "--task", "Fix parser"]) == 0
    capsys.readouterr()
    sessions = []
    for session_id in ("trial-a", "trial-b"):
        assert main(
            [
                "audit", "run", "--workspace", str(tmp_path), "--agent", "codex-cli",
                "--target-model", "gpt-5", "--target-provider", "openai",
                "--cohort-id", "cohort-1", "--session-id", session_id, "--dry-run",
            ]
        ) == 0
        sessions.append(yaml.safe_load(capsys.readouterr().out)["session"])
    identities = [
        yaml.safe_load(Path(path).read_text(encoding="utf-8"))["audit_evidence"]
        ["benchmark_identity"]
        for path in sessions
    ]
    assert identities[0]["context_contract_sha256"] == identities[1][
        "context_contract_sha256"
    ]


@pytest.mark.parametrize(
    "route_instance_id",
    ["https://gateway.example/v1", "route name", "a/b", "sk-" + "x" * 30],
)
def test_audit_rejects_non_opaque_route_instance_labels(
    tmp_path: Path, route_instance_id: str
) -> None:
    assert main(["audit", "init", "--workspace", str(tmp_path), "--task", "Fix parser"]) == 0
    assert main(
        [
            "audit", "run", "--workspace", str(tmp_path), "--agent", "codex-cli",
            "--target-model", "gpt-5", "--target-provider", "openai",
            "--route-instance-id", route_instance_id, "--dry-run",
        ]
    ) == 1


def test_audit_report_renders_existing_session_evidence(tmp_path: Path) -> None:
    session = tmp_path / "session.yaml"
    session.write_text(
        yaml.safe_dump(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                "agent_id": "codex-cli",
                "status": "completed",
                "started_at": "2026-07-13T00:00:00Z",
                "finished_at": "2026-07-13T00:01:00Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {"stdout": "", "stderr": ""},
                "diff_refs": [{"kind": "inline_patch", "bytes": 12}],
                "artifacts": [],
                "workspace": {},
                "outcome_metrics": {"changed_files_count": 1, "total_tokens": 42, "cost_usd": 0.01},
                "extraction": {"verification": {"status": "passed"}},
                "audit_evidence": {
                    "decision_points": [
                        {
                            "evidence_available_at_time": ["tests failed"],
                            "action_selected": "repair parser",
                            "alternatives_visible": ["revert", "repair parser"],
                            "later_outcome": {"verification": "passed"},
                        }
                    ],
                    "side_effects": [
                        {"type": "workspace", "source": "harness", "verified": True}
                    ],
                    "capability_contributions": [
                        {
                            "capability_id": "edit",
                            "invoked": True,
                            "result_used": True,
                            "measurable_delta": {"changed_files": 1},
                        }
                    ],
                },
                "result_proposal": {
                    "effective_model": "gpt-5",
                    "effective_provider": "openai",
                    "review_status": "pending",
                    "model_identity": {"requested": "gpt-5", "provider_reported": ["gpt-5.1"]},
                    "route_evidence": {
                        "runtime_contract_support": "supported",
                        "adapter_support": "implemented",
                        "tested_route_support": "verified",
                        "session_route_support": "verified",
                        "verification_levels": ["live_workspace_mutation"],
                    },
                    "metric_provenance": {
                        "wall_time": "harness",
                        "file_delta": "harness",
                        "token_usage": "provider_reported",
                        "monetary_cost": "provider_reported",
                        "tool_timeline": "native_event_stream",
                        "comparison_eligibility": {
                            "latency": "comparable",
                            "file_delta": "comparable",
                            "token_usage": "conditional",
                            "monetary_cost": "conditional",
                            "tool_timeline": "comparable",
                        },
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assert main(["audit", "report", str(session)]) == 0
    report = session.with_suffix(".audit.md").read_text(encoding="utf-8")
    assert "Changed files: `1`" in report
    assert "Agent-reported verification: `passed`" in report
    assert "Independent verification: `not_run`" in report
    assert "Total tokens: `42`" in report
    assert "Provider reported: `gpt-5.1`" in report
    assert "Tested route support: `verified`" in report
    assert "This session's route support: `verified`" in report
    assert "Token usage: `provider_reported`" in report
    assert "Decision points: `1`" in report
    assert "Side effects: `workspace:harness:True`" in report
    assert "Capability contributions: `1`" in report
    comparison = summarize_metrics(session)["comparison"]
    assert comparison["latency"]["eligibility"] == "comparable"
    assert comparison["token_usage"]["eligibility"] == "conditional"
    assert comparison["token_usage"]["sources"] == ["provider_reported"]

    assert main(["audit", "archive", str(session), "--workspace", str(tmp_path)]) == 0
    archive = tmp_path / ".bureauless" / "audits" / "2026-07-13" / "session-001"
    assert (archive / "session.yaml").read_bytes() == session.read_bytes()
    manifest = yaml.safe_load((archive / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["source_sha256"] == hashlib.sha256(session.read_bytes()).hexdigest()
    assert manifest["report_sha256"] == hashlib.sha256((archive / "report.md").read_bytes()).hexdigest()
    assert "Route evidence" in (archive / "report.md").read_text(encoding="utf-8")
    assert main(["audit", "verify", str(archive / "manifest.yaml")]) == 0


def test_session_audit_evidence_rejects_unproven_schema_values() -> None:
    with pytest.raises(ProtocolError, match="Side effect verified"):
        load_session_record(
            {
                "session_id": "session-001",
                "assignment_id": "assign-001",
                "agent_id": "codex-cli",
                "status": "completed",
                "started_at": "2026-07-13T00:00:00Z",
                "finished_at": "2026-07-13T00:01:00Z",
                "exit": {"code": 0, "reason": "completed"},
                "native_logs": {},
                "audit_evidence": {
                    "side_effects": [
                        {"type": "workspace", "source": "harness", "verified": "yes"}
                    ]
                },
            }
        )


def test_agent_routes_distinguish_registered_and_dispatchable_agents() -> None:
    assert route_agent("codex-cli").state == "dispatchable"
    claude = route_agent("claude-code")
    assert claude.state == "dispatchable"
    assert claude.output_contract == "jsonl"
    assert claude.comparison_eligibility["tool_timeline"] == "comparable"
    gemini = route_agent("gemini")
    assert gemini.state == "dispatchable"
    assert gemini.output_contract == "jsonl"
    assert route_agent("opencode").state == "dispatchable"
    assert route_agent("opencode").output_contract == "jsonl"
    pi = route_agent("pi")
    assert pi.state == "dispatchable"
    assert pi.output_contract == "jsonl"


def test_agent_route_keeps_runtime_and_tested_endpoint_evidence_separate() -> None:
    pi_responses = route_agent("pi", "openai-compatible")

    assert pi_responses.state == "registration_only"
    assert pi_responses.runtime_contract_support == "observed"
    assert pi_responses.adapter_support == "not_implemented"
    assert pi_responses.tested_route_support == "unavailable"
    assert pi_responses.route_kind == "custom_http"
    assert pi_responses.endpoint_family == "openai"
    assert pi_responses.wire_api == "responses"
    assert pi_responses.comparison_eligibility["monetary_cost"] == "not_comparable"
    assert (
        route_agent("pi", "anthropic-compatible").comparison_eligibility[
            "monetary_cost"
        ]
        == "conditional"
    )

    claude = route_agent("claude-code", "anthropic-compatible")
    assert claude.capability_evidence["clean_stateless_startup"] == "verified"
    assert claude.capability_evidence["native_tool_timeline"] == "verified"
    assert claude.wire_api == "messages"
    assert claude.audit_ref == "docs/audits/2026-07-15-agent-endpoint-capability-matrix.md"
    assert claude.verified_at == "2026-07-15"
    assert claude.verified_runtime_version == "2.1.202"
    assert {route.target_provider for route in list_agent_route_evidence("pi")} == {
        "anthropic-compatible",
        "openai-chat-compatible",
        "openai-compatible",
    }


def test_protocol_contract_links_to_a_dated_compatibility_audit() -> None:
    contract = Path("docs/protocol/agent_provider_registry.md").read_text(encoding="utf-8")

    assert "2026-07-13-agent-provider-compatibility.md" in contract
    assert "2026-07-15-agent-endpoint-capability-matrix.md" in contract
    assert "Current capability matrix" in contract
    assert "ANTHROPIC_API_KEY" in contract
    assert "OpenCode is registered but still lacks" not in contract


def test_claude_json_extracts_usage_and_cost() -> None:
    metrics, extraction = _extract_claude_json(
        '{"type":"result","result":"OK","usage":{"input_tokens":5,"output_tokens":1},"total_cost_usd":0.004}'
    )

    assert metrics["input_tokens"] == 5
    assert metrics["output_tokens"] == 1
    assert metrics["cost_usd"] == 0.004
    assert extraction["assistant_text"] == "OK"


def test_claude_stream_extracts_tool_timeline_usage_and_result() -> None:
    metrics, extraction = _extract_claude_stream_json(
        "\n".join(
            [
                '{"type":"system","subtype":"init","session_id":"session-1"}',
                '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"tool-1","name":"Edit","input":{}}]}}',
                '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tool-1","content":"ok"}]}}',
                '{"type":"result","result":"OK","usage":{"input_tokens":5,"output_tokens":1},"total_cost_usd":0.004}',
            ]
        )
    )

    assert metrics["input_tokens"] == 5
    assert metrics["cost_usd"] == 0.004
    assert extraction["native_event_stream_observed"] is True
    assert extraction["assistant_text"] == "OK"
    assert extraction["native_tool_events"] == [
        {
            "event_id": "tool-1",
            "event_type": "tool_use",
            "tool_name": "Edit",
            "source_ref": "stdout:2",
        },
        {
            "event_id": "tool-1",
            "event_type": "tool_result",
            "tool_name": None,
            "is_error": False,
            "source_ref": "stdout:3",
        },
    ]


def test_claude_binding_uses_a_one_shot_anthropic_compatible_endpoint() -> None:
    binding = resolve_agent_binding(
        "claude-code",
        target_model="claude-sonnet-4-6",
        target_provider="anthropic-compatible",
        provider_base_url="https://jojocode.com/v1",
        provider_api_key_env="JOJOCODE_CLAUDE_API_KEY",
    )

    assert binding.base_url == "https://jojocode.com/v1"
    assert binding.api_key_env == "JOJOCODE_CLAUDE_API_KEY"

    default_binding = resolve_agent_binding(
        "claude-code",
        target_model="claude-sonnet-4-6",
        target_provider="anthropic-compatible",
        provider_base_url="https://gateway.example",
    )
    assert default_binding.api_key_env == "ANTHROPIC_API_KEY"


def test_claude_environment_uses_only_the_selected_key_and_session_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOJOCODE_KIRO_API_KEY", "kiro-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "inherited-token")
    binding = resolve_agent_binding(
        "claude-code",
        target_model="claude-sonnet-4-6",
        target_provider="anthropic-compatible",
        provider_base_url="https://jojocode.com/v1",
        provider_api_key_env="JOJOCODE_KIRO_API_KEY",
    )

    env = _build_claude_code_environment(binding, {"session_root": str(tmp_path)})

    assert env["ANTHROPIC_API_KEY"] == "kiro-key"
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["ANTHROPIC_BASE_URL"] == "https://jojocode.com"
    assert env["HOME"] == str(tmp_path / "claude-home")
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "claude-home" / ".claude")


def test_pi_and_opencode_extract_native_usage() -> None:
    pi_metrics, pi = _extract_pi_jsonl(
        '\n'.join(
            [
                '{"type":"session","id":"pi-native"}',
                '{"type":"tool_execution_start","toolCallId":"tool-1","toolName":"edit"}',
                '{"type":"tool_execution_end","toolCallId":"tool-1","toolName":"edit"}',
                '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"done"}],"usage":{"input":5,"output":2,"cacheRead":7,"cacheWrite":1,"totalTokens":15,"cost":{"total":0.01}}}}',
            ]
        )
    )
    oc_metrics, oc = _extract_opencode_jsonl(
        '\n'.join(
            [
                '{"type":"tool_use","part":{"callID":"tool-2","tool":"edit"}}',
                '{"type":"text","part":{"text":"done","tokens":{"input":4,"output":3,"total":12,"reasoning":1,"cache":{"read":5,"write":0}}}}',
            ]
        )
    )

    assert pi_metrics["total_tokens"] == 15
    assert pi_metrics["cost_usd"] == 0.01
    assert pi["native_session_id"] == "pi-native"
    assert len(pi["native_tool_events"]) == 2
    assert oc_metrics["total_tokens"] == 12
    assert oc_metrics["cached_input_tokens"] == 5
    assert oc["assistant_text"] == "done"
