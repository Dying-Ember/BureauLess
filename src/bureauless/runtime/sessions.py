from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import shlex
import signal
import shutil
import subprocess
import threading
import time
import tempfile
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from uuid import uuid4

import yaml

from ..agents import resolve_agent_binding, route_agent, session_adapter_for
from ..errors import ProtocolError
from ..protocol.artifacts import sha256_file
from ..protocol.assignments import AssignmentPacket, workflow_version_id
from ..protocol.assignments import render_assignment_prompt
from ..protocol.context import (
    build_context_lifecycle_events,
    build_context_request,
    load_context_request_intent,
    resolve_context_request,
)
from ..protocol.dispatch import (
    DispatchPacket,
    load_dispatch_packet,
    load_turn_report,
    validate_dispatch_packet,
)
from ..protocol.harness import Ledger, Mission, STRICT_ACCEPTANCE_LEDGER_VERSION, Workflow
from ..protocol.ledger import append_ledger_event
from ..protocol.outcomes import (
    build_node_outcome_decision_event,
    node_outcome_from_session,
    reconcile_node_outcome_state,
)
from ..protocol.progress import INDEPENDENT_VERIFICATION_PENDING
from ..protocol.results import ResultProposal, load_result_proposal
from ..protocol.results import import_result_proposal
from ..runtime_workspace import (
    WorkspaceReadiness,
    assess_workspace_isolation,
    git_environment,
    probe_git_worktree,
)
from .provider_usage import (
    ProviderUsageCapture,
    build_provider_usage_capture as _build_provider_usage_capture_from_proxy,
    load_provider_usage_capture,
    merge_provider_usage_into_outcome_metrics as _merge_provider_usage_into_outcome_metrics,
    write_provider_usage_capture_artifact,
)


SUPPORTED_SESSION_AGENTS = {"fake", "shell-dummy"}

RETRY_ATTEMPT_LIMITS = {
    "transient_infrastructure": 3,
    "malformed_output_contract": 2,
    "verification_failure": 2,
    "capability_mismatch": 2,
    "deterministic_failure": 2,
    "workflow_structure": 1,
    "stale_or_superseded": 1,
    "policy_rejection": 1,
}
DEFAULT_RETRY_TOKEN_BUDGET = 20_000

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class _ProcessController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._terminal_status: str | None = None
        self._reason: str | None = None
        self._forced = False

    def attach(self, process: subprocess.Popen[str]) -> None:
        with self._lock:
            self._process = process
            pending = self._terminal_status is not None
        if pending:
            self._terminate(process, grace_seconds=0.0)

    def request(
        self,
        status: str,
        reason: str,
        *,
        grace_seconds: float,
    ) -> bool:
        with self._lock:
            if self._terminal_status is not None:
                return False
            self._terminal_status = status
            self._reason = reason
            process = self._process
        if process is not None:
            self._terminate(process, grace_seconds=grace_seconds)
        return True

    def terminal_intent(self) -> tuple[str, str, bool] | None:
        with self._lock:
            if self._terminal_status is None or self._reason is None:
                return None
            return self._terminal_status, self._reason, self._forced

    def _terminate(
        self,
        process: subprocess.Popen[str],
        *,
        grace_seconds: float,
    ) -> None:
        if process.poll() is not None:
            return
        _signal_process_group(process, force=False)
        deadline = time.monotonic() + max(0.0, grace_seconds)
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if process.poll() is None:
            with self._lock:
                self._forced = True
            _signal_process_group(process, force=True)


@dataclass(frozen=True)
class SessionSpec:
    session_id: str
    assignment_id: str
    agent_id: str
    workdir: str
    timeout_seconds: float
    dry_run: bool
    isolation_mode: str
    cleanup_policy: str
    sandbox_mode: str
    shell_command: str | None = None
    target_model: str | None = None
    target_provider: str | None = None
    provider_base_url: str | None = None
    provider_api_key_env: str | None = None
    provider_wire_api: str | None = None
    reuse_workspace_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "assignment_id": self.assignment_id,
            "agent_id": self.agent_id,
            "workdir": self.workdir,
            "timeout_seconds": self.timeout_seconds,
            "dry_run": self.dry_run,
            "isolation_mode": self.isolation_mode,
            "cleanup_policy": self.cleanup_policy,
            "sandbox_mode": self.sandbox_mode,
            "shell_command": self.shell_command,
            "target_model": self.target_model,
            "target_provider": self.target_provider,
            "provider_base_url": self.provider_base_url,
            "provider_api_key_env": self.provider_api_key_env,
            "provider_wire_api": self.provider_wire_api,
            "reuse_workspace_path": self.reuse_workspace_path,
        }


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    assignment_id: str
    agent_id: str
    status: str
    started_at: str
    finished_at: str
    exit: dict[str, Any]
    native_logs: dict[str, str]
    diff_refs: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    workspace: dict[str, Any]
    outcome_metrics: dict[str, Any]
    extraction: dict[str, Any]
    result_proposal: dict[str, Any] | None
    dispatch: dict[str, Any] | None = None
    audit_evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "assignment_id": self.assignment_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit": self.exit,
            "native_logs": self.native_logs,
            "diff_refs": self.diff_refs,
            "artifacts": self.artifacts,
            "workspace": self.workspace,
            "outcome_metrics": self.outcome_metrics,
            "extraction": self.extraction,
            "result_proposal": self.result_proposal,
            "dispatch": self.dispatch,
            "audit_evidence": self.audit_evidence,
        }


@dataclass(frozen=True)
class RetryControlResult:
    ledger: Ledger
    action: str
    failure_class: str
    failure_fingerprint: str
    event: dict[str, Any]


class _ProviderUsageCollector:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest_capture: dict[str, Any] | None = None

    def record(
        self,
        *,
        provider: str,
        model: str,
        usage: dict[str, Any],
        source_ref: str | None,
    ) -> None:
        payload = {
            "provider": provider,
            "model": model,
            "usage": dict(usage),
            "source_ref": source_ref,
        }
        with self._lock:
            self._latest_capture = payload

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            if self._latest_capture is None:
                return None
            return dict(self._latest_capture)


class _SSEUsageCaptureParser:
    def __init__(self) -> None:
        self._buffer = b""

    def feed(self, chunk: bytes) -> dict[str, Any] | None:
        self._buffer += chunk
        capture = None
        while b"\n\n" in self._buffer:
            raw_event, self._buffer = self._buffer.split(b"\n\n", 1)
            event_capture = self._parse_event(raw_event)
            if event_capture is not None:
                capture = event_capture
        return capture

    def finish(self) -> dict[str, Any] | None:
        if not self._buffer.strip():
            return None
        capture = self._parse_event(self._buffer)
        self._buffer = b""
        return capture

    def _parse_event(self, raw_event: bytes) -> dict[str, Any] | None:
        data_lines: list[str] = []
        for raw_line in raw_event.splitlines():
            line = raw_line.decode("utf-8", errors="ignore")
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if not data_lines:
            return None
        payload_text = "\n".join(data_lines).strip()
        if not payload_text or payload_text == "[DONE]":
            return None
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            return None
        return _extract_openai_compatible_usage_capture(payload)


class _OpenAICompatibleTelemetryProxy:
    def __init__(self, upstream_base_url: str) -> None:
        self._upstream_base_url = upstream_base_url.rstrip("/")
        self._collector = _ProviderUsageCollector()
        server = self._build_server()
        self._server = server
        self.base_url = f"http://127.0.0.1:{server.server_port}"
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()

    def snapshot(self) -> dict[str, Any] | None:
        return self._collector.snapshot()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1.0)

    def _build_server(self) -> ThreadingHTTPServer:
        proxy = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_DELETE(self) -> None:
                self._forward()

            def do_GET(self) -> None:
                self._forward()

            def do_PATCH(self) -> None:
                self._forward()

            def do_POST(self) -> None:
                self._forward()

            def do_PUT(self) -> None:
                self._forward()

            def log_message(self, _format: str, *_args: Any) -> None:
                return

            def _forward(self) -> None:
                body = b""
                content_length = self.headers.get("Content-Length")
                if content_length:
                    body = self.rfile.read(int(content_length))
                target_url = _join_upstream_url(proxy._upstream_base_url, self.path)
                headers = {
                    key: value
                    for key, value in self.headers.items()
                    if key.lower() not in {"host", "content-length", "connection"}
                }
                request = urllib_request.Request(
                    target_url,
                    data=body if self.command in {"POST", "PUT", "PATCH"} else None,
                    headers=headers,
                    method=self.command,
                )
                try:
                    with urllib_request.urlopen(request, timeout=300) as response:
                        self.send_response(response.status)
                        for key, value in response.headers.items():
                            lowered = key.lower()
                            if lowered in {"connection", "content-length", "transfer-encoding"}:
                                continue
                            self.send_header(key, value)
                        self.end_headers()
                        proxy._stream_response(response, self.wfile, response.headers)
                        return
                except urllib_error.HTTPError as exc:
                    self.send_response(exc.code)
                    for key, value in exc.headers.items():
                        lowered = key.lower()
                        if lowered in {"connection", "content-length", "transfer-encoding"}:
                            continue
                        self.send_header(key, value)
                    self.end_headers()
                    proxy._stream_response(exc, self.wfile, exc.headers)
                    return
                except (urllib_error.URLError, http.client.HTTPException, OSError) as exc:
                    reason = exc.reason if isinstance(exc, urllib_error.URLError) else str(exc)
                    self.send_error(502, explain=reason)
                    return

        return ThreadingHTTPServer(("127.0.0.1", 0), _Handler)

    def _record_capture(self, capture: dict[str, Any] | None) -> None:
        if capture is None:
            return
        self._collector.record(
            provider="openai-compatible",
            model=capture["model"],
            usage=capture["usage"],
            source_ref=capture.get("source_ref"),
        )

    def _stream_response(
        self,
        response: Any,
        output: Any,
        response_headers: Any,
    ) -> None:
        content_type = response_headers.get("Content-Type", "")
        is_sse = "text/event-stream" in content_type.lower()
        sse_parser = _SSEUsageCaptureParser() if is_sse else None
        json_chunks: list[bytes] | None = [] if not is_sse else None
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            if sse_parser is not None:
                self._record_capture(sse_parser.feed(chunk))
            elif json_chunks is not None:
                json_chunks.append(chunk)
            output.write(chunk)
            output.flush()
        if sse_parser is not None:
            self._record_capture(sse_parser.finish())
            return
        if json_chunks is None:
            return
        try:
            payload = json.loads(b"".join(json_chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        self._record_capture(_extract_openai_compatible_usage_capture(payload))


def classify_session_failure(
    record: SessionRecord,
    *,
    error_code: str | None = None,
) -> str:
    normalized = (error_code or str(record.exit.get("reason", ""))).lower()
    if record.status == "superseded" or "stale" in normalized or "supersed" in normalized:
        return "stale_or_superseded"
    if normalized.startswith(("policy_", "safety_", "permission_")):
        return "policy_rejection"
    if normalized.startswith(("capability_", "model_", "provider_")):
        return "capability_mismatch"
    result = record.result_proposal if isinstance(record.result_proposal, dict) else {}
    verification = result.get("verification")
    verification_status = (
        verification.get("status") if isinstance(verification, dict) else None
    )
    if verification_status == "workflow_structure" or result.get("control_intents"):
        return "workflow_structure"
    extraction_status = record.extraction.get("status")
    if record.status == "completed" and not result:
        return "malformed_output_contract"
    if extraction_status in {"wrapper_failed_to_extract", "agent_output_unstructured"}:
        return "malformed_output_contract"
    if verification_status in {"failed", "error", "rejected"}:
        return "verification_failure"
    if record.status == "timed_out" or any(
        marker in normalized
        for marker in ("network", "rate_limit", "launch_failed", "temporar", "timeout")
    ):
        return "transient_infrastructure"
    return "deterministic_failure"


def apply_retry_policy(
    workflow: Workflow,
    ledger: Ledger,
    assignment: AssignmentPacket,
    record: SessionRecord,
    *,
    error_code: str | None = None,
    changed_evidence_refs: list[str] | None = None,
    repair_strategy: str | None = None,
    routing_decision_id: str | None = None,
    strategy_id: str | None = None,
    token_budget: int = DEFAULT_RETRY_TOKEN_BUDGET,
) -> RetryControlResult:
    if record.assignment_id != assignment.assignment_id:
        raise ProtocolError("Retry record assignment_id does not match assignment")
    if token_budget <= 0 or token_budget > DEFAULT_RETRY_TOKEN_BUDGET:
        raise ProtocolError("Retry token budget must be between 1 and 20000")

    failure_class = classify_session_failure(record, error_code=error_code)
    root_assignment_id = _retry_root_assignment_id(ledger, assignment.assignment_id)
    related_attempt_ids = {root_assignment_id}
    related_attempt_ids.update(
        event["assignment_id"]
        for event in ledger.event_log
        if event.get("event_type") == "assignment_retry_scheduled"
        and event.get("root_assignment_id") == root_assignment_id
        and isinstance(event.get("assignment_id"), str)
    )
    scheduled = [
        event
        for event in ledger.event_log
        if event.get("event_type") == "assignment_retry_scheduled"
        and event.get("root_assignment_id") == root_assignment_id
    ]
    total_attempts = 1 + len(scheduled)
    used_tokens = _retry_tokens_used(ledger, related_attempt_ids)
    used_tokens = max(
        [
            used_tokens,
            *[
                _int_value(event.get("budget_snapshot", {}).get("tokens_used"))
                for event in scheduled
                if isinstance(event.get("budget_snapshot"), dict)
            ],
        ]
    )
    if not any(
        event.get("event_type") == "result_submitted"
        and event.get("assignment_id") == record.assignment_id
        for event in ledger.event_log
    ):
        used_tokens += _int_value(record.outcome_metrics.get("total_tokens"))

    changed_evidence_refs = changed_evidence_refs or []
    effective_strategy = strategy_id or repair_strategy or "unchanged"
    fingerprint_payload = {
        "root_assignment_id": root_assignment_id,
        "workflow_version_id": assignment.visible_context.get("workflow_version_id")
        or workflow_version_id(workflow, ledger),
        "failure_class": failure_class,
        "error_code": error_code or record.exit.get("reason") or record.status,
        "evidence": _failure_evidence(record),
        "agent_id": record.agent_id,
        "model": _result_field(record, "effective_model"),
        "provider": _result_field(record, "effective_provider"),
        "strategy_id": effective_strategy,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    budget_snapshot = {
        "policy_version": "retry-v1",
        "attempts_used": total_attempts,
        "attempts_allowed": RETRY_ATTEMPT_LIMITS[failure_class],
        "tokens_used": used_tokens,
        "token_budget": token_budget,
    }

    terminal_state = None
    stop_reason = None
    if failure_class in {"workflow_structure", "stale_or_superseded"}:
        terminal_state = "needs_replan"
        stop_reason = "failure_class_not_retryable"
    elif failure_class == "policy_rejection":
        terminal_state = "needs_review"
        stop_reason = "failure_class_not_retryable"
    elif failure_class == "verification_failure" and not (
        changed_evidence_refs and repair_strategy
    ):
        terminal_state = "needs_review"
        stop_reason = "repair_evidence_or_strategy_missing"
    elif failure_class == "capability_mismatch" and not (
        routing_decision_id and effective_strategy != "unchanged"
    ):
        terminal_state = "needs_review"
        stop_reason = "routing_or_strategy_change_missing"
    elif failure_class == "deterministic_failure" and not (
        changed_evidence_refs or effective_strategy != "unchanged"
    ):
        terminal_state = "needs_review"
        stop_reason = "changed_input_or_strategy_missing"
    elif failure_class != "transient_infrastructure" and any(
        event.get("failure_fingerprint") == fingerprint for event in scheduled
    ):
        terminal_state = "needs_review"
        stop_reason = "repeated_deterministic_fingerprint"
    elif total_attempts >= RETRY_ATTEMPT_LIMITS[failure_class]:
        terminal_state = "needs_review"
        stop_reason = "attempt_budget_exhausted"
    elif used_tokens >= token_budget:
        terminal_state = "needs_review"
        stop_reason = "token_budget_exhausted"

    common = {
        "mission_id": workflow.mission_id,
        "workflow_id": workflow.workflow_id,
        "node_id": assignment.node_id,
        "role": assignment.role,
        "root_assignment_id": root_assignment_id,
        "prior_attempt_id": assignment.assignment_id,
        "failure_class": failure_class,
        "failure_fingerprint": fingerprint,
        "error_code": error_code or record.exit.get("reason") or record.status,
        "changed_evidence_refs": changed_evidence_refs,
        "strategy_id": effective_strategy,
        "routing_decision_id": routing_decision_id,
        "budget_snapshot": budget_snapshot,
        "created_at": _now(),
    }
    if terminal_state is not None:
        event = {
            **common,
            "event_id": f"event-circuit-{root_assignment_id}-{fingerprint[:12]}",
            "event_type": "assignment_circuit_opened",
            "assignment_id": assignment.assignment_id,
            "terminal_state": terminal_state,
            "reason": stop_reason,
        }
        existing = next(
            (item for item in ledger.event_log if item.get("event_id") == event["event_id"]),
            None,
        )
        if existing is not None:
            return RetryControlResult(
                ledger, "circuit_opened", failure_class, fingerprint, existing
            )
        updated = append_ledger_event(ledger, event, workflow)
        return RetryControlResult(
            updated, "circuit_opened", failure_class, fingerprint, event
        )

    attempt_id = f"{root_assignment_id}:attempt-{total_attempts + 1:03d}"
    event = {
        **common,
        "event_id": f"event-retry-{attempt_id}",
        "event_type": "assignment_retry_scheduled",
        "assignment_id": attempt_id,
        "attempt_id": attempt_id,
        "retry_of": assignment.assignment_id,
        "retry_reason": failure_class,
    }
    updated = append_ledger_event(ledger, event, workflow)
    return RetryControlResult(updated, "retry_scheduled", failure_class, fingerprint, event)


def _retry_root_assignment_id(ledger: Ledger, assignment_id: str) -> str:
    event = next(
        (
            item
            for item in ledger.event_log
            if item.get("event_type") == "assignment_retry_scheduled"
            and item.get("assignment_id") == assignment_id
        ),
        None,
    )
    root = event.get("root_assignment_id") if event is not None else None
    return root if isinstance(root, str) and root else assignment_id


def _retry_tokens_used(ledger: Ledger, assignment_ids: set[str]) -> int:
    return sum(
        _int_value(result.get("outcome_metrics", {}).get("total_tokens"))
        for event in ledger.event_log
        if event.get("event_type") == "result_submitted"
        and event.get("assignment_id") in assignment_ids
        and isinstance((result := event.get("result")), dict)
        and isinstance(result.get("outcome_metrics"), dict)
    )


def _failure_evidence(record: SessionRecord) -> dict[str, Any]:
    result = record.result_proposal if isinstance(record.result_proposal, dict) else {}
    return {
        "verification": result.get("verification"),
        "warnings": record.extraction.get("warnings", []),
        "exit_reason": record.exit.get("reason"),
    }


def _result_field(record: SessionRecord, field: str) -> Any:
    if not isinstance(record.result_proposal, dict):
        return None
    return record.result_proposal.get(field)


class LiveSessionHandle:
    def __init__(
        self,
        session_id: str,
        target: Callable[[_ProcessController], SessionRecord],
    ) -> None:
        self.session_id = session_id
        self._target = target
        self._controller = _ProcessController()
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._record: SessionRecord | None = None
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"bureauless-{session_id}",
            daemon=True,
        )

    def start(self) -> "LiveSessionHandle":
        self._thread.start()
        return self

    def cancel(
        self,
        reason: str = "cancelled",
        *,
        grace_seconds: float = 1.0,
    ) -> bool:
        return self._request_terminal(
            "cancelled",
            reason,
            grace_seconds=grace_seconds,
        )

    def supersede(
        self,
        reason: str = "superseded",
        *,
        grace_seconds: float = 1.0,
    ) -> bool:
        return self._request_terminal(
            "superseded",
            reason,
            grace_seconds=grace_seconds,
        )

    def wait(self, timeout: float | None = None) -> SessionRecord:
        if not self._done.wait(timeout):
            raise TimeoutError(f"Session {self.session_id} is still running")
        if self._error is not None:
            raise self._error
        if self._record is None:
            raise ProtocolError(f"Session {self.session_id} finished without a record")
        return self._record

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def _request_terminal(
        self,
        status: str,
        reason: str,
        *,
        grace_seconds: float,
    ) -> bool:
        with self._lock:
            if self._done.is_set():
                return False
        return self._controller.request(
            status,
            reason,
            grace_seconds=grace_seconds,
        )

    def _run(self) -> None:
        try:
            record = self._target(self._controller)
            terminal_intent = self._controller.terminal_intent()
            if terminal_intent is not None:
                status, reason, forced = terminal_intent
                record = _terminalize_live_record(
                    record,
                    status=status,
                    reason=reason,
                    forced=forced,
                )
            with self._lock:
                self._record = record
        except BaseException as exc:
            with self._lock:
                self._error = exc
        finally:
            self._done.set()


def create_session_spec(
    assignment: AssignmentPacket,
    agent_id: str,
    workdir: Path,
    timeout_seconds: float = 30.0,
    dry_run: bool = False,
    isolation_mode: str = "copy",
    cleanup_policy: str = "retain_session_root",
    sandbox_mode: str = "workspace-write",
    shell_command: str | None = None,
    target_model: str | None = None,
    target_provider: str | None = None,
    provider_base_url: str | None = None,
    provider_api_key_env: str | None = None,
    provider_wire_api: str | None = None,
    session_id: str | None = None,
    reuse_workspace_path: str | None = None,
) -> SessionSpec:
    adapter = None if agent_id in SUPPORTED_SESSION_AGENTS else session_adapter_for(agent_id)
    if isolation_mode not in {"copy", "worktree"}:
        raise ProtocolError(f"Unsupported isolation_mode: {isolation_mode}")
    if sandbox_mode not in {"read-only", "workspace-write", "danger-full-access"}:
        raise ProtocolError(f"Unsupported sandbox_mode: {sandbox_mode}")
    if agent_id == "shell-dummy" and not dry_run and not shell_command:
        raise ProtocolError("shell-dummy session requires --shell-command")
    if adapter in {
        "codex_exec_v1",
        "claude_stream_json_v1",
        "gemini_stream_json_v1",
        "opencode_run_json_v1",
        "pi_json_v1",
    }:
        if target_model is None or target_provider is None:
            raise ProtocolError(f"{agent_id} session requires target_model and target_provider")
        resolve_agent_binding(
            agent_id,
            target_model=target_model,
            target_provider=target_provider,
            provider_base_url=provider_base_url,
            provider_api_key_env=provider_api_key_env,
            provider_wire_api=provider_wire_api,
        )
    return SessionSpec(
        session_id=session_id or f"session-{uuid4()}",
        assignment_id=assignment.assignment_id,
        agent_id=agent_id,
        workdir=str(workdir),
        timeout_seconds=timeout_seconds,
        dry_run=dry_run,
        isolation_mode=isolation_mode,
        cleanup_policy=cleanup_policy,
        sandbox_mode=sandbox_mode,
        shell_command=shell_command,
        target_model=target_model,
        target_provider=target_provider,
        provider_base_url=provider_base_url,
        provider_api_key_env=provider_api_key_env,
        provider_wire_api=provider_wire_api,
        reuse_workspace_path=reuse_workspace_path,
    )


def start_dispatch_session(
    mission: Mission,
    workflow: Workflow,
    packet: DispatchPacket,
    *,
    agent_id: str,
    workdir: Path,
    dispatch_packet_path: Path,
    timeout_seconds: float = 30.0,
    dry_run: bool = False,
    isolation_mode: str = "copy",
    cleanup_policy: str = "retain_session_root",
    sandbox_mode: str = "workspace-write",
    shell_command: str | None = None,
    target_model: str | None = None,
    target_provider: str | None = None,
    provider_base_url: str | None = None,
    provider_api_key_env: str | None = None,
    provider_wire_api: str | None = None,
    session_id: str | None = None,
    command_runner: CommandRunner | None = None,
    context_ledger: Ledger | None = None,
    max_added_context_tokens: int = 2000,
) -> LiveSessionHandle:
    """Validate and persist one dispatch, then return its live session handle."""
    validate_dispatch_packet(mission, workflow, packet)
    if (
        target_model is not None
        and mission.models
        and not _mission_allows_target_model(mission.models, target_model)
    ):
        raise ProtocolError(
            f"Dispatch target_model {target_model!r} is not allowed by mission"
        )

    spec = create_session_spec(
        assignment=packet.assignment,
        agent_id=agent_id,
        workdir=workdir,
        timeout_seconds=timeout_seconds,
        dry_run=dry_run,
        isolation_mode=isolation_mode,
        cleanup_policy=cleanup_policy,
        sandbox_mode=sandbox_mode,
        shell_command=shell_command,
        target_model=target_model,
        target_provider=target_provider,
        provider_base_url=provider_base_url,
        provider_api_key_env=provider_api_key_env,
        provider_wire_api=provider_wire_api,
        session_id=session_id,
    )
    _validate_dispatch_binding(packet, spec)
    _write_dispatch_packet(dispatch_packet_path, packet)
    packet_path = dispatch_packet_path.resolve()
    packet_sha256 = sha256_file(packet_path)

    dispatch_evidence = {
        "packet_id": packet.packet_id,
        "packet_path": str(packet_path),
        "packet_sha256": packet_sha256,
        "mission_id": packet.mission_id,
        "workflow_id": packet.workflow_id,
        "assignment_id": packet.assignment.assignment_id,
        "session_spec": spec.to_dict(),
        "review_constraints": packet.review_constraints,
        "turn_report_policy": packet.turn_report_policy,
    }

    def run(controller: _ProcessController) -> SessionRecord:
        if context_ledger is not None:
            record = run_session_with_context_continuation(
                spec,
                packet.assignment,
                workflow,
                context_ledger,
                command_runner=command_runner,
                dispatch_packet=packet,
                process_controller=controller,
                max_added_context_tokens=max_added_context_tokens,
            )
        else:
            record = run_session(
                spec,
                packet.assignment,
                command_runner=command_runner,
                dispatch_packet=packet,
                process_controller=controller,
            )
        record = _attach_dispatch_turn_report(record, packet)
        record = replace(
            record,
            audit_evidence=_session_audit_evidence(record, spec, packet),
        )
        return replace(
            record,
            dispatch=dispatch_evidence,
        )

    return LiveSessionHandle(spec.session_id, run).start()


def _mission_allows_target_model(models: dict[str, Any], target_model: str) -> bool:
    normalized_target = target_model.strip().lower()
    if not normalized_target:
        return False
    normalized_allowed = {str(name).strip().lower() for name in models}
    if normalized_target in normalized_allowed:
        return True
    return any(_model_family_matches(allowed, normalized_target) for allowed in normalized_allowed)


def _model_family_matches(allowed: str, target: str) -> bool:
    if allowed == "gpt-5":
        return target.startswith("gpt-5") and "-mini" not in target
    if allowed == "gpt-5-mini":
        return target.startswith("gpt-5") and "-mini" in target
    return False


def dispatch_session(
    mission: Mission,
    workflow: Workflow,
    packet: DispatchPacket,
    *,
    agent_id: str,
    workdir: Path,
    dispatch_packet_path: Path,
    timeout_seconds: float = 30.0,
    dry_run: bool = False,
    isolation_mode: str = "copy",
    cleanup_policy: str = "retain_session_root",
    sandbox_mode: str = "workspace-write",
    shell_command: str | None = None,
    target_model: str | None = None,
    target_provider: str | None = None,
    provider_base_url: str | None = None,
    provider_api_key_env: str | None = None,
    provider_wire_api: str | None = None,
    session_id: str | None = None,
    command_runner: CommandRunner | None = None,
    context_ledger: Ledger | None = None,
    max_added_context_tokens: int = 2000,
) -> SessionRecord:
    return start_dispatch_session(
        mission,
        workflow,
        packet,
        agent_id=agent_id,
        workdir=workdir,
        dispatch_packet_path=dispatch_packet_path,
        timeout_seconds=timeout_seconds,
        dry_run=dry_run,
        isolation_mode=isolation_mode,
        cleanup_policy=cleanup_policy,
        sandbox_mode=sandbox_mode,
        shell_command=shell_command,
        target_model=target_model,
        target_provider=target_provider,
        provider_base_url=provider_base_url,
        provider_api_key_env=provider_api_key_env,
        provider_wire_api=provider_wire_api,
        session_id=session_id,
        command_runner=command_runner,
        context_ledger=context_ledger,
        max_added_context_tokens=max_added_context_tokens,
    ).wait()


def reconstruct_dispatched_session(
    record: SessionRecord,
) -> tuple[DispatchPacket, SessionSpec]:
    """Reconstruct and verify the exact packet and binding used for a session."""
    evidence = record.dispatch
    if not isinstance(evidence, dict):
        raise ProtocolError("Session record is missing dispatch evidence")
    packet_path = Path(_as_string(evidence, "packet_path"))
    expected_sha256 = _as_string(evidence, "packet_sha256")
    if not packet_path.is_file():
        raise ProtocolError("Session dispatch packet artifact does not exist")
    if sha256_file(packet_path) != expected_sha256:
        raise ProtocolError("Session dispatch packet artifact hash does not match evidence")
    with packet_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ProtocolError("Session dispatch packet artifact must contain an object")
    packet = load_dispatch_packet(payload)
    spec = _load_session_spec(_as_mapping(evidence, "session_spec"))
    _validate_dispatch_binding(packet, spec)
    canonical_spec = create_session_spec(
        packet.assignment,
        spec.agent_id,
        Path(spec.workdir),
        timeout_seconds=spec.timeout_seconds,
        dry_run=spec.dry_run,
        isolation_mode=spec.isolation_mode,
        cleanup_policy=spec.cleanup_policy,
        sandbox_mode=spec.sandbox_mode,
        shell_command=spec.shell_command,
        target_model=spec.target_model,
        target_provider=spec.target_provider,
        provider_base_url=spec.provider_base_url,
        provider_api_key_env=spec.provider_api_key_env,
        provider_wire_api=spec.provider_wire_api,
        session_id=spec.session_id,
        reuse_workspace_path=spec.reuse_workspace_path,
    )
    if canonical_spec != spec:
        raise ProtocolError("Session dispatch binding is not in canonical form")
    if packet.packet_id != _as_string(evidence, "packet_id"):
        raise ProtocolError("Session dispatch packet_id does not match evidence")
    for field, expected in (
        ("mission_id", packet.mission_id),
        ("workflow_id", packet.workflow_id),
        ("assignment_id", packet.assignment.assignment_id),
    ):
        if _as_string(evidence, field) != expected:
            raise ProtocolError(f"Session dispatch {field} does not match packet")
    if _as_mapping(evidence, "review_constraints") != packet.review_constraints:
        raise ProtocolError("Session dispatch review_constraints do not match packet")
    if _as_mapping(evidence, "turn_report_policy") != packet.turn_report_policy:
        raise ProtocolError("Session dispatch turn_report_policy does not match packet")
    if record.session_id != spec.session_id:
        raise ProtocolError("Session record session_id does not match dispatch binding")
    if record.assignment_id != spec.assignment_id:
        raise ProtocolError("Session record assignment_id does not match dispatch binding")
    if record.agent_id != spec.agent_id:
        raise ProtocolError("Session record agent_id does not match dispatch binding")
    return packet, spec


def run_session(
    spec: SessionSpec,
    assignment: AssignmentPacket,
    *,
    command_runner: CommandRunner | None = None,
    dispatch_packet: DispatchPacket | None = None,
    process_controller: _ProcessController | None = None,
    context_resolution: dict[str, Any] | None = None,
) -> SessionRecord:
    if assignment.assignment_id != spec.assignment_id:
        raise ProtocolError("Session assignment_id does not match assignment packet")
    if dispatch_packet is not None:
        if dispatch_packet.assignment.to_dict() != assignment.to_dict():
            raise ProtocolError("Launched assignment does not match dispatch packet")
        _validate_dispatch_binding(dispatch_packet, spec)

    started_at = _now()
    started_monotonic = time.monotonic()

    if spec.dry_run:
        base_metrics = _base_outcome_metrics(wall_time_ms=0)
        base_metrics["cost_source"] = "unavailable"
        return SessionRecord(
            session_id=spec.session_id,
            assignment_id=spec.assignment_id,
            agent_id=spec.agent_id,
            status="dry_run",
            started_at=started_at,
            finished_at=started_at,
            exit={"code": 0, "reason": "dry_run"},
            native_logs={"stdout": "", "stderr": ""},
            diff_refs=[],
            artifacts=[],
            workspace=_unprepared_workspace_record(spec),
            outcome_metrics=base_metrics,
            extraction={
                "contract": "none",
                "status": "dry_run",
                "warnings": [],
                "parsed_fields": [],
                "missing_fields": [],
            },
            result_proposal=None,
        )

    if spec.agent_id == "fake":
        wall_time_ms = max(1, int((time.monotonic() - started_monotonic) * 1000))
        outcome_metrics = _base_outcome_metrics(wall_time_ms=wall_time_ms)
        outcome_metrics["patch_bytes"] = 0
        result = ResultProposal(
            result_id=f"result-{spec.session_id}",
            assignment_id=assignment.assignment_id,
            agent_id=spec.agent_id,
            status="completed",
            effective_model="fake",
            effective_provider="fixture",
            emitted_events=assignment.expected_events,
            artifacts=[],
            outcome_metrics=outcome_metrics,
            verification={"status": "not_run"},
            native_log_refs=[],
            mutation_proposal_refs=[],
            review_status=None,
        )
        finished_at = _now()
        return SessionRecord(
            session_id=spec.session_id,
            assignment_id=spec.assignment_id,
            agent_id=spec.agent_id,
            status="completed",
            started_at=started_at,
            finished_at=finished_at,
            exit={"code": 0, "reason": "completed"},
            native_logs={"stdout": "fake session completed", "stderr": ""},
            diff_refs=[],
            artifacts=[],
            workspace=_unprepared_workspace_record(spec),
            outcome_metrics=result.outcome_metrics,
            extraction={
                "contract": "fake_session_v1",
                "status": "synthetic",
                "warnings": [
                    "fake agent does not emit native token or cost usage",
                ],
                "parsed_fields": [
                    "effective_model",
                    "effective_provider",
                    "emitted_events",
                    "verification.status",
                ],
                "missing_fields": [
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "cost_usd",
                ],
            },
            result_proposal=result.to_dict(),
        )

    adapter = None if spec.agent_id in SUPPORTED_SESSION_AGENTS else session_adapter_for(spec.agent_id)
    if adapter == "codex_exec_v1":
        return _run_codex_cli_session(
            spec,
            assignment,
            started_at,
            started_monotonic,
            command_runner=command_runner,
            dispatch_packet=dispatch_packet,
            process_controller=process_controller,
            context_resolution=context_resolution,
        )

    if adapter == "claude_stream_json_v1":
        return _run_claude_code_session(
            spec,
            assignment,
            started_at,
            started_monotonic,
            command_runner=command_runner,
            dispatch_packet=dispatch_packet,
            process_controller=process_controller,
            context_resolution=context_resolution,
        )

    if adapter == "gemini_stream_json_v1":
        return _run_gemini_cli_session(
            spec,
            assignment,
            started_at,
            started_monotonic,
            command_runner=command_runner,
            dispatch_packet=dispatch_packet,
            process_controller=process_controller,
            context_resolution=context_resolution,
        )

    if adapter == "opencode_run_json_v1":
        return _run_opencode_session(
            spec,
            assignment,
            started_at,
            started_monotonic,
            command_runner=command_runner,
            dispatch_packet=dispatch_packet,
            process_controller=process_controller,
            context_resolution=context_resolution,
        )

    if adapter == "pi_json_v1":
        return _run_pi_session(
            spec,
            assignment,
            started_at,
            started_monotonic,
            command_runner=command_runner,
            dispatch_packet=dispatch_packet,
            process_controller=process_controller,
            context_resolution=context_resolution,
        )

    return _run_shell_dummy_session(
        spec,
        assignment,
        started_at,
        started_monotonic,
        process_controller=process_controller,
    )


def run_session_with_context_continuation(
    spec: SessionSpec,
    assignment: AssignmentPacket,
    workflow: Workflow,
    ledger: Ledger,
    *,
    command_runner: CommandRunner | None = None,
    dispatch_packet: DispatchPacket | None = None,
    process_controller: _ProcessController | None = None,
    max_context_requests: int = 1,
    max_context_artifacts: int = 1,
    max_added_context_tokens: int = 2000,
    context_request_ttl_seconds: int = 300,
    clock: Callable[[], datetime] | None = None,
) -> SessionRecord:
    if max_context_requests != 1:
        raise ProtocolError("The maintained continuation policy requires exactly one request")
    current_time = clock or (lambda: datetime.now(timezone.utc))
    first = run_session(
        spec,
        assignment,
        command_runner=command_runner,
        dispatch_packet=dispatch_packet,
        process_controller=process_controller,
    )
    intent_payload = first.extraction.get("context_request")
    if not isinstance(intent_payload, dict):
        return first
    if first.extraction.get("result_status") != "context_requested":
        raise ProtocolError("Context request requires result status context_requested")

    intent = load_context_request_intent(intent_payload)
    continuation_id = f"continuation-{spec.session_id}"
    request = build_context_request(
        intent,
        assignment_id=assignment.assignment_id,
        session_id=spec.session_id,
        continuation_id=continuation_id,
        request_index=1,
        now=current_time(),
        ttl_seconds=context_request_ttl_seconds,
    )
    resolution = resolve_context_request(
        assignment,
        ledger,
        request,
        max_artifacts=max_context_artifacts,
        max_added_tokens=max_added_context_tokens,
        now=current_time(),
    )
    resumed = resolution.status in {"granted", "partially_granted"}
    lifecycle_events = build_context_lifecycle_events(
        request,
        resolution,
        mission_id=workflow.mission_id,
        workflow_id=workflow.workflow_id,
        node_id=assignment.node_id,
        role=assignment.role,
        resumed=resumed,
    )
    context_entry = {
        "continuation_id": continuation_id,
        "context_request_id": request.context_request_id,
        "status": resolution.status,
        "requested_refs": request.requested_refs,
        "added_tokens_estimate": resolution.added_tokens_estimate,
        "request": request.to_dict(),
        "resolution": resolution.to_dict(),
        "resumed": resumed,
    }
    if not resumed:
        return _context_terminal_record(
            first,
            context_entry=context_entry,
            lifecycle_events=lifecycle_events,
            reason=f"context_{resolution.status}",
        )

    resumed_spec = replace(
        spec,
        workdir=first.workspace["path"],
        reuse_workspace_path=first.workspace["path"],
    )
    final = run_session(
        resumed_spec,
        assignment,
        command_runner=command_runner,
        dispatch_packet=dispatch_packet,
        process_controller=process_controller,
        context_resolution=resolution.to_dict(),
    )
    if isinstance(final.extraction.get("context_request"), dict):
        return _context_terminal_record(
            final,
            context_entry=context_entry,
            lifecycle_events=lifecycle_events,
            reason="context_request_limit_exhausted",
        )
    return _merge_context_continuation_records(
        first,
        final,
        context_entry=context_entry,
        lifecycle_events=lifecycle_events,
        added_tokens=resolution.added_tokens_estimate,
    )


def cancel_session_record(record: SessionRecord, reason: str = "cancelled") -> SessionRecord:
    finished_at = _now()
    return replace(
        record,
        status="cancelled",
        finished_at=finished_at,
        exit={"code": None, "reason": reason},
        result_proposal=None,
    )


def supersede_session_record(
    record: SessionRecord,
    reason: str = "superseded",
) -> SessionRecord:
    finished_at = _now()
    return replace(
        record,
        status="superseded",
        finished_at=finished_at,
        exit={"code": None, "reason": reason},
        result_proposal=None,
    )


def build_assignment_created_event(
    workflow: Workflow,
    assignment: AssignmentPacket,
    session_id: str,
    agent_id: str,
    event_id: str | None = None,
) -> dict[str, Any]:
    event = {
        "event_id": event_id or f"event-{assignment.assignment_id}-created",
        "event_type": "assignment_created",
        "mission_id": workflow.mission_id,
        "workflow_id": workflow.workflow_id,
        "assignment_id": assignment.assignment_id,
        "node_id": assignment.node_id,
        "role": assignment.role,
        "agent_id": agent_id,
        "session_id": session_id,
        "created_at": _now(),
    }
    version = assignment.visible_context.get("workflow_version_id")
    if isinstance(version, str) and version:
        event["workflow_version_id"] = version
    return event


def build_session_terminal_event(
    workflow: Workflow,
    assignment: AssignmentPacket,
    record: SessionRecord,
    event_id: str | None = None,
    superseded_by: str | None = None,
) -> dict[str, Any] | None:
    event_type = _terminal_event_type(record.status)
    if event_type is None:
        return None

    payload = {
        "event_id": event_id or f"event-{assignment.assignment_id}-{event_type}",
        "event_type": event_type,
        "mission_id": workflow.mission_id,
        "workflow_id": workflow.workflow_id,
        "assignment_id": assignment.assignment_id,
        "node_id": assignment.node_id,
        "role": assignment.role,
        "agent_id": record.agent_id,
        "session_id": record.session_id,
        "created_at": record.finished_at,
        "reason": record.exit.get("reason"),
        "exit": record.exit,
    }
    if superseded_by is not None:
        payload["superseded_by"] = superseded_by
    return payload


def load_session_record(data: dict[str, Any]) -> SessionRecord:
    return SessionRecord(
        session_id=_as_string(data, "session_id"),
        assignment_id=_as_string(data, "assignment_id"),
        agent_id=_as_string(data, "agent_id"),
        status=_as_string(data, "status"),
        started_at=_as_string(data, "started_at"),
        finished_at=_as_string(data, "finished_at"),
        exit=_as_mapping(data, "exit"),
        native_logs=_as_mapping(data, "native_logs"),
        diff_refs=_as_mapping_list(data, "diff_refs", default=[]),
        artifacts=_as_mapping_list(data, "artifacts", default=[]),
        workspace=_as_mapping(data, "workspace", default={}),
        outcome_metrics=_as_mapping(data, "outcome_metrics", default={}),
        extraction=_as_mapping(data, "extraction", default={}),
        result_proposal=data.get("result_proposal"),
        dispatch=data.get("dispatch") if isinstance(data.get("dispatch"), dict) else None,
        audit_evidence=_load_audit_evidence(data.get("audit_evidence")),
    )


def _load_audit_evidence(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProtocolError("Session audit_evidence must be an object")
    decision_points = value.get("decision_points", [])
    side_effects = value.get("side_effects", [])
    capability_contributions = value.get("capability_contributions", [])
    independent_verification = value.get("independent_verification")
    benchmark_identity = value.get("benchmark_identity")
    side_effect_coverage = value.get("side_effect_coverage")
    for name, records in (
        ("decision_points", decision_points),
        ("side_effects", side_effects),
        ("capability_contributions", capability_contributions),
    ):
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise ProtocolError(f"Session audit_evidence.{name} must be a list of objects")

    for point in decision_points:
        if not isinstance(point.get("evidence_available_at_time"), list):
            raise ProtocolError("Decision point evidence_available_at_time must be a list")
        if not _string_or_none(point.get("action_selected")):
            raise ProtocolError("Decision point action_selected must be a non-empty string")
        alternatives = point.get("alternatives_visible")
        if not isinstance(alternatives, list) or not all(
            isinstance(item, str) and item for item in alternatives
        ):
            raise ProtocolError("Decision point alternatives_visible must be a list of strings")
        if point.get("later_outcome") is not None and not isinstance(
            point.get("later_outcome"), dict
        ):
            raise ProtocolError("Decision point later_outcome must be an object or null")
        candidate_set = point.get("candidate_set")
        if candidate_set is not None:
            if not isinstance(candidate_set, list) or not candidate_set:
                raise ProtocolError("Decision point candidate_set must be a non-empty list")
            for candidate in candidate_set:
                if not isinstance(candidate, dict):
                    raise ProtocolError("Decision point candidate_set entries must be objects")
                if not _string_or_none(candidate.get("action")):
                    raise ProtocolError("Decision point candidate action must be non-empty")
                if candidate.get("disposition") not in ("selected", "rejected"):
                    raise ProtocolError("Decision point candidate disposition is invalid")
                if not _string_or_none(candidate.get("reason")):
                    raise ProtocolError("Decision point candidate reason must be non-empty")

    for effect in side_effects:
        if effect.get("type") not in ("workspace", "process", "network", "credential", "payment"):
            raise ProtocolError("Side effect type is invalid")
        if effect.get("source") not in ("harness", "agent", "provider"):
            raise ProtocolError("Side effect source is invalid")
        verified = effect.get("verified")
        if not isinstance(verified, bool) and verified != "unknown":
            raise ProtocolError("Side effect verified must be true, false, or unknown")

    for contribution in capability_contributions:
        if not _string_or_none(contribution.get("capability_id")):
            raise ProtocolError("Capability contribution capability_id must be a non-empty string")
        if not isinstance(contribution.get("invoked"), bool):
            raise ProtocolError("Capability contribution invoked must be boolean")
        result_used = contribution.get("result_used")
        if not isinstance(result_used, bool) and result_used != "unknown":
            raise ProtocolError("Capability contribution result_used must be true, false, or unknown")
        if contribution.get("measurable_delta") is not None and not isinstance(
            contribution.get("measurable_delta"), dict
        ):
            raise ProtocolError("Capability contribution measurable_delta must be an object or null")

    if independent_verification is not None:
        if not isinstance(independent_verification, dict):
            raise ProtocolError("Session audit_evidence.independent_verification must be an object")
        if independent_verification.get("status") not in (
            "passed",
            "failed",
            "timed_out",
            "error",
            "not_run",
        ):
            raise ProtocolError("Independent verification status is invalid")
        if independent_verification.get("source") != "harness":
            raise ProtocolError("Independent verification source must be harness")

    if benchmark_identity is not None:
        if not isinstance(benchmark_identity, dict):
            raise ProtocolError("Session audit_evidence.benchmark_identity must be an object")
        benchmark_schema = benchmark_identity.get("schema")
        if benchmark_schema not in {
            "bureauless_benchmark_identity_v1",
            "bureauless_benchmark_identity_v2",
        }:
            raise ProtocolError("Benchmark identity schema is invalid")
        for key in ("cohort_id", "trial_id"):
            if not _string_or_none(benchmark_identity.get(key)):
                raise ProtocolError(f"Benchmark identity {key} must be a non-empty string")
        if not isinstance(benchmark_identity.get("cohort_declared"), bool):
            raise ProtocolError("Benchmark identity cohort_declared must be boolean")
        task_key = (
            "task_contract_sha256"
            if benchmark_schema == "bureauless_benchmark_identity_v2"
            else "task_sha256"
        )
        task_sha = benchmark_identity.get(task_key)
        if not isinstance(task_sha, str) or not task_sha:
            raise ProtocolError(f"Benchmark identity {task_key} must be a non-empty string")
        if benchmark_schema == "bureauless_benchmark_identity_v2":
            for key in ("context_contract_sha256", "execution_contract_sha256"):
                if not _string_or_none(benchmark_identity.get(key)):
                    raise ProtocolError(f"Benchmark identity {key} must be a non-empty string")
            if not isinstance(benchmark_identity.get("execution_contract"), dict):
                raise ProtocolError("Benchmark identity execution_contract must be an object")
        baseline_ref = benchmark_identity.get("workspace_baseline_ref")
        if baseline_ref is not None and (
            not isinstance(baseline_ref, str) or not baseline_ref
        ):
            raise ProtocolError(
                "Benchmark identity workspace_baseline_ref must be a string or null"
            )
        acceptance_sha = benchmark_identity.get("acceptance_contract_sha256")
        if acceptance_sha is not None and (
            not isinstance(acceptance_sha, str) or not acceptance_sha
        ):
            raise ProtocolError(
                "Benchmark identity acceptance_contract_sha256 must be a string or null"
            )

    if side_effect_coverage is not None:
        if not isinstance(side_effect_coverage, dict):
            raise ProtocolError("Session audit_evidence.side_effect_coverage must be an object")
        expected_effects = {"workspace", "process", "network", "credential", "payment"}
        if set(side_effect_coverage) != expected_effects:
            raise ProtocolError("Side effect coverage must declare all five effect types")
        for effect_type, coverage in side_effect_coverage.items():
            if not isinstance(coverage, dict):
                raise ProtocolError(f"Side effect coverage {effect_type} must be an object")
            status = coverage.get("status")
            if status not in (
                "observed", "not_observed", "full", "partial", "none", "not_applicable"
            ):
                raise ProtocolError(f"Side effect coverage {effect_type} status is invalid")
            if coverage.get("evidence_source") not in (
                "harness",
                "agent",
                "provider",
                "unavailable",
            ):
                raise ProtocolError(
                    f"Side effect coverage {effect_type} evidence_source is invalid"
                )
            if status in {"full", "partial", "none", "not_applicable"}:
                if not _string_or_none(coverage.get("scope")):
                    raise ProtocolError(f"Side effect coverage {effect_type} scope is required")
                blind_spots = coverage.get("blind_spots")
                if not isinstance(blind_spots, list) or not all(
                    isinstance(item, str) and item for item in blind_spots
                ):
                    raise ProtocolError(
                        f"Side effect coverage {effect_type} blind_spots must be a list of strings"
                    )

    evidence = {
        "decision_points": [dict(item) for item in decision_points],
        "side_effects": [dict(item) for item in side_effects],
        "capability_contributions": [dict(item) for item in capability_contributions],
    }
    if independent_verification is not None:
        evidence["independent_verification"] = dict(independent_verification)
    if benchmark_identity is not None:
        evidence["benchmark_identity"] = dict(benchmark_identity)
    if side_effect_coverage is not None:
        evidence["side_effect_coverage"] = {
            key: dict(item) for key, item in side_effect_coverage.items()
        }
    return evidence


def _session_audit_evidence(
    record: SessionRecord,
    spec: SessionSpec,
    packet: DispatchPacket | None = None,
) -> dict[str, Any]:
    evidence = _load_audit_evidence(record.audit_evidence)
    if packet is not None:
        verification = record.result_proposal or record.extraction
        verification_status = _mapping_value(verification.get("verification")).get(
            "status", "not_run"
        )
        selected_action = f"dispatch_agent:{spec.agent_id}"
        rejected_candidates = [
            {
                "action": f"routing_mode:{item['mode']}",
                "disposition": "rejected",
                "reason": item["rejected_because"],
            }
            for item in packet.routing_decision.rejected_modes
        ]
        evidence.setdefault("decision_points", []).append(
            {
                "decision_id": f"decision-{record.session_id}-dispatch",
                "decision_type": "dispatch",
                "source": "harness",
                "evidence_available_at_time": [
                    "dispatch_packet.routing_decision",
                    "dispatch_packet.assignment",
                    "dispatch.session_spec",
                ],
                "action_selected": selected_action,
                "alternatives_visible": [item["action"] for item in rejected_candidates],
                "candidate_set": [
                    {
                        "action": selected_action,
                        "disposition": "selected",
                        "reason": packet.routing_decision.reason,
                    },
                    *rejected_candidates,
                ],
                "selection_basis": {
                    "selection_policy_version": packet.routing_decision.selection_policy_version,
                    "triggered_rules": packet.routing_decision.triggered_rules,
                    "reason": packet.routing_decision.reason,
                    "budget_reason": packet.routing_decision.budget_reason,
                    "risk_reason": packet.routing_decision.risk_reason,
                    "budget_confidence": packet.routing_decision.budget_confidence,
                    "estimated_coordination_ratio": packet.routing_decision.estimated_coordination_ratio,
                    "advisor_gate_decision": packet.routing_decision.advisor_gate_decision,
                },
                "selection_scope": {
                    "routing_mode": "policy_selected",
                    "agent_id": "operator_fixed",
                    "target_provider": "operator_fixed",
                    "target_model": "operator_fixed",
                },
                "selected_context": {
                    "routing_mode": packet.routing_decision.selected_mode,
                    "selection_policy_version": packet.routing_decision.selection_policy_version,
                    "agent_id": spec.agent_id,
                    "target_provider": spec.target_provider,
                    "target_model": spec.target_model,
                },
                "later_outcome": {
                    "session_status": record.status,
                    "exit_reason": record.exit.get("reason"),
                    "changed_files_count": record.outcome_metrics.get(
                        "changed_files_count"
                    ),
                    "agent_verification_status": verification_status,
                },
            }
        )
    effects = evidence.setdefault("side_effects", [])
    credential_env = spec.provider_api_key_env
    if spec.target_model and spec.target_provider:
        credential_env = resolve_agent_binding(
            spec.agent_id,
            target_model=spec.target_model,
            target_provider=spec.target_provider,
            provider_base_url=spec.provider_base_url,
            provider_api_key_env=spec.provider_api_key_env,
            provider_wire_api=spec.provider_wire_api,
        ).api_key_env
    if (
        spec.agent_id != "fake"
        and record.status != "dry_run"
        and record.exit.get("reason") != "launch_failed"
    ):
        effects.append(
            {"type": "process", "source": "harness", "verified": True, "evidence_ref": "exit"}
        )
        if credential_env:
            effects.append(
                {
                    "type": "credential",
                    "source": "harness",
                    "verified": True,
                    "evidence_ref": "dispatch.session_spec.provider_api_key_env",
                }
            )
    if _int_value(record.outcome_metrics.get("changed_files_count")) > 0:
        effects.append(
            {
                "type": "workspace",
                "source": "harness",
                "verified": True,
                "evidence_ref": "diff_refs",
            }
        )
    if isinstance(record.extraction.get("provider_usage_capture"), dict):
        effects.append(
            {
                "type": "network",
                "source": "harness",
                "verified": True,
                "evidence_ref": "extraction.provider_usage_capture",
            }
        )
    observed_effects = {
        effect["type"]: effect for effect in effects if effect.get("verified") is not False
    }
    workspace_observed = all(
        isinstance(record.workspace.get(key), str)
        for key in ("pre_state_ref", "post_state_ref")
    )
    process_observed = "process" in observed_effects
    credential_expected = bool(credential_env)
    evidence["side_effect_coverage"] = {
        "workspace": _side_effect_coverage_entry(
            observed=workspace_observed,
            source="harness",
            evidence_ref="workspace.pre_state_ref+post_state_ref",
            scope="regular_file_content_hashes",
            blind_spots=["symlinks", "file_modes", "permissions", "extended_attributes"],
        ),
        "process": _side_effect_coverage_entry(
            observed=process_observed,
            source="harness",
            evidence_ref="exit",
            scope="outer_agent_process_group_lifecycle",
            blind_spots=["detached_descendants", "external_processes"],
            not_applicable=record.status == "dry_run",
        ),
        "network": _side_effect_coverage_entry(
            observed="network" in observed_effects,
            source="harness",
            evidence_ref="extraction.provider_usage_capture",
            scope="configured_provider_proxy",
            blind_spots=["direct_agent_egress", "child_process_network"],
        ),
        "credential": (
            _side_effect_coverage_entry(
                observed="credential" in observed_effects,
                source="harness",
                evidence_ref="dispatch.session_spec.provider_api_key_env",
                scope="selected_child_environment",
                blind_spots=["retrieved_secrets", "transformed_secrets", "downstream_handling"],
            )
            if credential_expected
            else _side_effect_coverage_entry(
                observed=False,
                source="unavailable",
                evidence_ref=None,
                scope="selected_child_environment",
                blind_spots=[],
                not_applicable=True,
            )
        ),
        "payment": _side_effect_coverage_entry(
            observed=False,
            source="unavailable",
            evidence_ref=None,
            scope="provider_billing_and_settlement",
            blind_spots=["external_billing_state", "payment_settlement"],
        ),
    }
    return evidence


def _side_effect_coverage_entry(
    *,
    observed: bool,
    source: str,
    evidence_ref: str | None,
    scope: str,
    blind_spots: list[str],
    not_applicable: bool = False,
) -> dict[str, Any]:
    return {
        "status": "not_applicable" if not_applicable else "partial" if observed else "none",
        "scope": scope,
        "blind_spots": blind_spots,
        "evidence_source": source if observed else "unavailable",
        "evidence_ref": evidence_ref if observed else None,
    }


def run_independent_verification(
    command_text: str,
    workdir: Path,
    *,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    try:
        command = shlex.split(command_text)
    except ValueError as exc:
        raise ProtocolError(f"Verification command is invalid: {exc}") from exc
    if not command:
        raise ProtocolError("Verification command must not be empty")
    if timeout_seconds <= 0:
        raise ProtocolError("Verification timeout must be > 0")
    if not workdir.is_dir():
        raise ProtocolError("Verification workspace does not exist")

    env = os.environ.copy()
    sensitive_values: list[str] = []
    for name in list(env):
        if _secret_environment_name(name):
            value = env.pop(name)
            if len(value) >= 4:
                sensitive_values.append(value)
    env.pop("PYTHONPATH", None)
    started_at = _now()
    started_monotonic = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="bureauless-verification-") as temporary:
        verification_root = Path(temporary)
        verification_workdir = verification_root / "workspace"
        shutil.copytree(
            workdir,
            verification_workdir,
            ignore=shutil.ignore_patterns(".bureauless", ".git"),
        )
        home = verification_root / "home"
        home.mkdir()
        env.update(
            {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_CACHE_HOME": str(home / ".cache"),
                "XDG_DATA_HOME": str(home / ".local" / "share"),
            }
        )
        try:
            completed = _run_live_process(
                command,
                cwd=verification_workdir,
                timeout=timeout_seconds,
                env=env,
                input_text=None,
                controller=None,
            )
            status = "passed" if completed.returncode == 0 else "failed"
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            status = "timed_out"
            exit_code = None
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
        except OSError as exc:
            status = "error"
            exit_code = None
            stdout = ""
            stderr = str(exc)

    secrets = tuple(sensitive_values)
    stdout_text = _redact_native_text(_text_value(stdout), secrets)
    stderr_text = _redact_native_text(_text_value(stderr), secrets)
    acceptance_contract = {
        "schema": "bureauless_independent_verification_v1",
        "command": command,
        "timeout_seconds": timeout_seconds,
        "workspace_mode": "copy_without_vcs_metadata",
        "environment_policy": "secret_named_variables_removed",
    }
    return {
        "schema": "bureauless_independent_verification_v1",
        "source": "harness",
        "status": status,
        "command": command,
        "command_sha256": hashlib.sha256(
            json.dumps(command, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "acceptance_contract_sha256": hashlib.sha256(
            json.dumps(acceptance_contract, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest(),
        "timeout_seconds": timeout_seconds,
        "started_at": started_at,
        "finished_at": _now(),
        "wall_time_ms": max(1, int((time.monotonic() - started_monotonic) * 1000)),
        "exit_code": exit_code,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "stdout_sha256": hashlib.sha256(stdout_text.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr_text.encode("utf-8")).hexdigest(),
        "workspace_mode": "copy_without_vcs_metadata",
        "environment_policy": "secret_named_variables_removed",
    }


def _secret_environment_name(name: str) -> bool:
    parts = name.upper().split("_")
    return any(part in {"KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"} for part in parts)


def _legacy_load_provider_usage_capture(data: dict[str, Any]) -> ProviderUsageCapture:
    artifact_type = _as_string(data, "artifact_type")
    if artifact_type != "provider_usage_capture":
        raise ProtocolError("Provider usage capture artifact_type must be provider_usage_capture")
    usage = _as_mapping(data, "usage", default={})
    _validate_provider_usage_capture_usage(usage)
    return ProviderUsageCapture(
        assignment_id=_as_string(data, "assignment_id"),
        session_id=_as_string(data, "session_id"),
        agent_id=_as_string(data, "agent_id"),
        provider=_as_string(data, "provider"),
        model=_as_string(data, "model"),
        collected_at=_as_string(data, "collected_at"),
        source=_as_string(data, "source"),
        usage=usage,
        result_id=_string_or_none(data.get("result_id")),
        source_ref=_string_or_none(data.get("source_ref")),
    )


def _legacy_write_provider_usage_capture_artifact(
    path: Path,
    capture: ProviderUsageCapture,
    *,
    created_by: str = "harness",
    source_event: str | None = None,
) -> dict[str, Any]:
    payload = capture.to_dict()
    content = yaml.safe_dump(payload, sort_keys=False).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ProtocolError(f"Immutable provider usage artifact differs: {path}")
    else:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    digest = sha256_file(path)
    if digest != hashlib.sha256(content).hexdigest():
        raise ProtocolError(f"Provider usage artifact hash verification failed: {path}")
    artifact_id_suffix = capture.result_id or capture.session_id
    artifact: dict[str, Any] = {
        "artifact_id": f"artifact-{artifact_id_suffix}-provider-usage",
        "path": str(path),
        "sha256": digest,
        "created_by": created_by,
        "mutable": False,
        "artifact_type": "provider_usage_capture",
    }
    if source_event is not None:
        artifact["source_event"] = source_event
    return artifact


def _validate_provider_usage_capture_usage(usage: dict[str, Any]) -> None:
    allowed_fields = {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "reasoning_output_tokens",
        "cost_usd",
        "cost_source",
        "cost_confidence",
        "usage_confidence",
    }
    unknown_fields = sorted(set(usage) - allowed_fields)
    if unknown_fields:
        raise ProtocolError(
            "Provider usage capture usage contains unknown fields: "
            + ", ".join(unknown_fields)
        )
    for field in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "reasoning_output_tokens",
    ):
        value = usage.get(field)
        if value is not None and (not isinstance(value, int) or value < 0):
            raise ProtocolError(f"Provider usage capture {field} must be a non-negative integer")
    cost_usd = usage.get("cost_usd")
    if cost_usd is not None and (
        not isinstance(cost_usd, (int, float))
        or isinstance(cost_usd, bool)
        or float(cost_usd) < 0
    ):
        raise ProtocolError("Provider usage capture cost_usd must be non-negative when present")
    for field in ("cost_source", "cost_confidence", "usage_confidence"):
        value = usage.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ProtocolError(f"Provider usage capture {field} must be a non-empty string when present")
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    total_tokens = usage.get("total_tokens")
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        derived_total = input_tokens + output_tokens
        if total_tokens is None:
            usage["total_tokens"] = derived_total
        elif total_tokens != derived_total:
            raise ProtocolError("Provider usage capture total_tokens must equal input_tokens + output_tokens")


def _join_upstream_url(base_url: str, request_path: str) -> str:
    if request_path.startswith(("http://", "https://")):
        return request_path
    return urllib_parse.urljoin(f"{base_url.rstrip('/')}/", request_path.lstrip("/"))


def _extract_openai_compatible_usage_capture(payload: dict[str, Any]) -> dict[str, Any] | None:
    if (
        payload.get("type") == "response.completed"
        and isinstance(payload.get("response"), dict)
    ):
        payload = payload["response"]
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None

    normalized_usage: dict[str, Any] = {}
    input_tokens = usage.get("input_tokens")
    if not isinstance(input_tokens, int):
        input_tokens = usage.get("prompt_tokens")
    if isinstance(input_tokens, int):
        normalized_usage["input_tokens"] = input_tokens

    output_tokens = usage.get("output_tokens")
    if not isinstance(output_tokens, int):
        output_tokens = usage.get("completion_tokens")
    if isinstance(output_tokens, int):
        normalized_usage["output_tokens"] = output_tokens

    total_tokens = usage.get("total_tokens")
    if isinstance(total_tokens, int):
        normalized_usage["total_tokens"] = total_tokens

    input_details = usage.get("input_tokens_details")
    if not isinstance(input_details, dict):
        input_details = usage.get("prompt_tokens_details")
    cached_input_tokens = (
        input_details.get("cached_tokens") if isinstance(input_details, dict) else None
    )
    if isinstance(cached_input_tokens, int):
        normalized_usage["cached_input_tokens"] = cached_input_tokens

    output_details = usage.get("output_tokens_details")
    if not isinstance(output_details, dict):
        output_details = usage.get("completion_tokens_details")
    reasoning_output_tokens = (
        output_details.get("reasoning_tokens") if isinstance(output_details, dict) else None
    )
    if isinstance(reasoning_output_tokens, int):
        normalized_usage["reasoning_output_tokens"] = reasoning_output_tokens

    if not normalized_usage:
        return None
    normalized_usage["usage_confidence"] = "high"
    _validate_provider_usage_capture_usage(normalized_usage)

    model = _string_or_none(payload.get("model"))
    if model is None:
        return None
    source_ref = _string_or_none(payload.get("id"))
    return {"model": model, "usage": normalized_usage, "source_ref": source_ref}


def _retarget_binding_base_url(binding: Any, base_url: str) -> Any:
    overrides = dict(getattr(binding, "codex_config_overrides", {}))
    if binding.provider_id == "openai":
        overrides["openai_base_url"] = base_url
    else:
        for key in list(overrides):
            if key.endswith(".base_url"):
                overrides[key] = base_url
    return replace(binding, base_url=base_url, codex_config_overrides=overrides)


def _legacy_build_provider_usage_capture_from_proxy(
    telemetry_capture: dict[str, Any] | None,
    *,
    assignment_id: str,
    session_id: str,
    agent_id: str,
    result_id: str,
    collected_at: str,
) -> ProviderUsageCapture | None:
    if not isinstance(telemetry_capture, dict):
        return None
    usage = telemetry_capture.get("usage")
    if not isinstance(usage, dict):
        return None
    _validate_provider_usage_capture_usage(usage)
    provider = _string_or_none(telemetry_capture.get("provider"))
    model = _string_or_none(telemetry_capture.get("model"))
    if provider is None or model is None:
        return None
    return ProviderUsageCapture(
        assignment_id=assignment_id,
        session_id=session_id,
        agent_id=agent_id,
        provider=provider,
        model=model,
        collected_at=collected_at,
        usage=dict(usage),
        result_id=result_id,
        source_ref=_string_or_none(telemetry_capture.get("source_ref")),
    )


def _legacy_merge_provider_usage_into_outcome_metrics(
    outcome_metrics: dict[str, Any],
    capture: ProviderUsageCapture | None,
) -> dict[str, Any]:
    if capture is None:
        return dict(outcome_metrics)
    merged = dict(outcome_metrics)
    usage = capture.usage
    for field in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "reasoning_output_tokens",
        "cost_usd",
        "usage_source",
        "usage_confidence",
        "cost_source",
        "cost_confidence",
    ):
        if field in usage:
            merged[field] = usage[field]
    merged["usage_source"] = "provider_attributed"
    if (
        "usage_confidence" not in usage
        and any(field in usage for field in ("input_tokens", "output_tokens", "total_tokens"))
    ):
        merged["usage_confidence"] = "high"
    if "cost_usd" in usage:
        merged.setdefault("cost_source", "provider_attributed")
        merged.setdefault("cost_confidence", "high")
    if (
        "total_tokens" not in merged
        and isinstance(merged.get("input_tokens"), int)
        and isinstance(merged.get("output_tokens"), int)
    ):
        merged["total_tokens"] = merged["input_tokens"] + merged["output_tokens"]
    return merged


def _load_session_spec(data: dict[str, Any]) -> SessionSpec:
    timeout_seconds = data.get("timeout_seconds")
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise ProtocolError("Dispatch session_spec.timeout_seconds must be > 0")
    return SessionSpec(
        session_id=_as_string(data, "session_id"),
        assignment_id=_as_string(data, "assignment_id"),
        agent_id=_as_string(data, "agent_id"),
        workdir=_as_string(data, "workdir"),
        timeout_seconds=float(timeout_seconds),
        dry_run=_as_bool(data, "dry_run"),
        isolation_mode=_as_string(data, "isolation_mode"),
        cleanup_policy=_as_string(data, "cleanup_policy"),
        sandbox_mode=_as_string(data, "sandbox_mode"),
        shell_command=_string_or_none(data.get("shell_command")),
        target_model=_string_or_none(data.get("target_model")),
        target_provider=_string_or_none(data.get("target_provider")),
        provider_base_url=_string_or_none(data.get("provider_base_url")),
        provider_api_key_env=_string_or_none(data.get("provider_api_key_env")),
        provider_wire_api=_string_or_none(data.get("provider_wire_api")),
        reuse_workspace_path=_string_or_none(data.get("reuse_workspace_path")),
    )


def _validate_dispatch_binding(packet: DispatchPacket, spec: SessionSpec) -> None:
    if spec.assignment_id != packet.assignment.assignment_id:
        raise ProtocolError("Dispatch binding assignment_id does not match packet")
    if spec.agent_id in SUPPORTED_SESSION_AGENTS:
        return
    if spec.target_model is None or spec.target_provider is None:
        raise ProtocolError("Dispatch binding is missing agent model or provider")
    resolve_agent_binding(
        spec.agent_id,
        target_model=spec.target_model,
        target_provider=spec.target_provider,
        provider_base_url=spec.provider_base_url,
        provider_api_key_env=spec.provider_api_key_env,
        provider_wire_api=spec.provider_wire_api,
    )


def _write_dispatch_packet(path: Path, packet: DispatchPacket) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(packet.to_dict(), handle, sort_keys=False)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def package_session_result(
    record: SessionRecord,
    assignment: AssignmentPacket,
    artifact_root: Path | None = None,
    result_id: str | None = None,
) -> ResultProposal:
    if record.assignment_id != assignment.assignment_id:
        raise ProtocolError("Session record assignment_id does not match assignment packet")
    if record.status != "completed":
        raise ProtocolError(f"Cannot package session result from status {record.status!r}")
    if not isinstance(record.result_proposal, dict):
        raise ProtocolError("Session record is missing an import-ready result proposal payload")

    base = load_result_proposal(record.result_proposal)
    if base.assignment_id != assignment.assignment_id:
        raise ProtocolError("Session result proposal assignment_id does not match assignment packet")
    if base.agent_id != record.agent_id:
        raise ProtocolError("Session result proposal agent_id does not match session record")

    packaged_result_id = result_id or base.result_id
    source_event = f"event-{packaged_result_id}"
    package_root, workspace_root = _packaging_roots(record, artifact_root)
    provider_capture = _load_provider_usage_capture_for_record(record, result_id=packaged_result_id)
    packaged_outcome_metrics = _merge_provider_usage_into_outcome_metrics(
        base.outcome_metrics,
        provider_capture,
    )
    artifacts: list[dict[str, Any]] = []
    for index, artifact in enumerate(base.artifacts or record.artifacts, start=1):
        normalized = _normalize_packaged_artifact(
            artifact,
            package_root=package_root,
            workspace_root=workspace_root,
            source_event=source_event,
            created_by=record.agent_id,
            fallback_id=f"artifact-{packaged_result_id}-{index:03d}",
        )
        if normalized is not None:
            artifacts.append(normalized)
    provider_usage_artifact = _package_provider_usage_capture(
        record,
        base,
        package_root=package_root,
        workspace_root=workspace_root,
        source_event=source_event,
    )
    if provider_usage_artifact is not None:
        artifacts.append(provider_usage_artifact)
    native_log_refs = _package_native_log_refs(
        record,
        package_root,
        source_event,
        packaged_result_id,
    )

    return ResultProposal(
        result_id=packaged_result_id,
        assignment_id=base.assignment_id,
        agent_id=base.agent_id,
        status=base.status,
        effective_model=base.effective_model,
        effective_provider=base.effective_provider,
        emitted_events=list(base.emitted_events),
        artifacts=artifacts,
        outcome_metrics=packaged_outcome_metrics,
        verification=dict(base.verification),
        native_log_refs=native_log_refs,
        mutation_proposal_refs=list(base.mutation_proposal_refs),
        review_status=base.review_status,
        control_intents=list(base.control_intents),
        model_identity=dict(base.model_identity),
        metric_provenance=dict(base.metric_provenance),
        route_evidence=dict(base.route_evidence),
    )


def import_session_record(
    workflow: Workflow,
    ledger: Any,
    assignment: AssignmentPacket,
    record: SessionRecord,
    *,
    artifact_root: Path | None = None,
    result_id: str | None = None,
    outcome_id: str | None = None,
    decision_event_id: str | None = None,
    actor: str = "harness",
    disposition: str = "accepted",
    accepted_event_types: list[str] | None = None,
    validation_rule: str | None = None,
) -> Any:
    if ledger.ledger_version >= STRICT_ACCEPTANCE_LEDGER_VERSION:
        raise ProtocolError(
            "Strict session import must use application.acceptance.stage_session_record "
            "and decide_staged_result"
        )
    result = package_session_result(
        record,
        assignment,
        artifact_root=artifact_root,
        result_id=result_id,
    )
    updated = import_result_proposal(workflow, ledger, assignment, result)
    outcome = reconcile_node_outcome_state(
        node_outcome_from_session(
            assignment,
            record.to_dict(),
            outcome_id=outcome_id,
        ),
        _accepted_workspace_ref_for_node(ledger, assignment.node_id),
    )
    accepted_event_types = accepted_event_types or result.emitted_events
    if outcome.status in {"stale", "needs_review"}:
        accepted_event_types = []
    decision_event = build_node_outcome_decision_event(
        outcome,
        event_id=decision_event_id or f"event-{outcome.outcome_id}-decision",
        mission_id=workflow.mission_id,
        workflow_id=workflow.workflow_id,
        actor=actor,
        disposition=disposition,
        accepted_event_types=accepted_event_types,
        validation_rule=validation_rule,
        created_at=record.finished_at,
    )
    return append_ledger_event(updated, decision_event, workflow)


def _run_shell_dummy_session(
    spec: SessionSpec,
    assignment: AssignmentPacket,
    started_at: str,
    started_monotonic: float,
    *,
    process_controller: _ProcessController | None = None,
) -> SessionRecord:
    source_root = Path(spec.workdir).resolve()
    source_root.mkdir(parents=True, exist_ok=True)
    workspace = _prepare_session_workspace(spec, source_root)
    workdir = Path(_as_string(workspace, "path"))
    baseline = _capture_workspace_baseline(workdir)
    _set_workspace_state_refs(workspace, baseline.files)
    try:
        completed = _run_live_process(
            ["bash", "-lc", spec.shell_command or ""],
            cwd=workdir,
            timeout=spec.timeout_seconds,
            env=None,
            input_text=None,
            controller=process_controller,
        )
    except subprocess.TimeoutExpired as exc:
        finished_at = _now()
        native_logs = _persist_native_logs(workspace, exc.stdout or "", exc.stderr or "")
        _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
        outcome_metrics = _base_outcome_metrics(
            wall_time_ms=max(1, int((time.monotonic() - started_monotonic) * 1000))
        )
        return SessionRecord(
            session_id=spec.session_id,
            assignment_id=spec.assignment_id,
            agent_id=spec.agent_id,
            status="timed_out",
            started_at=started_at,
            finished_at=finished_at,
            exit={"code": None, "reason": "timed_out"},
            native_logs=native_logs,
            diff_refs=[],
            artifacts=[],
            workspace=workspace,
            outcome_metrics=outcome_metrics,
            extraction={
                "contract": "shell_dummy_v1",
                "status": "timed_out",
                "warnings": [],
                "parsed_fields": [],
                "missing_fields": [],
            },
            result_proposal=None,
        )
    except OSError as exc:
        finished_at = _now()
        native_logs = _persist_native_logs(workspace, "", str(exc))
        _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
        outcome_metrics = _base_outcome_metrics(
            wall_time_ms=max(1, int((time.monotonic() - started_monotonic) * 1000))
        )
        return SessionRecord(
            session_id=spec.session_id,
            assignment_id=spec.assignment_id,
            agent_id=spec.agent_id,
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            exit={"code": 1, "reason": "launch_failed"},
            native_logs=native_logs,
            diff_refs=[],
            artifacts=[],
            workspace=workspace,
            outcome_metrics=outcome_metrics,
            extraction={
                "contract": "shell_dummy_v1",
                "status": "launch_failed",
                "warnings": [str(exc)],
                "parsed_fields": [],
                "missing_fields": [],
            },
            result_proposal=None,
        )

    finished_at = _now()
    wall_time_ms = max(1, int((time.monotonic() - started_monotonic) * 1000))
    status = "completed" if completed.returncode == 0 else "failed"
    native_logs = _persist_native_logs(workspace, completed.stdout, completed.stderr)
    extraction = _extract_shell_dummy_output(spec, assignment, completed.stdout)
    baseline_metrics, baseline_diff_refs = _collect_workspace_delta(workdir, baseline)
    _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
    outcome_metrics = _merge_outcome_metrics(
        _merge_outcome_metrics(_base_outcome_metrics(wall_time_ms=wall_time_ms), baseline_metrics),
        _as_mapping(extraction, "outcome_metrics", default={}),
    )
    if not extraction["diff_refs"] and baseline_diff_refs:
        extraction["diff_refs"] = baseline_diff_refs
    result_proposal = None
    if completed.returncode == 0:
        result = ResultProposal(
            result_id=f"result-{spec.session_id}",
            assignment_id=assignment.assignment_id,
            agent_id=spec.agent_id,
            status=_string_value(extraction.get("result_status"), default="completed"),
            effective_model=_string_or_none(extraction.get("effective_model")),
            effective_provider=_string_or_none(extraction.get("effective_provider")),
            emitted_events=_string_list_value(extraction.get("emitted_events")),
            artifacts=_as_mapping_list(extraction, "artifacts", default=[]),
            outcome_metrics=outcome_metrics,
            verification=_as_mapping(extraction, "verification", default={"status": "not_run"}),
            native_log_refs=_as_mapping_list(extraction, "native_log_refs", default=[]),
            mutation_proposal_refs=_string_list_value(
                extraction.get("mutation_proposal_refs")
            ),
            review_status=_string_or_none(extraction.get("review_status")),
            control_intents=_list_value(extraction.get("control_intents")),
        )
        result_proposal = result.to_dict()

    return SessionRecord(
        session_id=spec.session_id,
        assignment_id=spec.assignment_id,
        agent_id=spec.agent_id,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        exit={"code": completed.returncode, "reason": status},
        native_logs=native_logs,
        diff_refs=_as_mapping_list(extraction, "diff_refs", default=[]),
        artifacts=_as_mapping_list(extraction, "artifacts", default=[]),
        workspace=workspace,
        outcome_metrics=outcome_metrics,
        extraction=extraction,
        result_proposal=result_proposal,
    )


def _run_codex_cli_session(
    spec: SessionSpec,
    assignment: AssignmentPacket,
    started_at: str,
    started_monotonic: float,
    *,
    command_runner: CommandRunner | None = None,
    dispatch_packet: DispatchPacket | None = None,
    process_controller: _ProcessController | None = None,
    context_resolution: dict[str, Any] | None = None,
) -> SessionRecord:
    source_root = Path(spec.workdir).resolve()
    source_root.mkdir(parents=True, exist_ok=True)
    workspace = _prepare_session_workspace(spec, source_root)
    workdir = Path(_as_string(workspace, "path"))
    baseline = _capture_workspace_baseline(workdir)
    _set_workspace_state_refs(workspace, baseline.files)
    binding = resolve_agent_binding(
        spec.agent_id,
        target_model=_as_string({"target_model": spec.target_model}, "target_model"),
        target_provider=_as_string({"target_provider": spec.target_provider}, "target_provider"),
        provider_base_url=spec.provider_base_url,
        provider_api_key_env=spec.provider_api_key_env,
        provider_wire_api=spec.provider_wire_api,
    )
    sensitive_values = _binding_secret_values(binding)
    telemetry_proxy: _OpenAICompatibleTelemetryProxy | None = None
    telemetry_capture: dict[str, Any] | None = None
    try:
        if binding.provider_id == "openai-compatible" and binding.base_url:
            telemetry_proxy = _OpenAICompatibleTelemetryProxy(binding.base_url)
            binding = _retarget_binding_base_url(binding, telemetry_proxy.base_url)
        env = _build_codex_environment(binding)
        codex_home = _prepare_codex_home(workspace, binding, env)
        command = _build_codex_command(spec, binding, workdir)
        prompt = _render_codex_assignment_prompt(
            assignment,
            dispatch_packet=dispatch_packet,
            context_resolution=context_resolution,
        )

        try:
            try:
                completed = _run_command_runner(
                    command_runner,
                    command,
                    cwd=workdir,
                    env=env,
                    timeout=spec.timeout_seconds,
                    input_text=prompt,
                    process_controller=process_controller,
                    progress_line=_is_codex_native_progress_line,
                )
            finally:
                _cleanup_codex_home(codex_home)
        finally:
            if telemetry_proxy is not None:
                telemetry_capture = telemetry_proxy.snapshot()
                telemetry_proxy.close()
    except subprocess.TimeoutExpired as exc:
        timeout_reason = _timeout_reason(exc)
        finished_at = _now()
        native_logs = _persist_native_logs(
            workspace,
            exc.stdout or "",
            exc.stderr or "",
            sensitive_values=sensitive_values,
        )
        _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
        outcome_metrics = _base_outcome_metrics(
            wall_time_ms=max(1, int((time.monotonic() - started_monotonic) * 1000))
        )
        extraction = _empty_agent_extraction(timeout_reason, [])
        extraction["contract"] = "codex_exec_v1"
        return SessionRecord(
            session_id=spec.session_id,
            assignment_id=spec.assignment_id,
            agent_id=spec.agent_id,
            status="timed_out",
            started_at=started_at,
            finished_at=finished_at,
            exit={"code": None, "reason": timeout_reason},
            native_logs=native_logs,
            diff_refs=[],
            artifacts=[],
            workspace=workspace,
            outcome_metrics=outcome_metrics,
            extraction=extraction,
            result_proposal=None,
        )
    except OSError as exc:
        finished_at = _now()
        warning = _redact_native_text(str(exc), sensitive_values)
        native_logs = _persist_native_logs(
            workspace,
            "",
            warning,
            sensitive_values=sensitive_values,
        )
        _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
        outcome_metrics = _base_outcome_metrics(
            wall_time_ms=max(1, int((time.monotonic() - started_monotonic) * 1000))
        )
        extraction = _empty_agent_extraction("launch_failed", [warning])
        extraction["contract"] = "codex_exec_v1"
        return SessionRecord(
            session_id=spec.session_id,
            assignment_id=spec.assignment_id,
            agent_id=spec.agent_id,
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            exit={"code": 1, "reason": "launch_failed"},
            native_logs=native_logs,
            diff_refs=[],
            artifacts=[],
            workspace=workspace,
            outcome_metrics=outcome_metrics,
            extraction=extraction,
            result_proposal=None,
        )

    finished_at = _now()
    wall_time_ms = max(1, int((time.monotonic() - started_monotonic) * 1000))
    status = "completed" if completed.returncode == 0 else "failed"
    stdout = _redact_native_text(_text_value(completed.stdout), sensitive_values)
    stderr = _redact_native_text(_text_value(completed.stderr), sensitive_values)
    native_logs = _persist_native_logs(
        workspace,
        stdout,
        stderr,
        sensitive_values=sensitive_values,
    )
    diff_metrics, diff_refs = _collect_workspace_delta(workdir, baseline)
    _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
    codex_metrics, codex_extraction = _extract_codex_jsonl(stdout)
    outcome_metrics = _merge_outcome_metrics(
        _merge_outcome_metrics(_base_outcome_metrics(wall_time_ms=wall_time_ms), diff_metrics),
        codex_metrics,
    )
    extraction = _empty_agent_extraction("native_stream_captured", [])
    extraction["contract"] = "codex_exec_v1"
    extraction["parsed_fields"] = ["effective_model", "effective_provider"]
    extraction["effective_model"] = binding.model
    extraction["effective_provider"] = binding.provider_id
    extraction["warnings"].extend(codex_extraction.get("warnings", []))
    extraction["parsed_fields"].extend(_string_list_value(codex_extraction.get("parsed_fields")))
    extraction["native_event_stream_observed"] = (
        codex_extraction.get("native_event_stream_observed") is True
    )
    extraction["native_tool_events"] = _mapping_list_value(
        codex_extraction.get("native_tool_events")
    )
    assistant_text = _string_or_none(codex_extraction.get("assistant_text"))
    if assistant_text is not None:
        extraction["assistant_text"] = assistant_text
    for field in (
        "result_status",
        "review_status",
        "emitted_events",
        "artifacts",
        "verification",
        "native_log_refs",
        "mutation_proposal_refs",
        "control_intents",
        "context_request",
    ):
        if field in codex_extraction:
            extraction[field] = codex_extraction[field]
    extraction["diff_refs"] = diff_refs
    extraction["outcome_metrics"] = outcome_metrics
    extraction["missing_fields"] = _missing_usage_fields(outcome_metrics)
    result_proposal = None
    if completed.returncode == 0:
        result_status = _string_or_none(codex_extraction.get("result_status")) or "completed"
        review_status = _string_or_none(codex_extraction.get("review_status"))
        result_id = f"result-{spec.session_id}"
        provider_capture = _build_provider_usage_capture_from_proxy(
            telemetry_capture,
            assignment_id=assignment.assignment_id,
            session_id=spec.session_id,
            agent_id=spec.agent_id,
            result_id=result_id,
            collected_at=finished_at,
        )
        outcome_metrics = _merge_provider_usage_into_outcome_metrics(
            outcome_metrics,
            provider_capture,
        )
        extraction["outcome_metrics"] = outcome_metrics
        extraction["missing_fields"] = _missing_usage_fields(outcome_metrics)
        result_proposal = ResultProposal(
            result_id=result_id,
            assignment_id=assignment.assignment_id,
            agent_id=spec.agent_id,
            status=result_status,
            effective_model=binding.model,
            effective_provider=binding.provider_id,
            emitted_events=_string_list_value(codex_extraction.get("emitted_events")),
            artifacts=_mapping_list_value(codex_extraction.get("artifacts")),
            outcome_metrics=outcome_metrics,
            verification=_mapping_value(
                codex_extraction.get("verification"),
                default={"status": "not_run"},
            ),
            native_log_refs=_mapping_list_value(codex_extraction.get("native_log_refs")),
            mutation_proposal_refs=_string_list_value(
                codex_extraction.get("mutation_proposal_refs")
            ),
            review_status=review_status,
            control_intents=_list_value(codex_extraction.get("control_intents")),
            model_identity=_model_identity(binding, codex_extraction),
            metric_provenance=_metric_provenance(
                spec.agent_id, binding.provider_id, outcome_metrics, extraction
            ),
            route_evidence=_session_route_evidence(
                spec.agent_id,
                binding.provider_id,
                outcome_metrics,
                extraction,
                _model_identity(binding, codex_extraction),
            ),
        ).to_dict()
        if provider_capture is not None:
            extraction["provider_usage_capture"] = provider_capture.to_dict()
            extraction["parsed_fields"].append("provider_usage_capture")

    return SessionRecord(
        session_id=spec.session_id,
        assignment_id=spec.assignment_id,
        agent_id=spec.agent_id,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        exit={"code": completed.returncode, "reason": status},
        native_logs=native_logs,
        diff_refs=diff_refs,
        artifacts=[],
        workspace=workspace,
        outcome_metrics=outcome_metrics,
        extraction=extraction,
        result_proposal=result_proposal,
    )


def _run_claude_code_session(
    spec: SessionSpec,
    assignment: AssignmentPacket,
    started_at: str,
    started_monotonic: float,
    *,
    command_runner: CommandRunner | None = None,
    dispatch_packet: DispatchPacket | None = None,
    process_controller: _ProcessController | None = None,
    context_resolution: dict[str, Any] | None = None,
) -> SessionRecord:
    source_root = Path(spec.workdir).resolve()
    source_root.mkdir(parents=True, exist_ok=True)
    workspace = _prepare_session_workspace(spec, source_root)
    workdir = Path(_as_string(workspace, "path"))
    baseline = _capture_workspace_baseline(workdir)
    _set_workspace_state_refs(workspace, baseline.files)
    binding = resolve_agent_binding(
        spec.agent_id,
        target_model=_as_string({"target_model": spec.target_model}, "target_model"),
        target_provider=_as_string({"target_provider": spec.target_provider}, "target_provider"),
        provider_base_url=spec.provider_base_url,
        provider_api_key_env=spec.provider_api_key_env,
        provider_wire_api=spec.provider_wire_api,
    )
    sensitive_values = _binding_secret_values(binding)
    try:
        completed = _run_command_runner(
            command_runner,
            _build_claude_code_command(binding),
            cwd=workdir,
            env=_build_claude_code_environment(binding, workspace),
            timeout=spec.timeout_seconds,
            input_text=_render_codex_assignment_prompt(
                assignment,
                dispatch_packet=dispatch_packet,
                context_resolution=context_resolution,
            ),
            process_controller=process_controller,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return _failed_cli_session_record(
            spec,
            workspace,
            baseline.files,
            workdir,
            started_at,
            started_monotonic,
            exc,
            contract="claude_stream_json_v1",
            binding=binding,
        )

    finished_at = _now()
    stdout = _redact_native_text(_text_value(completed.stdout), sensitive_values)
    stderr = _redact_native_text(_text_value(completed.stderr), sensitive_values)
    native_logs = _persist_native_logs(
        workspace,
        stdout,
        stderr,
        sensitive_values=sensitive_values,
    )
    diff_metrics, diff_refs = _collect_workspace_delta(workdir, baseline)
    _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
    claude_metrics, extraction = _extract_claude_stream_json(stdout)
    outcome_metrics = _merge_outcome_metrics(
        _merge_outcome_metrics(
            _base_outcome_metrics(
                wall_time_ms=max(1, int((time.monotonic() - started_monotonic) * 1000))
            ),
            diff_metrics,
        ),
        claude_metrics,
    )
    extraction.update(
        {
            "contract": "claude_stream_json_v1",
            "effective_model": binding.model,
            "effective_provider": binding.provider_id,
            "diff_refs": diff_refs,
            "outcome_metrics": outcome_metrics,
            "missing_fields": _missing_usage_fields(outcome_metrics),
        }
    )
    result = None
    if completed.returncode == 0:
        result = ResultProposal(
            result_id=f"result-{spec.session_id}",
            assignment_id=assignment.assignment_id,
            agent_id=spec.agent_id,
            status=_string_value(extraction.get("result_status"), default="completed"),
            effective_model=binding.model,
            effective_provider=binding.provider_id,
            emitted_events=_string_list_value(extraction.get("emitted_events")),
            artifacts=_mapping_list_value(extraction.get("artifacts")),
            outcome_metrics=outcome_metrics,
            verification=_mapping_value(extraction.get("verification"), default={"status": "not_run"}),
            native_log_refs=_mapping_list_value(extraction.get("native_log_refs")),
            mutation_proposal_refs=_string_list_value(extraction.get("mutation_proposal_refs")),
            review_status=_string_or_none(extraction.get("review_status")),
            control_intents=_list_value(extraction.get("control_intents")),
            model_identity=_model_identity(binding, extraction),
            metric_provenance=_metric_provenance(
                spec.agent_id, binding.provider_id, outcome_metrics, extraction
            ),
            route_evidence=_session_route_evidence(
                spec.agent_id,
                binding.provider_id,
                outcome_metrics,
                extraction,
                _model_identity(binding, extraction),
            ),
        ).to_dict()
    return SessionRecord(
        session_id=spec.session_id,
        assignment_id=spec.assignment_id,
        agent_id=spec.agent_id,
        status="completed" if completed.returncode == 0 else "failed",
        started_at=started_at,
        finished_at=finished_at,
        exit={"code": completed.returncode, "reason": "completed" if completed.returncode == 0 else "failed"},
        native_logs=native_logs,
        diff_refs=diff_refs,
        artifacts=[],
        workspace=workspace,
        outcome_metrics=outcome_metrics,
        extraction=extraction,
        result_proposal=result,
    )


def _run_gemini_cli_session(
    spec: SessionSpec,
    assignment: AssignmentPacket,
    started_at: str,
    started_monotonic: float,
    *,
    command_runner: CommandRunner | None = None,
    dispatch_packet: DispatchPacket | None = None,
    process_controller: _ProcessController | None = None,
    context_resolution: dict[str, Any] | None = None,
) -> SessionRecord:
    source_root = Path(spec.workdir).resolve()
    source_root.mkdir(parents=True, exist_ok=True)
    workspace = _prepare_session_workspace(spec, source_root)
    workdir = Path(_as_string(workspace, "path"))
    baseline = _capture_workspace_baseline(workdir)
    _set_workspace_state_refs(workspace, baseline.files)
    binding = resolve_agent_binding(
        spec.agent_id,
        target_model=_as_string({"target_model": spec.target_model}, "target_model"),
        target_provider=_as_string({"target_provider": spec.target_provider}, "target_provider"),
        provider_base_url=spec.provider_base_url,
        provider_api_key_env=spec.provider_api_key_env,
        provider_wire_api=spec.provider_wire_api,
    )
    sensitive_values = _binding_secret_values(binding)
    gemini_home: Path | None = None
    try:
        env = _build_gemini_environment(binding)
        gemini_home = _prepare_gemini_home(workspace, env)
        prompt = _render_codex_assignment_prompt(
            assignment,
            dispatch_packet=dispatch_packet,
            context_resolution=context_resolution,
        )
        try:
            completed = _run_command_runner(
                command_runner,
                _build_gemini_command(spec, binding, prompt),
                cwd=workdir,
                env=env,
                timeout=spec.timeout_seconds,
                input_text=None,
                process_controller=process_controller,
                progress_line=_is_codex_native_progress_line,
            )
        finally:
            _cleanup_gemini_home(gemini_home)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return _failed_cli_session_record(
            spec,
            workspace,
            baseline.files,
            workdir,
            started_at,
            started_monotonic,
            exc,
            contract="gemini_stream_json_v1",
            binding=binding,
        )

    finished_at = _now()
    stdout = _redact_native_text(_text_value(completed.stdout), sensitive_values)
    stderr = _redact_native_text(_text_value(completed.stderr), sensitive_values)
    native_logs = _persist_native_logs(
        workspace,
        stdout,
        stderr,
        sensitive_values=sensitive_values,
    )
    diff_metrics, diff_refs = _collect_workspace_delta(workdir, baseline)
    _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
    gemini_metrics, gemini_extraction = _extract_gemini_jsonl(stdout)
    outcome_metrics = _merge_outcome_metrics(
        _merge_outcome_metrics(
            _base_outcome_metrics(
                wall_time_ms=max(1, int((time.monotonic() - started_monotonic) * 1000))
            ),
            diff_metrics,
        ),
        gemini_metrics,
    )
    extraction = _empty_agent_extraction("native_stream_captured", [])
    extraction.update(
        {
            "contract": "gemini_stream_json_v1",
            "effective_model": binding.model,
            "effective_provider": binding.provider_id,
            "diff_refs": diff_refs,
            "outcome_metrics": outcome_metrics,
            "missing_fields": _missing_usage_fields(outcome_metrics),
        }
    )
    extraction["warnings"].extend(_string_list_value(gemini_extraction.get("warnings")))
    extraction["parsed_fields"] = [
        "effective_model",
        "effective_provider",
        *_string_list_value(gemini_extraction.get("parsed_fields")),
    ]
    for field in (
        "assistant_text",
        "native_event_stream_observed",
        "native_tool_events",
        "native_session_id",
        "provider_reported_models",
        "result_status",
        "review_status",
        "emitted_events",
        "artifacts",
        "verification",
        "native_log_refs",
        "mutation_proposal_refs",
        "control_intents",
        "context_request",
    ):
        if field in gemini_extraction:
            extraction[field] = gemini_extraction[field]

    result = None
    if completed.returncode == 0:
        result = ResultProposal(
            result_id=f"result-{spec.session_id}",
            assignment_id=assignment.assignment_id,
            agent_id=spec.agent_id,
            status=_string_value(gemini_extraction.get("result_status"), default="completed"),
            effective_model=binding.model,
            effective_provider=binding.provider_id,
            emitted_events=_string_list_value(gemini_extraction.get("emitted_events")),
            artifacts=_mapping_list_value(gemini_extraction.get("artifacts")),
            outcome_metrics=outcome_metrics,
            verification=_mapping_value(gemini_extraction.get("verification"), default={"status": "not_run"}),
            native_log_refs=_mapping_list_value(gemini_extraction.get("native_log_refs")),
            mutation_proposal_refs=_string_list_value(gemini_extraction.get("mutation_proposal_refs")),
            review_status=_string_or_none(gemini_extraction.get("review_status")),
            control_intents=_list_value(gemini_extraction.get("control_intents")),
            model_identity=_model_identity(binding, extraction),
            metric_provenance=_metric_provenance(
                spec.agent_id, binding.provider_id, outcome_metrics, extraction
            ),
            route_evidence=_session_route_evidence(
                spec.agent_id,
                binding.provider_id,
                outcome_metrics,
                extraction,
                _model_identity(binding, extraction),
            ),
        ).to_dict()
    return SessionRecord(
        session_id=spec.session_id,
        assignment_id=spec.assignment_id,
        agent_id=spec.agent_id,
        status="completed" if completed.returncode == 0 else "failed",
        started_at=started_at,
        finished_at=finished_at,
        exit={"code": completed.returncode, "reason": "completed" if completed.returncode == 0 else "failed"},
        native_logs=native_logs,
        diff_refs=diff_refs,
        artifacts=[],
        workspace=workspace,
        outcome_metrics=outcome_metrics,
        extraction=extraction,
        result_proposal=result,
    )


def _run_pi_session(
    spec: SessionSpec,
    assignment: AssignmentPacket,
    started_at: str,
    started_monotonic: float,
    *,
    command_runner: CommandRunner | None = None,
    dispatch_packet: DispatchPacket | None = None,
    process_controller: _ProcessController | None = None,
    context_resolution: dict[str, Any] | None = None,
) -> SessionRecord:
    source_root = Path(spec.workdir).resolve()
    source_root.mkdir(parents=True, exist_ok=True)
    workspace = _prepare_session_workspace(spec, source_root)
    workdir = Path(_as_string(workspace, "path"))
    baseline = _capture_workspace_baseline(workdir)
    _set_workspace_state_refs(workspace, baseline.files)
    binding = resolve_agent_binding(
        spec.agent_id,
        target_model=_as_string({"target_model": spec.target_model}, "target_model"),
        target_provider=_as_string({"target_provider": spec.target_provider}, "target_provider"),
        provider_base_url=spec.provider_base_url,
        provider_api_key_env=spec.provider_api_key_env,
        provider_wire_api=spec.provider_wire_api,
    )
    pi_root: Path | None = None
    try:
        env = _build_pi_environment(binding)
        pi_root = _prepare_pi_config(workspace, binding, env)
        completed = _run_command_runner(
            command_runner,
            _build_pi_command(
                spec,
                binding,
                _render_codex_assignment_prompt(
                    assignment,
                    dispatch_packet=dispatch_packet,
                    context_resolution=context_resolution,
                ),
            ),
            cwd=workdir,
            env=env,
            timeout=spec.timeout_seconds,
            input_text=None,
            process_controller=process_controller,
            progress_line=_is_codex_native_progress_line,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return _failed_cli_session_record(
            spec, workspace, baseline.files, workdir, started_at, started_monotonic, exc,
            contract="pi_json_v1",
            binding=binding,
        )
    finally:
        if pi_root is not None:
            shutil.rmtree(pi_root, ignore_errors=True)

    return _native_json_session_record(
        spec,
        assignment,
        workspace,
        workdir,
        baseline,
        started_at,
        started_monotonic,
        completed,
        binding,
        contract="pi_json_v1",
        extractor=_extract_pi_jsonl,
    )


def _run_opencode_session(
    spec: SessionSpec,
    assignment: AssignmentPacket,
    started_at: str,
    started_monotonic: float,
    *,
    command_runner: CommandRunner | None = None,
    dispatch_packet: DispatchPacket | None = None,
    process_controller: _ProcessController | None = None,
    context_resolution: dict[str, Any] | None = None,
) -> SessionRecord:
    source_root = Path(spec.workdir).resolve()
    source_root.mkdir(parents=True, exist_ok=True)
    workspace = _prepare_session_workspace(spec, source_root)
    workdir = Path(_as_string(workspace, "path"))
    baseline = _capture_workspace_baseline(workdir)
    _set_workspace_state_refs(workspace, baseline.files)
    binding = resolve_agent_binding(
        spec.agent_id,
        target_model=_as_string({"target_model": spec.target_model}, "target_model"),
        target_provider=_as_string({"target_provider": spec.target_provider}, "target_provider"),
        provider_base_url=spec.provider_base_url,
        provider_api_key_env=spec.provider_api_key_env,
        provider_wire_api=spec.provider_wire_api,
    )
    runtime_root: Path | None = None
    try:
        env = _build_opencode_environment(binding)
        runtime_root = _prepare_opencode_runtime(workspace, binding, spec, env)
        completed = _run_command_runner(
            command_runner,
            _build_opencode_command(
                binding,
                workdir,
                _render_codex_assignment_prompt(
                    assignment,
                    dispatch_packet=dispatch_packet,
                    context_resolution=context_resolution,
                ),
            ),
            cwd=workdir,
            env=env,
            timeout=spec.timeout_seconds,
            input_text=None,
            process_controller=process_controller,
            progress_line=_is_codex_native_progress_line,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return _failed_cli_session_record(
            spec, workspace, baseline.files, workdir, started_at, started_monotonic, exc,
            contract="opencode_run_json_v1",
            binding=binding,
        )
    finally:
        if runtime_root is not None:
            shutil.rmtree(runtime_root, ignore_errors=True)

    return _native_json_session_record(
        spec,
        assignment,
        workspace,
        workdir,
        baseline,
        started_at,
        started_monotonic,
        completed,
        binding,
        contract="opencode_run_json_v1",
        extractor=_extract_opencode_jsonl,
    )


def _native_json_session_record(
    spec: SessionSpec,
    assignment: AssignmentPacket,
    workspace: dict[str, Any],
    workdir: Path,
    baseline: WorkspaceBaseline,
    started_at: str,
    started_monotonic: float,
    completed: subprocess.CompletedProcess[str],
    binding: Any,
    *,
    contract: str,
    extractor: Callable[[str], tuple[dict[str, Any], dict[str, Any]]],
) -> SessionRecord:
    finished_at = _now()
    sensitive_values = _binding_secret_values(binding)
    stdout = _redact_native_text(_text_value(completed.stdout), sensitive_values)
    stderr = _redact_native_text(_text_value(completed.stderr), sensitive_values)
    native_logs = _persist_native_logs(
        workspace,
        stdout,
        stderr,
        sensitive_values=sensitive_values,
    )
    diff_metrics, diff_refs = _collect_workspace_delta(workdir, baseline)
    _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
    agent_metrics, agent_extraction = extractor(stdout)
    outcome_metrics = _merge_outcome_metrics(
        _merge_outcome_metrics(
            _base_outcome_metrics(
                wall_time_ms=max(1, int((time.monotonic() - started_monotonic) * 1000))
            ),
            diff_metrics,
        ),
        agent_metrics,
    )
    extraction = _empty_agent_extraction("native_stream_captured", [])
    extraction.update(
        {
            "contract": contract,
            "effective_model": binding.model,
            "effective_provider": binding.provider_id,
            "diff_refs": diff_refs,
            "outcome_metrics": outcome_metrics,
            "missing_fields": _missing_usage_fields(outcome_metrics),
        }
    )
    extraction["warnings"].extend(_string_list_value(agent_extraction.get("warnings")))
    extraction["parsed_fields"] = [
        "effective_model",
        "effective_provider",
        *_string_list_value(agent_extraction.get("parsed_fields")),
    ]
    for field in (
        "assistant_text",
        "native_event_stream_observed",
        "native_tool_events",
        "native_session_id",
        "provider_reported_models",
        "result_status",
        "review_status",
        "emitted_events",
        "artifacts",
        "verification",
        "native_log_refs",
        "mutation_proposal_refs",
        "control_intents",
        "context_request",
    ):
        if field in agent_extraction:
            extraction[field] = agent_extraction[field]
    result = None
    if completed.returncode == 0:
        result = ResultProposal(
            result_id=f"result-{spec.session_id}",
            assignment_id=assignment.assignment_id,
            agent_id=spec.agent_id,
            status=_string_value(agent_extraction.get("result_status"), default="completed"),
            effective_model=binding.model,
            effective_provider=binding.provider_id,
            emitted_events=_string_list_value(agent_extraction.get("emitted_events")),
            artifacts=_mapping_list_value(agent_extraction.get("artifacts")),
            outcome_metrics=outcome_metrics,
            verification=_mapping_value(agent_extraction.get("verification"), default={"status": "not_run"}),
            native_log_refs=_mapping_list_value(agent_extraction.get("native_log_refs")),
            mutation_proposal_refs=_string_list_value(agent_extraction.get("mutation_proposal_refs")),
            review_status=_string_or_none(agent_extraction.get("review_status")),
            control_intents=_list_value(agent_extraction.get("control_intents")),
            model_identity=_model_identity(binding, extraction),
            metric_provenance=_metric_provenance(
                spec.agent_id, binding.provider_id, outcome_metrics, extraction
            ),
            route_evidence=_session_route_evidence(
                spec.agent_id,
                binding.provider_id,
                outcome_metrics,
                extraction,
                _model_identity(binding, extraction),
            ),
        ).to_dict()
    return SessionRecord(
        session_id=spec.session_id,
        assignment_id=spec.assignment_id,
        agent_id=spec.agent_id,
        status="completed" if completed.returncode == 0 else "failed",
        started_at=started_at,
        finished_at=finished_at,
        exit={"code": completed.returncode, "reason": "completed" if completed.returncode == 0 else "failed"},
        native_logs=native_logs,
        diff_refs=diff_refs,
        artifacts=[],
        workspace=workspace,
        outcome_metrics=outcome_metrics,
        extraction=extraction,
        result_proposal=result,
    )


def _failed_cli_session_record(
    spec: SessionSpec,
    workspace: dict[str, Any],
    baseline_files: dict[str, str],
    workdir: Path,
    started_at: str,
    started_monotonic: float,
    exc: subprocess.TimeoutExpired | OSError,
    *,
    contract: str,
    binding: Any,
) -> SessionRecord:
    timed_out = isinstance(exc, subprocess.TimeoutExpired)
    reason = _timeout_reason(exc) if timed_out else "launch_failed"
    sensitive_values = _binding_secret_values(binding)
    warning = _redact_native_text(str(exc), sensitive_values)
    native_logs = _persist_native_logs(
        workspace,
        getattr(exc, "stdout", "") or "",
        getattr(exc, "stderr", "") or warning,
        sensitive_values=sensitive_values,
    )
    _set_workspace_state_refs(workspace, baseline_files, _snapshot_workspace_files(workdir))
    extraction = _empty_agent_extraction(reason, [warning])
    extraction["contract"] = contract
    return SessionRecord(
        session_id=spec.session_id,
        assignment_id=spec.assignment_id,
        agent_id=spec.agent_id,
        status="timed_out" if timed_out else "failed",
        started_at=started_at,
        finished_at=_now(),
        exit={"code": None if timed_out else 1, "reason": reason},
        native_logs=native_logs,
        diff_refs=[],
        artifacts=[],
        workspace=workspace,
        outcome_metrics=_base_outcome_metrics(
            wall_time_ms=max(1, int((time.monotonic() - started_monotonic) * 1000))
        ),
        extraction=extraction,
        result_proposal=None,
    )


def _build_claude_code_environment(binding: Any, workspace: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    if not binding.api_key_env or not env.get(binding.api_key_env):
        raise ProtocolError(
            f"Session provider_api_key_env is not set in the environment: {binding.api_key_env}"
        )
    home = Path(_as_string(workspace, "session_root")) / "claude-home"
    home.mkdir(parents=True, exist_ok=True)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["CLAUDE_CONFIG_DIR"] = str(home / ".claude")
    env["ANTHROPIC_BASE_URL"] = _as_string({"base_url": binding.base_url}, "base_url").rstrip("/").removesuffix("/v1")
    env["ANTHROPIC_API_KEY"] = env[binding.api_key_env]
    return env


def _build_claude_code_command(binding: Any) -> list[str]:
    return [
        "claude",
        "--print",
        "--bare",
        "--no-session-persistence",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "acceptEdits",
        "--model",
        binding.model,
    ]


def _build_gemini_environment(binding: Any) -> dict[str, str]:
    env = os.environ.copy()
    if not binding.api_key_env or not env.get(binding.api_key_env):
        raise ProtocolError(
            f"Session provider_api_key_env is not set in the environment: {binding.api_key_env}"
        )
    env["GEMINI_API_KEY"] = env[binding.api_key_env]
    env["GOOGLE_GEMINI_BASE_URL"] = _as_string({"base_url": binding.base_url}, "base_url")
    env["GEMINI_TELEMETRY_ENABLED"] = "false"
    env["NO_COLOR"] = "1"
    return env


def _prepare_gemini_home(workspace: dict[str, Any], env: dict[str, str]) -> Path:
    home = Path(_as_string(workspace, "session_root")) / "gemini-home"
    settings_path = home / ".gemini" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps({"security": {"auth": {"selectedType": "gemini-api-key"}}}),
        encoding="utf-8",
    )
    env["HOME"] = str(home)
    return home


def _cleanup_gemini_home(home: Path) -> None:
    shutil.rmtree(home, ignore_errors=True)


def _build_gemini_command(spec: SessionSpec, binding: Any, prompt: str) -> list[str]:
    approval_mode = {
        "read-only": "plan",
        "workspace-write": "auto_edit",
        "danger-full-access": "yolo",
    }[spec.sandbox_mode]
    return [
        "gemini",
        "--skip-trust",
        "--approval-mode",
        approval_mode,
        "--output-format",
        "stream-json",
        "--model",
        binding.model,
        "--prompt",
        prompt,
    ]


def _build_pi_environment(binding: Any) -> dict[str, str]:
    env = os.environ.copy()
    if not binding.api_key_env or not env.get(binding.api_key_env):
        raise ProtocolError(
            f"Session provider_api_key_env is not set in the environment: {binding.api_key_env}"
        )
    env["BUREAULESS_PI_API_KEY"] = env[binding.api_key_env]
    env["PI_TELEMETRY"] = "0"
    env["PI_OFFLINE"] = "1"
    return env


def _prepare_pi_config(workspace: dict[str, Any], binding: Any, env: dict[str, str]) -> Path:
    root = Path(_as_string(workspace, "session_root")) / "pi-runtime"
    agent_dir = root / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    agent_dir.joinpath("models.json").write_text(
        json.dumps(
            {
                "providers": {
                    "bureauless": {
                        "baseUrl": _pi_base_url(binding),
                        "api": "anthropic-messages" if binding.provider_id == "anthropic-compatible" else "openai-completions",
                        "apiKey": "$BUREAULESS_PI_API_KEY",
                        "models": [{"id": binding.model}],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    env["PI_CODING_AGENT_DIR"] = str(agent_dir)
    env["PI_CODING_AGENT_SESSION_DIR"] = str(root / "sessions")
    return root


def _pi_base_url(binding: Any) -> str:
    base_url = _as_string({"base_url": binding.base_url}, "base_url").rstrip("/")
    return base_url.removesuffix("/v1") if binding.provider_id == "anthropic-compatible" else base_url


def _build_pi_command(spec: SessionSpec, binding: Any, prompt: str) -> list[str]:
    tools = "read,grep,find,ls" if spec.sandbox_mode == "read-only" else "read,edit,write,grep,find,ls"
    if spec.sandbox_mode == "danger-full-access":
        tools = f"{tools},bash"
    return [
        "pi",
        "--print",
        "--mode",
        "json",
        "--provider",
        "bureauless",
        "--model",
        binding.model,
        "--no-session",
        "--no-approve",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--offline",
        "--tools",
        tools,
        prompt,
    ]


def _build_opencode_environment(binding: Any) -> dict[str, str]:
    env = os.environ.copy()
    if not binding.api_key_env or not env.get(binding.api_key_env):
        raise ProtocolError(
            f"Session provider_api_key_env is not set in the environment: {binding.api_key_env}"
        )
    env["BUREAULESS_OPENCODE_API_KEY"] = env[binding.api_key_env]
    env["OPENCODE_DISABLE_CLAUDE_CODE"] = "1"
    return env


def _prepare_opencode_runtime(
    workspace: dict[str, Any], binding: Any, spec: SessionSpec, env: dict[str, str]
) -> Path:
    root = Path(_as_string(workspace, "session_root")) / "opencode-runtime"
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    permissions: dict[str, str] = {
        "*": "deny",
        "read": "allow",
        "glob": "allow",
        "grep": "allow",
        "list": "allow",
    }
    if spec.sandbox_mode != "read-only":
        permissions["edit"] = "allow"
    if spec.sandbox_mode == "danger-full-access":
        permissions["bash"] = "allow"
    env["HOME"] = str(root / "home")
    env["OPENCODE_CONFIG_DIR"] = str(config_dir)
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps(
        {
            "$schema": "https://opencode.ai/config.json",
            "permission": permissions,
            "provider": {
                "bureauless": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "BureauLess",
                    "options": {
                        "baseURL": _as_string({"base_url": binding.base_url}, "base_url"),
                        "apiKey": "{env:BUREAULESS_OPENCODE_API_KEY}",
                    },
                    "models": {binding.model: {"name": binding.model}},
                }
            },
        }
    )
    return root


def _build_opencode_command(binding: Any, workdir: Path, prompt: str) -> list[str]:
    return [
        "opencode",
        "run",
        "--pure",
        "--format",
        "json",
        "--model",
        f"bureauless/{binding.model}",
        "--dir",
        str(workdir),
        prompt,
    ]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _render_codex_assignment_prompt(
    assignment: AssignmentPacket,
    *,
    dispatch_packet: DispatchPacket | None = None,
    context_resolution: dict[str, Any] | None = None,
) -> str:
    sections = [render_assignment_prompt(assignment)]
    workflow_nodes = assignment.visible_context.get("workflow_structure", {}).get(
        "nodes", []
    )
    awaits_independent_verification = (
        "patch_ready" in assignment.expected_events
        and isinstance(workflow_nodes, list)
        and any(
            isinstance(node, dict)
            and node.get("id") != assignment.node_id
            and any(
                isinstance(event, str) and "verification" in event
                for event in node.get("emits", [])
            )
            for node in workflow_nodes
        )
    )
    is_independent_verification = any(
        "verification" in event.casefold() for event in assignment.expected_events
    )
    if dispatch_packet is not None:
        sections.append(
            "\n".join(
                [
                    "## Dispatch Constraints",
                    f"Packet: {dispatch_packet.packet_id}",
                    f"Routing mode: {dispatch_packet.routing_decision.selected_mode}",
                    "Review constraints:",
                    yaml.safe_dump(
                        dispatch_packet.review_constraints,
                        sort_keys=False,
                    ).strip(),
                    "Turn report policy:",
                    yaml.safe_dump(
                        dispatch_packet.turn_report_policy,
                        sort_keys=False,
                    ).strip(),
                    "These constraints are authoritative for this session.",
                ]
            )
        )
    if context_resolution is not None:
        sections.append(
            "\n".join(
                [
                    "## Context Continuation",
                    "This is a resumed turn for the same assignment and workspace.",
                    "Use only this bounded resolution; do not infer unrelated ledger history.",
                    yaml.safe_dump(context_resolution, sort_keys=False).strip(),
                ]
            )
        )
    sections.append(
        "\n".join(
            [
                "## Output Contract",
                "Return a YAML object as your final answer.",
                "Required fields:",
                "- status: completed | blocked | context_requested",
                "- emitted_events: list of workflow events you actually satisfied",
                "- verification: object with at least status",
                *(
                    [
                        "- verification.final_independent_verification: "
                        f"{INDEPENDENT_VERIFICATION_PENDING}",
                        "  Use this exact marker after implementation self-checks; "
                        "do not claim final verification.",
                    ]
                    if awaits_independent_verification
                    else [
                        "- verification.status: passed",
                        "- verification.evidence: structured commands and observed results, "
                        "or reference a verification artifact",
                    ]
                    if is_independent_verification
                    else [
                        "- For status completed, set verification.status: passed only "
                        "after this assignment's checks pass.",
                    ]
                ),
                "Optional fields:",
                "- review_status",
                "- control_intents: omit or use the single workflow_mutation intent defined above",
                "- artifacts: list of objects with a path; do not use bare path strings",
                "When status is context_requested, include exactly one context_request object.",
                "Use plain YAML scalars only. Do not use markdown backticks or code fences inside values.",
                "Do not wrap the YAML in code fences.",
            ]
        )
    )
    return "\n\n".join(sections)


def _terminal_event_type(status: str) -> str | None:
    if status == "timed_out":
        return "worker_timeout"
    if status == "cancelled":
        return "assignment_cancelled"
    if status == "superseded":
        return "assignment_superseded"
    return None


def _extract_shell_dummy_output(
    spec: SessionSpec,
    assignment: AssignmentPacket,
    stdout: str,
) -> dict[str, Any]:
    stripped = stdout.strip()
    if not stripped:
        return _empty_shell_dummy_extraction("agent_does_not_emit_usage", [])

    if not _looks_structured(stripped):
        return _empty_shell_dummy_extraction("agent_does_not_emit_usage", [])

    extraction = _extract_structured_output(
        stripped,
        extracted_status="extracted",
        contract_name="shell_dummy_v1",
    )
    outcome_metrics = _mapping_value(extraction.get("outcome_metrics"))
    if (
        extraction["status"] == "extracted"
        and not any(field in outcome_metrics for field in ("input_tokens", "output_tokens", "total_tokens"))
    ):
        extraction["warnings"].append(
            f"{spec.agent_id} output for {assignment.assignment_id} omitted token usage fields"
        )
    return extraction


def _extract_structured_output(
    text: str,
    *,
    extracted_status: str,
    contract_name: str,
) -> dict[str, Any]:
    payload, parse_error = _parse_structured_yaml(text)
    if parse_error is not None:
        extraction = _empty_shell_dummy_extraction(
            "wrapper_failed_to_extract",
            [str(parse_error)],
        )
        extraction["contract"] = contract_name
        return extraction

    if not isinstance(payload, dict):
        extraction = _empty_shell_dummy_extraction(
            "wrapper_failed_to_extract",
            ["structured output must decode to a YAML object"],
        )
        extraction["contract"] = contract_name
        return extraction

    extraction = _empty_shell_dummy_extraction(extracted_status, [])
    extraction["contract"] = contract_name
    extraction["parsed_fields"] = []

    result_status = _string_or_none(payload.get("status"))
    if result_status is not None:
        extraction["result_status"] = result_status
        extraction["parsed_fields"].append("status")

    for field in ("effective_model", "effective_provider", "review_status"):
        value = _string_or_none(payload.get(field))
        if value is not None:
            extraction[field] = value
            extraction["parsed_fields"].append(field)

    emitted_events = _string_list_or_none(payload.get("emitted_events"))
    if emitted_events is not None:
        extraction["emitted_events"] = emitted_events
        extraction["parsed_fields"].append("emitted_events")

    artifacts = _mapping_list_or_none(payload.get("artifacts"))
    if artifacts is not None:
        extraction["artifacts"] = artifacts
        extraction["parsed_fields"].append("artifacts")

    verification = payload.get("verification")
    if isinstance(verification, dict):
        extraction["verification"] = verification
        extraction["parsed_fields"].append("verification")

    native_log_refs = _mapping_list_or_none(payload.get("native_log_refs"))
    if native_log_refs is not None:
        extraction["native_log_refs"] = native_log_refs
        extraction["parsed_fields"].append("native_log_refs")

    mutation_proposal_refs = _string_list_or_none(
        payload.get("mutation_proposal_refs")
    )
    if mutation_proposal_refs is not None:
        extraction["mutation_proposal_refs"] = mutation_proposal_refs
        extraction["parsed_fields"].append("mutation_proposal_refs")

    control_intents = _list_or_none(payload.get("control_intents"))
    if control_intents is not None:
        extraction["control_intents"] = control_intents
        extraction["parsed_fields"].append("control_intents")

    context_request = payload.get("context_request")
    if isinstance(context_request, dict):
        extraction["context_request"] = dict(context_request)
        extraction["parsed_fields"].append("context_request")

    diff_refs = _mapping_list_or_none(payload.get("diff_refs"))
    if diff_refs is not None:
        extraction["diff_refs"] = diff_refs
        extraction["parsed_fields"].append("diff_refs")

    changed_files = _string_list_or_none(payload.get("changed_files"))
    patch = payload.get("patch") if isinstance(payload.get("patch"), str) else None

    outcome_metrics = {}
    if isinstance(payload.get("outcome_metrics"), dict):
        outcome_metrics = dict(payload["outcome_metrics"])
        extraction["parsed_fields"].append("outcome_metrics")

    for field in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cost_usd",
        "usage_source",
        "cost_source",
        "cost_confidence",
        "usage_confidence",
        "changed_files_count",
        "patch_bytes",
    ):
        if field in payload:
            outcome_metrics[field] = payload[field]
            extraction["parsed_fields"].append(field)

    if "changed_files_count" not in outcome_metrics and changed_files is not None:
        outcome_metrics["changed_files_count"] = len(changed_files)
        extraction["parsed_fields"].append("changed_files")

    if "patch_bytes" not in outcome_metrics and patch is not None:
        outcome_metrics["patch_bytes"] = len(patch.encode("utf-8"))
        extraction["parsed_fields"].append("patch")

    if "total_tokens" not in outcome_metrics:
        input_tokens = outcome_metrics.get("input_tokens")
        output_tokens = outcome_metrics.get("output_tokens")
        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
            outcome_metrics["total_tokens"] = input_tokens + output_tokens
    if (
        "usage_source" not in outcome_metrics
        and any(field in outcome_metrics for field in ("input_tokens", "output_tokens", "total_tokens"))
    ):
        outcome_metrics["usage_source"] = "agent_reported"

    if patch is not None and not extraction["diff_refs"]:
        extraction["diff_refs"] = [
            {
                "kind": "inline_patch",
                "bytes": outcome_metrics.get("patch_bytes", len(patch.encode("utf-8"))),
            }
        ]
        extraction["parsed_fields"].append("diff_refs.inline_patch")

    extraction["outcome_metrics"] = outcome_metrics
    extraction["missing_fields"] = _missing_usage_fields(outcome_metrics)
    return extraction


def _parse_structured_yaml(text: str) -> tuple[dict[str, Any] | Any, yaml.YAMLError | None]:
    try:
        return yaml.safe_load(text), None
    except yaml.YAMLError as exc:
        sanitized = text.replace("`", "'")
        if sanitized != text:
            try:
                return yaml.safe_load(sanitized), None
            except yaml.YAMLError:
                pass
        return None, exc


def _prepare_session_workspace(spec: SessionSpec, source_root: Path) -> dict[str, Any]:
    if spec.reuse_workspace_path is not None:
        workspace_path = Path(spec.reuse_workspace_path).resolve()
        if not workspace_path.is_dir():
            raise ProtocolError("Continuation workspace does not exist")
        return {
            "mode": "continuation",
            "requested_mode": spec.isolation_mode,
            "source_root": str(source_root),
            "path": str(workspace_path),
            "session_root": str(workspace_path.parent),
            "cleanup_policy": spec.cleanup_policy,
            "retained_paths": [str(workspace_path)],
            "warnings": [],
        }
    session_root = source_root / ".bureauless" / "sessions" / spec.session_id
    session_root.mkdir(parents=True, exist_ok=True)
    workspace_path = session_root / "workspace"
    warnings: list[str] = []
    actual_mode = spec.isolation_mode

    if spec.isolation_mode == "worktree":
        worktree_result = _prepare_git_worktree(source_root, workspace_path)
        if worktree_result["ok"]:
            actual_mode = "worktree"
        else:
            warnings.extend(_string_list_value(worktree_result.get("warnings")))
            actual_mode = "copy"

    if actual_mode == "copy":
        _prepare_copy_workspace(source_root, workspace_path)

    return {
        "mode": actual_mode,
        "requested_mode": spec.isolation_mode,
        "source_root": str(source_root),
        "path": str(workspace_path),
        "session_root": str(session_root),
        "cleanup_policy": spec.cleanup_policy,
        "retained_paths": [str(workspace_path)],
        "warnings": warnings,
    }


def _prepare_copy_workspace(source_root: Path, workspace_path: Path) -> None:
    if workspace_path.exists():
        shutil.rmtree(workspace_path)
    shutil.copytree(
        source_root,
        workspace_path,
        ignore=shutil.ignore_patterns(".bureauless"),
    )


def _prepare_git_worktree(source_root: Path, workspace_path: Path) -> dict[str, Any]:
    if workspace_path.exists():
        shutil.rmtree(workspace_path)
    probe = probe_git_worktree(source_root)
    if not probe["ok"]:
        return probe
    env = git_environment(source_root)
    add = subprocess.run(
        ["git", "worktree", "add", "--detach", str(workspace_path), "HEAD"],
        cwd=source_root,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if add.returncode != 0:
        warning = add.stderr.strip() or add.stdout.strip() or "git worktree add failed"
        return {"ok": False, "warnings": [warning]}
    return {"ok": True, "warnings": []}


def _persist_native_logs(
    workspace: dict[str, Any],
    stdout: str | bytes,
    stderr: str | bytes,
    *,
    sensitive_values: tuple[str, ...] = (),
) -> dict[str, str]:
    session_root = Path(_as_string(workspace, "session_root"))
    logs_dir = session_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_dir / "stdout.log"
    stderr_path = logs_dir / "stderr.log"
    stdout_text = _redact_native_text(_text_value(stdout), sensitive_values)
    stderr_text = _redact_native_text(_text_value(stderr), sensitive_values)
    stdout_path.write_text(stdout_text, encoding="utf-8")
    stderr_path.write_text(stderr_text, encoding="utf-8")

    retained_paths = list(_string_list_value(workspace.get("retained_paths")))
    for path in (str(stdout_path), str(stderr_path)):
        if path not in retained_paths:
            retained_paths.append(path)
    workspace["retained_paths"] = retained_paths
    return {
        "stdout": stdout_text,
        "stderr": stderr_text,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def _binding_secret_values(binding: Any) -> tuple[str, ...]:
    api_key_env = _string_or_none(getattr(binding, "api_key_env", None))
    if api_key_env is None:
        return ()
    value = os.environ.get(api_key_env)
    return (value,) if value else ()


def _redact_native_text(text: str, sensitive_values: tuple[str, ...]) -> str:
    for value in sensitive_values:
        if value:
            text = text.replace(value, "<redacted>")
    return text


def _empty_shell_dummy_extraction(status: str, warnings: list[str]) -> dict[str, Any]:
    return {
        "contract": "shell_dummy_v1",
        "status": status,
        "warnings": warnings,
        "parsed_fields": [],
        "missing_fields": [
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cost_usd",
        ],
        "emitted_events": [],
        "artifacts": [],
        "verification": {"status": "not_run"},
        "native_log_refs": [],
        "diff_refs": [],
        "outcome_metrics": {},
    }


def _empty_agent_extraction(status: str, warnings: list[str]) -> dict[str, Any]:
    return {
        "contract": "agent_session_v1",
        "status": status,
        "warnings": warnings,
        "parsed_fields": [],
        "missing_fields": [
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cost_usd",
        ],
        "emitted_events": [],
        "artifacts": [],
        "verification": {"status": "not_run"},
        "native_log_refs": [],
        "diff_refs": [],
        "outcome_metrics": {},
    }


def _base_outcome_metrics(wall_time_ms: int) -> dict[str, Any]:
    return {
        "wall_time_ms": wall_time_ms,
        "changed_files_count": 0,
        "usage_source": "unavailable",
        "usage_confidence": "none",
        "cost_source": "agent_not_supported",
        "cost_confidence": "none",
    }


def _merge_outcome_metrics(
    base_metrics: dict[str, Any],
    extracted_metrics: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(base_metrics)
    merged.update(extracted_metrics)
    if (
        "total_tokens" not in merged
        and isinstance(merged.get("input_tokens"), int)
        and isinstance(merged.get("output_tokens"), int)
    ):
        merged["total_tokens"] = merged["input_tokens"] + merged["output_tokens"]
    return merged


def _model_identity(binding: Any, extraction: dict[str, Any]) -> dict[str, Any]:
    identity: dict[str, Any] = {"requested": binding.model}
    cli_reported = _string_or_none(extraction.get("cli_reported_model"))
    if cli_reported is not None:
        identity["cli_reported"] = cli_reported
    provider_reported = _string_list_value(extraction.get("provider_reported_models"))
    if provider_reported:
        identity["provider_reported"] = provider_reported
    independently_attested = _string_or_none(extraction.get("independently_attested_model"))
    if independently_attested is not None:
        identity["independently_attested"] = independently_attested
    return identity


def _metric_provenance(
    agent_id: str,
    provider_id: str,
    outcome_metrics: dict[str, Any],
    extraction: dict[str, Any],
) -> dict[str, Any]:
    return {
        "wall_time": "harness",
        "file_delta": "harness",
        "token_usage": outcome_metrics.get("usage_source", "unavailable"),
        "monetary_cost": outcome_metrics.get("cost_source", "unavailable"),
        "tool_timeline": "native_event_stream"
        if extraction.get("native_event_stream_observed")
        else "not_captured",
        "comparison_eligibility": dict(
            route_agent(agent_id, provider_id).comparison_eligibility
        ),
    }


def _session_route_evidence(
    agent_id: str,
    provider_id: str,
    outcome_metrics: dict[str, Any],
    extraction: dict[str, Any],
    model_identity: dict[str, Any],
) -> dict[str, Any]:
    evidence = route_agent(agent_id, provider_id).to_dict()
    usage_source = outcome_metrics.get("usage_source", "unavailable")
    cost_source = outcome_metrics.get("cost_source", "unavailable")
    if model_identity.get("independently_attested"):
        model_status = "verified"
    elif model_identity.get("provider_reported") or model_identity.get("cli_reported"):
        model_status = "observed"
    else:
        model_status = "requested_only"
    evidence["session_route_support"] = {
        "launch": "verified",
        "request_completed": "verified",
        "workspace_mutation": (
            "verified"
            if _int_value(outcome_metrics.get("changed_files_count")) > 0
            else "not_observed"
        ),
        "telemetry": (
            "verified"
            if usage_source == "provider_attributed"
            else "observed"
            if usage_source not in {"unavailable", "agent_not_supported"}
            else "unavailable"
        ),
        "model_identity": model_status,
        "cost_attribution": (
            "observed"
            if cost_source not in {"unavailable", "agent_not_supported"}
            else "unavailable"
        ),
        "permission_boundary": "not_verified",
        "native_event_stream": (
            "observed" if extraction.get("native_event_stream_observed") else "not_captured"
        ),
    }
    return evidence


def _build_codex_environment(binding: Any) -> dict[str, str]:
    env = os.environ.copy()
    if binding.api_key_env:
        value = env.get(binding.api_key_env)
        if value is None:
            raise ProtocolError(
                f"Session provider_api_key_env is not set in the environment: {binding.api_key_env}"
            )
        env["OPENAI_API_KEY"] = value
    return env


def _prepare_codex_home(
    workspace: dict[str, Any],
    binding: Any,
    env: dict[str, str],
) -> Path:
    session_root = Path(_as_string(workspace, "session_root"))
    codex_home = session_root / "codex-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    auth_payload = {"OPENAI_API_KEY": env.get("OPENAI_API_KEY")}
    (codex_home / "auth.json").write_text(
        json.dumps(auth_payload),
        encoding="utf-8",
    )
    env["CODEX_HOME"] = str(codex_home)
    return codex_home


def _cleanup_codex_home(codex_home: Path) -> None:
    shutil.rmtree(codex_home, ignore_errors=True)


def _toml_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value)


def _build_codex_command(spec: SessionSpec, binding: Any, workdir: Path) -> list[str]:
    command = [
        "codex",
        "--ask-for-approval",
        "never",
        "exec",
        "--json",
        "--ignore-user-config",
        "--ephemeral",
        "--cd",
        str(workdir),
        "--sandbox",
        spec.sandbox_mode,
        "--model",
        binding.model,
    ]
    for key, value in binding.codex_config_overrides.items():
        command.extend(["-c", f"{key}={_toml_literal(value)}"])
    return command


def _run_command_runner(
    command_runner: CommandRunner | None,
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    input_text: str,
    process_controller: _ProcessController | None = None,
    progress_line: Callable[[str], bool] | None = None,
) -> subprocess.CompletedProcess[str]:
    if command_runner is not None:
        return command_runner(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            input=input_text,
        )
    return _run_live_process(
        command,
        cwd=cwd,
        timeout=timeout,
        env=env,
        input_text=input_text,
        controller=process_controller,
        progress_line=progress_line,
    )


def _run_live_process(
    command: list[str],
    *,
    cwd: Path,
    timeout: float,
    env: dict[str, str] | None,
    input_text: str | None,
    controller: _ProcessController | None,
    progress_line: Callable[[str], bool] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_controller = controller or _ProcessController()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=os.name == "posix",
    )
    process_controller.attach(process)
    if progress_line is not None:
        return _wait_for_native_progress(
            process,
            command=command,
            input_text=input_text,
            idle_timeout=timeout,
            process_controller=process_controller,
            progress_line=progress_line,
        )
    try:
        stdout, stderr = process.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        process_controller.request(
            "timed_out",
            "timed_out",
            grace_seconds=0.25,
        )
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output=stdout,
            stderr=stderr,
        )
    return subprocess.CompletedProcess(
        args=command,
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _wait_for_native_progress(
    process: subprocess.Popen[str],
    *,
    command: list[str],
    input_text: str | None,
    idle_timeout: float,
    process_controller: _ProcessController,
    progress_line: Callable[[str], bool],
) -> subprocess.CompletedProcess[str]:
    outputs = {"stdout": [], "stderr": []}
    updates: queue.Queue[bool] = queue.Queue()

    def drain(stream: Any, output_name: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                outputs[output_name].append(line)
                if progress_line(line):
                    updates.put(True)
        finally:
            stream.close()
            updates.put(False)

    readers = [
        threading.Thread(target=drain, args=(process.stdout, "stdout"), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, "stderr"), daemon=True),
    ]
    for reader in readers:
        reader.start()
    if process.stdin is not None:
        try:
            process.stdin.write(input_text or "")
        except BrokenPipeError:
            pass
        finally:
            process.stdin.close()

    last_progress = time.monotonic()
    idle_timed_out = False
    while process.poll() is None:
        remaining = idle_timeout - (time.monotonic() - last_progress)
        if remaining <= 0:
            idle_timed_out = process_controller.request(
                "timed_out", "idle_timeout", grace_seconds=0.25
            )
            break
        try:
            if updates.get(timeout=remaining):
                last_progress = time.monotonic()
        except queue.Empty:
            if process.poll() is None:
                idle_timed_out = process_controller.request(
                    "timed_out", "idle_timeout", grace_seconds=0.25
                )
            break

    process.wait()
    for reader in readers:
        reader.join()
    stdout = "".join(outputs["stdout"])
    stderr = "".join(outputs["stderr"])
    if idle_timed_out:
        timeout_error = subprocess.TimeoutExpired(command, idle_timeout, output=stdout, stderr=stderr)
        timeout_error.reason = "idle_timeout"
        raise timeout_error
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _is_codex_native_progress_line(line: str) -> bool:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and isinstance(payload.get("type"), str)


def _timeout_reason(exc: subprocess.TimeoutExpired) -> str:
    reason = getattr(exc, "reason", "timed_out")
    return reason if isinstance(reason, str) and reason else "timed_out"


def _signal_process_group(process: subprocess.Popen[str], *, force: bool) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        elif force:
            process.kill()
        else:
            process.terminate()
    except ProcessLookupError:
        return


def _terminalize_live_record(
    record: SessionRecord,
    *,
    status: str,
    reason: str,
    forced: bool,
) -> SessionRecord:
    extraction = dict(record.extraction)
    warnings = list(_string_list_value(extraction.get("warnings")))
    warnings.append(f"live session terminated as {status}: {reason}")
    extraction["warnings"] = warnings
    audit_evidence = dict(record.audit_evidence)
    decision_points = [
        dict(point) for point in audit_evidence.get("decision_points", [])
    ]
    for point in decision_points:
        if point.get("decision_type") != "dispatch":
            continue
        later_outcome = dict(point.get("later_outcome") or {})
        later_outcome.update({"session_status": status, "exit_reason": reason})
        point["later_outcome"] = later_outcome
    audit_evidence["decision_points"] = decision_points
    return replace(
        record,
        status=status,
        finished_at=_now(),
        exit={
            "code": record.exit.get("code"),
            "reason": reason,
            "termination": {
                "status": status,
                "process_group": os.name == "posix",
                "forced": forced,
            },
        },
        extraction=extraction,
        result_proposal=None,
        audit_evidence=audit_evidence,
    )


def _context_terminal_record(
    record: SessionRecord,
    *,
    context_entry: dict[str, Any],
    lifecycle_events: list[dict[str, Any]],
    reason: str,
) -> SessionRecord:
    extraction = dict(record.extraction)
    extraction["context_requests"] = [context_entry]
    extraction["context_events"] = lifecycle_events
    metrics = dict(record.outcome_metrics)
    metrics.update(
        {
            "context_request_count": 1,
            "continuation_turn_count": 0,
            "added_context_tokens_estimate": 0,
        }
    )
    return replace(
        record,
        status="blocked",
        finished_at=_now(),
        exit={"code": record.exit.get("code"), "reason": reason},
        outcome_metrics=metrics,
        extraction=extraction,
        result_proposal=None,
    )


def _merge_context_continuation_records(
    first: SessionRecord,
    final: SessionRecord,
    *,
    context_entry: dict[str, Any],
    lifecycle_events: list[dict[str, Any]],
    added_tokens: int,
) -> SessionRecord:
    stdout = first.native_logs.get("stdout", "") + final.native_logs.get("stdout", "")
    stderr = first.native_logs.get("stderr", "") + final.native_logs.get("stderr", "")
    native_logs = _persist_native_logs(final.workspace, stdout, stderr)
    metrics = dict(final.outcome_metrics)
    for field in (
        "wall_time_ms",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "changed_files_count",
        "patch_bytes",
    ):
        first_value = first.outcome_metrics.get(field)
        final_value = final.outcome_metrics.get(field)
        if isinstance(first_value, int) or isinstance(final_value, int):
            metrics[field] = (
                first_value if isinstance(first_value, int) else 0
            ) + (final_value if isinstance(final_value, int) else 0)
    metrics.update(
        {
            "context_request_count": 1,
            "continuation_turn_count": 1,
            "granted_context_artifact_count": len(
                context_entry["resolution"].get("granted_artifacts", [])
            ),
            "added_context_tokens_estimate": added_tokens,
        }
    )
    extraction = dict(final.extraction)
    extraction["native_event_stream_observed"] = bool(
        first.extraction.get("native_event_stream_observed")
        or final.extraction.get("native_event_stream_observed")
    )
    extraction["native_tool_events"] = [
        *_mapping_list_value(first.extraction.get("native_tool_events")),
        *_mapping_list_value(final.extraction.get("native_tool_events")),
    ]
    extraction["context_requests"] = [context_entry]
    extraction["context_events"] = lifecycle_events
    extraction["continuation_status"] = "completed"
    return replace(
        final,
        session_id=first.session_id,
        started_at=first.started_at,
        native_logs=native_logs,
        diff_refs=[*first.diff_refs, *final.diff_refs],
        artifacts=[*first.artifacts, *final.artifacts],
        outcome_metrics=metrics,
        extraction=extraction,
    )


def _attach_dispatch_turn_report(
    record: SessionRecord,
    packet: DispatchPacket,
) -> SessionRecord:
    extraction = dict(record.extraction)
    tool_events = _mapping_list_value(extraction.get("native_tool_events"))
    stream_observed = extraction.get("native_event_stream_observed") is True
    telemetry_mode = "observed" if stream_observed else "degraded"
    compliance_reasons: list[str] = []
    if not stream_observed:
        compliance_status = "degraded"
        compliance_reasons.append("adapter_native_progress_stream_unavailable")
    elif packet.turn_report_policy.get("after_each_tool_call") and tool_events:
        compliance_status = "violated"
        compliance_reasons.append("native_events_aggregated_after_process_exit")
    else:
        compliance_status = "compliant"

    report_status = "completed" if record.status == "completed" else "blocked"
    summary = (
        f"Session {record.session_id} finished with status {record.status}; "
        f"observed {len(tool_events)} native tool events."
    )
    estimated_report_tokens = max(1, len(summary) // 4)
    max_report_tokens = packet.turn_report_policy.get("max_report_tokens")
    if isinstance(max_report_tokens, int) and estimated_report_tokens > max_report_tokens:
        compliance_status = "violated"
        compliance_reasons.append("report_token_budget_exceeded")
    report = load_turn_report(
        {
            "report_id": f"turn-{record.session_id}",
            "assignment_id": record.assignment_id,
            "agent_id": record.agent_id,
            "status": report_status,
            "tool_calls_since_last_report": len(tool_events),
            "summary": summary,
            "new_findings": [],
            "artifact_refs": record.artifacts,
            "blockers": (
                []
                if record.status == "completed"
                else [{"reason": record.exit.get("reason", record.status)}]
            ),
            "suggested_ledger_updates": [],
            "token_usage": {
                "input_tokens": _int_value(record.outcome_metrics.get("input_tokens")),
                "output_tokens": _int_value(record.outcome_metrics.get("output_tokens")),
            },
            "observed_at": record.finished_at,
            "telemetry_mode": telemetry_mode,
            "source_event_ids": [
                event["event_id"]
                for event in tool_events
                if isinstance(event.get("event_id"), str)
            ],
            "policy_compliance": {
                "status": compliance_status,
                "reasons": compliance_reasons,
                "policy": packet.turn_report_policy,
                "report_tokens_estimate": estimated_report_tokens,
            },
        }
    )
    for event in tool_events:
        event.setdefault("observed_at", record.finished_at)
        event.setdefault("timestamp_source", "native" if event.get("native_timestamp") else "wrapper_capture")
    extraction["native_tool_events"] = tool_events
    extraction["turn_reports"] = [report.to_dict()]
    metrics = dict(record.outcome_metrics)
    metrics["observed_tool_call_count"] = len(tool_events)
    metrics["turn_report_telemetry_mode"] = telemetry_mode
    metrics["turn_report_policy_status"] = compliance_status
    return replace(record, extraction=extraction, outcome_metrics=metrics)


def _int_value(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _collect_workspace_diff(workdir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    changed_files_count = 0
    patch_bytes = 0
    diff_refs: list[dict[str, Any]] = []

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workdir,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode == 0:
        changed_files_count = len([line for line in status.stdout.splitlines() if line.strip()])

    patch = subprocess.run(
        ["git", "diff", "--binary", "--no-ext-diff"],
        cwd=workdir,
        check=False,
        capture_output=True,
        text=True,
    )
    if patch.returncode == 0 and patch.stdout:
        patch_bytes = len(patch.stdout.encode("utf-8"))
        diff_refs.append({"kind": "inline_patch", "bytes": patch_bytes})

    metrics: dict[str, Any] = {"changed_files_count": changed_files_count}
    if patch_bytes:
        metrics["patch_bytes"] = patch_bytes
    return metrics, diff_refs


@dataclass(frozen=True)
class WorkspaceBaseline:
    files: dict[str, str]
    git_dirty: bool


def _capture_workspace_baseline(workdir: Path) -> WorkspaceBaseline:
    return WorkspaceBaseline(
        files=_snapshot_workspace_files(workdir),
        git_dirty=_workspace_git_dirty(workdir),
    )


def _set_workspace_state_refs(
    workspace: dict[str, Any],
    pre_files: dict[str, str],
    post_files: dict[str, str] | None = None,
) -> None:
    workspace["pre_state_ref"] = _workspace_state_ref(pre_files)
    workspace["post_state_ref"] = _workspace_state_ref(post_files or pre_files)


def _workspace_state_ref(files: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path, file_hash in sorted(files.items()):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("utf-8"))
        digest.update(b"\0")
    return f"workspace:{digest.hexdigest()}"


def _collect_workspace_delta(
    workdir: Path,
    baseline: WorkspaceBaseline,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    current_files = _snapshot_workspace_files(workdir)
    changed_files = {
        path
        for path in set(baseline.files) | set(current_files)
        if baseline.files.get(path) != current_files.get(path)
    }
    metrics: dict[str, Any] = {"changed_files_count": len(changed_files)}
    if baseline.git_dirty:
        return metrics, []

    diff_metrics, diff_refs = _collect_workspace_diff(workdir)
    patch_bytes = diff_metrics.get("patch_bytes", 0)

    added_files = sorted(set(current_files) - set(baseline.files))
    if added_files:
        added_patch_bytes = _collect_untracked_patch_bytes(workdir, added_files)
        patch_bytes += added_patch_bytes

    if patch_bytes:
        metrics["patch_bytes"] = patch_bytes
        if not diff_refs:
            diff_refs = [{"kind": "inline_patch", "bytes": patch_bytes}]
        elif added_files:
            diff_refs = [{"kind": "inline_patch", "bytes": patch_bytes}]
    return metrics, diff_refs


def _extract_opencode_jsonl(stdout: str) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics: dict[str, Any] = {}
    extraction: dict[str, Any] = {
        "warnings": [],
        "parsed_fields": [],
        "native_event_stream_observed": False,
        "native_tool_events": [],
    }
    assistant_parts: list[str] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            extraction["warnings"].append("opencode_jsonl_line_unparseable")
            continue
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            continue
        extraction["native_event_stream_observed"] = True
        event_type = event["type"]
        part = _mapping_value(event.get("part"))
        if event_type == "text":
            text = _string_or_none(event.get("text")) or _string_or_none(part.get("text"))
            if text:
                assistant_parts.append(text)
        if event_type == "tool_use":
            extraction["native_tool_events"].append(
                {
                    "event_id": _string_or_none(event.get("tool_call_id"))
                    or _string_or_none(part.get("callID"))
                    or f"native-tool-{len(extraction['native_tool_events']) + 1}",
                    "event_type": event_type,
                    "tool_name": _string_or_none(event.get("tool_name"))
                    or _string_or_none(part.get("tool")),
                }
            )
        for value in _mapping_values(event):
            tokens = _mapping_value(value.get("tokens"))
            for source, target in (
                ("input", "input_tokens"),
                ("output", "output_tokens"),
                ("reasoning", "reasoning_output_tokens"),
                ("total", "total_tokens"),
            ):
                if isinstance(tokens.get(source), int):
                    metrics[target] = tokens[source]
                    extraction["parsed_fields"].append(f"tokens.{source}")
            cache = _mapping_value(tokens.get("cache"))
            if isinstance(cache.get("read"), int):
                metrics["cached_input_tokens"] = cache["read"]
                extraction["parsed_fields"].append("tokens.cache.read")
            if isinstance(cache.get("write"), int):
                metrics["cache_creation_input_tokens"] = cache["write"]
                extraction["parsed_fields"].append("tokens.cache.write")
    if "input_tokens" in metrics or "output_tokens" in metrics:
        metrics.update({"usage_source": "agent_reported", "usage_confidence": "high"})
    if assistant_parts:
        text = "".join(assistant_parts)
        extraction["assistant_text"] = text
        extraction["parsed_fields"].append("text")
        if _looks_structured(text.strip()):
            structured = _extract_structured_output(text.strip(), extracted_status="extracted", contract_name="opencode_run_json_v1")
            extraction["warnings"].extend(_string_list_value(structured.get("warnings")))
            extraction["parsed_fields"].extend(_string_list_value(structured.get("parsed_fields")))
            for field in ("result_status", "review_status", "emitted_events", "artifacts", "verification", "native_log_refs", "mutation_proposal_refs", "control_intents", "context_request"):
                if field in structured:
                    extraction[field] = structured[field]
            for key, value in _mapping_value(structured.get("outcome_metrics")).items():
                metrics.setdefault(key, value)
    extraction["parsed_fields"].append("native_tool_events")
    return metrics, extraction


def _mapping_values(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_mapping_values(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_mapping_values(child))
    return found


def _extract_pi_jsonl(stdout: str) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics: dict[str, Any] = {}
    extraction: dict[str, Any] = {
        "warnings": [],
        "parsed_fields": [],
        "native_event_stream_observed": False,
        "native_tool_events": [],
    }
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            extraction["warnings"].append("pi_jsonl_line_unparseable")
            continue
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            continue
        extraction["native_event_stream_observed"] = True
        if event["type"] == "session" and isinstance(event.get("id"), str):
            extraction["native_session_id"] = event["id"]
        if event["type"] in {"tool_execution_start", "tool_execution_end"}:
            extraction["native_tool_events"].append(
                {
                    "event_id": _string_or_none(event.get("toolCallId"))
                    or f"native-tool-{len(extraction['native_tool_events']) + 1}",
                    "event_type": event["type"],
                    "tool_name": _string_or_none(event.get("toolName")),
                }
            )
        if event["type"] != "message_end":
            continue
        message = _mapping_value(event.get("message"))
        if message.get("role") != "assistant":
            continue
        text = "".join(
            part.get("text", "")
            for part in _list_value(message.get("content"))
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
        )
        if text:
            extraction["assistant_text"] = text
            extraction["parsed_fields"].append("message.content.text")
        usage = _mapping_value(message.get("usage"))
        for source, target in (
            ("input", "input_tokens"),
            ("output", "output_tokens"),
            ("cacheRead", "cached_input_tokens"),
            ("cacheWrite", "cache_creation_input_tokens"),
            ("totalTokens", "total_tokens"),
        ):
            if isinstance(usage.get(source), int):
                metrics[target] = usage[source]
                extraction["parsed_fields"].append(f"message.usage.{source}")
        cost = _mapping_value(usage.get("cost")).get("total")
        if isinstance(cost, (int, float)):
            metrics.update({"cost_usd": cost, "cost_source": "agent_reported", "cost_confidence": "high"})
            extraction["parsed_fields"].append("message.usage.cost.total")
    if "input_tokens" in metrics or "output_tokens" in metrics:
        metrics.update({"usage_source": "agent_reported", "usage_confidence": "high"})
    text = _string_or_none(extraction.get("assistant_text"))
    if text and _looks_structured(text.strip()):
        structured = _extract_structured_output(text.strip(), extracted_status="extracted", contract_name="pi_json_v1")
        extraction["warnings"].extend(_string_list_value(structured.get("warnings")))
        extraction["parsed_fields"].extend(_string_list_value(structured.get("parsed_fields")))
        for field in ("result_status", "review_status", "emitted_events", "artifacts", "verification", "native_log_refs", "mutation_proposal_refs", "control_intents", "context_request"):
            if field in structured:
                extraction[field] = structured[field]
        for key, value in _mapping_value(structured.get("outcome_metrics")).items():
            metrics.setdefault(key, value)
    extraction["parsed_fields"].append("native_tool_events")
    return metrics, extraction


def _extract_gemini_jsonl(stdout: str) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics: dict[str, Any] = {}
    extraction: dict[str, Any] = {
        "warnings": [],
        "parsed_fields": [],
        "native_event_stream_observed": False,
        "native_tool_events": [],
    }
    assistant_parts: list[str] = []
    provider_reported_models: list[str] = []

    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            extraction["warnings"].append("gemini_jsonl_line_unparseable")
            continue
        if not isinstance(payload, dict):
            continue
        event_type = _string_or_none(payload.get("type"))
        if event_type is None:
            continue
        extraction["native_event_stream_observed"] = True
        session_id = _string_or_none(payload.get("session_id"))
        if session_id is not None:
            extraction["native_session_id"] = session_id
        if event_type == "message" and payload.get("role") == "assistant":
            content = _string_or_none(payload.get("content"))
            if content is not None:
                assistant_parts.append(content)
        if event_type in {"tool_use", "tool_result"}:
            extraction["native_tool_events"].append(
                {
                    "event_id": _string_or_none(payload.get("tool_id"))
                    or f"native-tool-{len(extraction['native_tool_events']) + 1}",
                    "event_type": event_type,
                    "tool_name": _string_or_none(payload.get("tool_name")),
                    "native_timestamp": _string_or_none(payload.get("timestamp")),
                }
            )
        if event_type == "error":
            extraction["warnings"].append("gemini_native_error_event")
        if event_type != "result":
            continue
        stats = _mapping_value(payload.get("stats"))
        for source, target in (
            ("input_tokens", "input_tokens"),
            ("output_tokens", "output_tokens"),
            ("cached", "cached_input_tokens"),
            ("total_tokens", "total_tokens"),
            ("duration_ms", "agent_duration_ms"),
            ("tool_calls", "agent_tool_calls"),
        ):
            if isinstance(stats.get(source), int):
                metrics[target] = stats[source]
                extraction["parsed_fields"].append(f"stats.{source}")
        models = _mapping_value(stats.get("models"))
        provider_reported_models = sorted(
            model for model in models if isinstance(model, str) and model
        )

    if "input_tokens" in metrics or "output_tokens" in metrics:
        metrics["usage_source"] = "agent_reported"
        metrics["usage_confidence"] = "high"
    if assistant_parts:
        assistant_text = "".join(assistant_parts)
        extraction["assistant_text"] = assistant_text
        extraction["parsed_fields"].append("message.assistant.content")
        if _looks_structured(assistant_text.strip()):
            structured = _extract_structured_output(
                assistant_text.strip(),
                extracted_status="extracted",
                contract_name="gemini_stream_json_v1",
            )
            extraction["warnings"].extend(_string_list_value(structured.get("warnings")))
            extraction["parsed_fields"].extend(
                _string_list_value(structured.get("parsed_fields"))
            )
            for field in (
                "result_status",
                "review_status",
                "emitted_events",
                "artifacts",
                "verification",
                "native_log_refs",
                "mutation_proposal_refs",
                "control_intents",
                "context_request",
            ):
                if field in structured:
                    extraction[field] = structured[field]
            for key, value in _mapping_value(structured.get("outcome_metrics")).items():
                metrics.setdefault(key, value)
    if provider_reported_models:
        extraction["provider_reported_models"] = provider_reported_models
        extraction["parsed_fields"].append("result.stats.models")
    extraction["parsed_fields"].append("native_tool_events")
    return metrics, extraction


def _extract_codex_jsonl(stdout: str) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics: dict[str, Any] = {}
    extraction: dict[str, Any] = {"warnings": [], "parsed_fields": []}
    assistant_text: str | None = None
    native_tool_events: list[dict[str, Any]] = []
    native_event_stream_observed = False

    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            extraction["warnings"].append("codex_jsonl_line_unparseable")
            continue
        if not isinstance(payload, dict):
            continue

        payload_type = _string_or_none(payload.get("type"))
        if payload_type is not None:
            native_event_stream_observed = True

        item = payload.get("item")
        if payload_type == "item.completed" and isinstance(item, dict) and item.get("type") in {
            "command_execution",
            "mcp_tool_call",
            "web_search",
            "file_change",
            "tool_call",
        }:
            event_id = _string_or_none(item.get("id")) or f"native-tool-{len(native_tool_events) + 1}"
            native_tool_events.append(
                {
                    "event_id": event_id,
                    "event_type": payload_type or "item.observed",
                    "item_type": item["type"],
                    "native_timestamp": _string_or_none(payload.get("timestamp")),
                }
            )
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = _string_or_none(item.get("text"))
            if text is not None:
                assistant_text = text

        if payload.get("type") != "turn.completed":
            continue
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            continue
        if isinstance(usage.get("input_tokens"), int):
            metrics["input_tokens"] = usage["input_tokens"]
            extraction["parsed_fields"].append("usage.input_tokens")
        if isinstance(usage.get("output_tokens"), int):
            metrics["output_tokens"] = usage["output_tokens"]
            extraction["parsed_fields"].append("usage.output_tokens")
        if isinstance(usage.get("cached_input_tokens"), int):
            metrics["cached_input_tokens"] = usage["cached_input_tokens"]
            extraction["parsed_fields"].append("usage.cached_input_tokens")
        if isinstance(usage.get("reasoning_output_tokens"), int):
            metrics["reasoning_output_tokens"] = usage["reasoning_output_tokens"]
            extraction["parsed_fields"].append("usage.reasoning_output_tokens")

    if "input_tokens" in metrics or "output_tokens" in metrics:
        metrics["usage_source"] = "agent_reported"
        metrics["usage_confidence"] = "high"
    extraction["native_event_stream_observed"] = native_event_stream_observed
    extraction["native_tool_events"] = native_tool_events
    extraction["parsed_fields"].append("native_tool_events")
    if assistant_text is not None:
        extraction["assistant_text"] = assistant_text
        extraction["parsed_fields"].append("item.agent_message.text")
        if _looks_structured(assistant_text.strip()):
            structured = _extract_structured_output(
                assistant_text.strip(),
                extracted_status="extracted",
                contract_name="codex_exec_v1",
            )
            extraction["warnings"].extend(_string_list_value(structured.get("warnings")))
            extraction["parsed_fields"].extend(_string_list_value(structured.get("parsed_fields")))
            for field in (
                "result_status",
                "review_status",
                "emitted_events",
                "artifacts",
                "verification",
                "native_log_refs",
                "mutation_proposal_refs",
                "control_intents",
                "context_request",
            ):
                if field in structured:
                    extraction[field] = structured[field]
            structured_metrics = _mapping_value(structured.get("outcome_metrics"))
            if structured_metrics:
                extraction["outcome_metrics"] = structured_metrics
                for key, value in structured_metrics.items():
                    metrics.setdefault(key, value)
    return metrics, extraction


def _extract_claude_json(
    stdout: str,
    *,
    contract_name: str = "claude_print_json_v1",
) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics: dict[str, Any] = {}
    extraction: dict[str, Any] = {
        "warnings": [],
        "parsed_fields": [],
        "native_event_stream_observed": False,
        "native_tool_events": [],
    }
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        extraction["warnings"].append("claude_json_unparseable")
        return metrics, extraction
    if not isinstance(payload, dict):
        extraction["warnings"].append("claude_json_not_object")
        return metrics, extraction

    usage = _mapping_value(payload.get("usage"))
    for field in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        if isinstance(usage.get(field), int):
            metrics[field] = usage[field]
            extraction["parsed_fields"].append(f"usage.{field}")
    if isinstance(payload.get("total_cost_usd"), (int, float)):
        metrics.update(
            {
                "cost_usd": payload["total_cost_usd"],
                "cost_source": "agent_reported",
                "cost_confidence": "high",
            }
        )
        extraction["parsed_fields"].append("total_cost_usd")
    if "input_tokens" in metrics or "output_tokens" in metrics:
        metrics["usage_source"] = "agent_reported"
        metrics["usage_confidence"] = "high"

    result = _string_or_none(payload.get("result"))
    if result is not None:
        extraction["assistant_text"] = result
        extraction["parsed_fields"].append("result")
        if _looks_structured(result.strip()):
            structured = _extract_structured_output(
                result.strip(),
                extracted_status="extracted",
                contract_name=contract_name,
            )
            extraction["warnings"].extend(_string_list_value(structured.get("warnings")))
            extraction["parsed_fields"].extend(_string_list_value(structured.get("parsed_fields")))
            for field in (
                "result_status",
                "review_status",
                "emitted_events",
                "artifacts",
                "verification",
                "native_log_refs",
                "mutation_proposal_refs",
                "control_intents",
                "context_request",
            ):
                if field in structured:
                    extraction[field] = structured[field]
            for key, value in _mapping_value(structured.get("outcome_metrics")).items():
                metrics.setdefault(key, value)
    return metrics, extraction


def _extract_claude_stream_json(stdout: str) -> tuple[dict[str, Any], dict[str, Any]]:
    result_payload: dict[str, Any] | None = None
    native_tool_events: list[dict[str, Any]] = []
    warnings: list[str] = []
    event_stream_observed = False
    for line_number, line in enumerate(stdout.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            warnings.append("claude_jsonl_line_unparseable")
            continue
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            continue
        event_stream_observed = True
        event_type = event["type"]
        if event_type == "result":
            result_payload = event
            continue
        message = _mapping_value(event.get("message"))
        content = _list_value(message.get("content"))
        if event_type == "assistant":
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                native_tool_events.append(
                    {
                        "event_id": _string_or_none(block.get("id"))
                        or f"native-tool-{len(native_tool_events) + 1}",
                        "event_type": "tool_use",
                        "tool_name": _string_or_none(block.get("name")),
                        "source_ref": f"stdout:{line_number}",
                    }
                )
        if event_type == "user":
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                native_tool_events.append(
                    {
                        "event_id": _string_or_none(block.get("tool_use_id"))
                        or f"native-tool-{len(native_tool_events) + 1}",
                        "event_type": "tool_result",
                        "tool_name": None,
                        "is_error": bool(block.get("is_error", False)),
                        "source_ref": f"stdout:{line_number}",
                    }
                )
    if result_payload is None:
        metrics: dict[str, Any] = {}
        extraction: dict[str, Any] = {
            "warnings": [*warnings, "claude_result_event_missing"],
            "parsed_fields": ["native_tool_events"],
            "native_event_stream_observed": event_stream_observed,
            "native_tool_events": native_tool_events,
        }
        return metrics, extraction
    metrics, extraction = _extract_claude_json(
        json.dumps(result_payload), contract_name="claude_stream_json_v1"
    )
    extraction["warnings"] = [*warnings, *_string_list_value(extraction.get("warnings"))]
    extraction["native_event_stream_observed"] = event_stream_observed
    extraction["native_tool_events"] = native_tool_events
    extraction["parsed_fields"].append("native_tool_events")
    return metrics, extraction


def _snapshot_workspace_files(workdir: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for root, dirnames, filenames in os.walk(workdir):
        root_path = Path(root)
        rel_root = root_path.relative_to(workdir)
        dirnames[:] = [
            name
            for name in dirnames
            if (rel_root / name).as_posix() not in {".git", ".bureauless"}
        ]
        for filename in filenames:
            rel_path = (rel_root / filename).as_posix()
            if rel_path.startswith(".git/") or rel_path.startswith(".bureauless/"):
                continue
            file_path = root_path / filename
            if file_path.is_symlink() or not file_path.is_file():
                continue
            snapshot[rel_path] = sha256_file(file_path)
    return snapshot


def _workspace_git_dirty(workdir: Path) -> bool:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workdir,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        return False
    return any(line.strip() for line in status.stdout.splitlines())


def _collect_untracked_patch_bytes(workdir: Path, added_files: list[str]) -> int:
    total = 0
    for rel_path in added_files:
        file_path = workdir / rel_path
        diff = subprocess.run(
            ["git", "diff", "--no-index", "--binary", "--no-ext-diff", "--", "/dev/null", str(file_path)],
            cwd=workdir,
            check=False,
            capture_output=True,
            text=False,
        )
        if diff.stdout:
            total += len(diff.stdout)
    return total


def _missing_usage_fields(outcome_metrics: dict[str, Any]) -> list[str]:
    missing = []
    for field in ("input_tokens", "output_tokens", "total_tokens", "cost_usd"):
        if field not in outcome_metrics:
            missing.append(field)
    return missing


def _looks_structured(text: str) -> bool:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first_line:
        return False
    if first_line.startswith("{"):
        return True
    key, separator, remainder = first_line.partition(":")
    return bool(separator and key and remainder is not None)


def _unprepared_workspace_record(spec: SessionSpec) -> dict[str, Any]:
    source_root = str(Path(spec.workdir).resolve())
    return {
        "mode": "none",
        "requested_mode": spec.isolation_mode,
        "source_root": source_root,
        "path": source_root,
        "session_root": "",
        "cleanup_policy": spec.cleanup_policy,
        "retained_paths": [],
        "warnings": [],
    }


def _packaging_roots(record: SessionRecord, artifact_root: Path | None) -> tuple[Path, Path]:
    if artifact_root is not None:
        root = artifact_root.resolve()
        return root, root
    session_root = _string_or_none(record.workspace.get("session_root"))
    workspace_path = _string_or_none(record.workspace.get("path"))
    if session_root is not None and workspace_path is not None:
        return Path(session_root).resolve(), Path(workspace_path).resolve()
    workspace_path = _string_or_none(record.workspace.get("path"))
    if workspace_path is not None:
        root = Path(workspace_path).resolve()
        return root, root
    source_root = _string_or_none(record.workspace.get("source_root"))
    if source_root is not None:
        root = Path(source_root).resolve()
        return root, root
    raise ProtocolError("Packaging requires an artifact_root or a session workspace path")


def _accepted_workspace_ref_for_node(ledger: Any, node_id: str) -> str | None:
    projection = ledger.projection if hasattr(ledger, "projection") else {}
    projected_cursor = _string_or_none(projection.get("through_event_id"))
    event_log = getattr(ledger, "event_log", [])
    last_event_id = (
        _string_or_none(event_log[-1].get("event_id")) if event_log else None
    )
    projected = _string_or_none(projection.get("accepted_workspace_ref"))
    if projected is not None and projected_cursor == last_event_id:
        latest_node_event = next(
            (
                event
                for event in reversed(event_log)
                if event.get("event_type") == "node_outcome_decided"
                and event.get("node_id") == node_id
                and event.get("disposition") in {"accepted", "partially_accepted"}
            ),
            None,
        )
        if latest_node_event is not None:
            post_state_ref = _string_or_none(latest_node_event.get("post_state_ref"))
            if post_state_ref is not None:
                return post_state_ref
    for event in reversed(event_log):
        if event.get("event_type") != "node_outcome_decided":
            continue
        if event.get("node_id") != node_id:
            continue
        if event.get("disposition") not in {"accepted", "partially_accepted"}:
            continue
        post_state_ref = _string_or_none(event.get("post_state_ref"))
        if post_state_ref is not None:
            return post_state_ref
    return None


def _normalize_packaged_artifact(
    artifact: dict[str, Any],
    *,
    package_root: Path,
    workspace_root: Path,
    source_event: str,
    created_by: str,
    fallback_id: str,
) -> dict[str, Any] | None:
    artifact_path = _string_or_none(artifact.get("path"))
    if artifact_path is None:
        return None
    resolved_path, relative_path = _resolve_artifact_path(
        package_root,
        artifact_path,
        candidate_roots=[workspace_root, package_root],
    )
    if not resolved_path.exists():
        raise ProtocolError(f"Session artifact file is missing: {relative_path}")

    actual_hash = sha256_file(resolved_path)
    recorded_hash = _string_or_none(artifact.get("sha256"))
    if recorded_hash is not None and recorded_hash != actual_hash:
        raise ProtocolError(f"Session artifact hash does not match file contents: {relative_path}")

    normalized = {
        "artifact_id": _string_or_none(artifact.get("artifact_id")) or fallback_id,
        "path": relative_path,
        "sha256": actual_hash,
        "created_by": _string_or_none(artifact.get("created_by")) or created_by,
        "source_event": source_event,
        "mutable": False,
    }
    artifact_type = _string_or_none(artifact.get("artifact_type"))
    if artifact_type is not None:
        normalized["artifact_type"] = artifact_type
    return normalized


def _package_native_log_refs(
    record: SessionRecord,
    package_root: Path,
    source_event: str,
    result_id: str,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for kind in ("stdout", "stderr"):
        path_key = f"{kind}_path"
        native_path = _string_or_none(record.native_logs.get(path_key))
        if native_path is None:
            continue
        resolved_path, relative_path = _resolve_artifact_path(package_root, native_path)
        if not resolved_path.exists():
            raise ProtocolError(f"Native log file is missing: {relative_path}")
        refs.append(
            {
                "artifact_id": f"artifact-{result_id}-native-{kind}",
                "kind": kind,
                "path": relative_path,
                "sha256": sha256_file(resolved_path),
                "created_by": record.agent_id,
                "source_event": source_event,
                "mutable": False,
            }
        )
    return refs


def _package_provider_usage_capture(
    record: SessionRecord,
    result: ResultProposal,
    *,
    package_root: Path,
    workspace_root: Path,
    source_event: str,
) -> dict[str, Any] | None:
    capture = _load_provider_usage_capture_for_record(record, result_id=result.result_id)
    if capture is None:
        return None
    artifact_path = (
        package_root / "artifacts" / "provider-usage" / f"{result.result_id}.provider-usage.yaml"
    )
    written = write_provider_usage_capture_artifact(
        artifact_path,
        capture,
        created_by="harness",
        source_event=source_event,
    )
    return _normalize_packaged_artifact(
        written,
        package_root=package_root,
        workspace_root=workspace_root,
        source_event=source_event,
        created_by="harness",
        fallback_id=written["artifact_id"],
    )


def _load_provider_usage_capture_for_record(
    record: SessionRecord,
    *,
    result_id: str,
) -> ProviderUsageCapture | None:
    capture_data = record.extraction.get("provider_usage_capture")
    if not isinstance(capture_data, dict):
        return None
    capture = load_provider_usage_capture(capture_data)
    if capture.assignment_id != record.assignment_id or capture.session_id != record.session_id:
        raise ProtocolError("Provider usage capture does not match the session being packaged")
    if capture.result_id != result_id:
        capture = replace(capture, result_id=result_id)
    return capture


def _resolve_artifact_path(
    root: Path,
    artifact_path: str,
    candidate_roots: list[Path] | None = None,
) -> tuple[Path, str]:
    candidate = Path(artifact_path)
    resolved_path: Path | None = None
    if candidate.is_absolute():
        resolved_path = candidate.resolve()
    else:
        for candidate_root in candidate_roots or [root]:
            trial = (candidate_root / candidate).resolve()
            try:
                trial.relative_to(root)
            except ValueError:
                continue
            if trial.exists():
                resolved_path = trial
                break
        if resolved_path is None:
            resolved_path = ((candidate_roots or [root])[0] / candidate).resolve()
    try:
        relative_path = str(resolved_path.relative_to(root))
    except ValueError as exc:
        raise ProtocolError(f"Artifact path escapes packaging root: {artifact_path}") from exc
    return resolved_path, relative_path


def _as_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ProtocolError(f"Session field {key!r} must be a string")
    return value


def _as_mapping(
    data: dict[str, Any],
    key: str,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = data.get(key, default)
    if not isinstance(value, dict):
        raise ProtocolError(f"Session field {key!r} must be an object")
    return value


def _as_mapping_list(
    data: dict[str, Any],
    key: str,
    default: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ProtocolError(f"Session field {key!r} must be a list of objects")
    return value


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_bool(data: dict[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ProtocolError(f"Session field {key!r} must be boolean")
    return value


def _text_value(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return ""


def _string_value(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _string_list_value(value: Any) -> list[str]:
    return value if isinstance(value, list) and all(isinstance(item, str) for item in value) else []


def _string_list_or_none(value: Any) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    return None


def _mapping_list_or_none(value: Any) -> list[dict[str, Any]] | None:
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    return None


def _list_or_none(value: Any) -> list[Any] | None:
    return value if isinstance(value, list) else None


def _mapping_value(value: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return default or {}


def _mapping_list_value(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) and all(isinstance(item, dict) for item in value) else []


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
