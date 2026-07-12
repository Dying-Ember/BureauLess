from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import signal
import shutil
import subprocess
import threading
import time
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from uuid import uuid4

import yaml

from ..agents import resolve_agent_binding
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


SUPPORTED_SESSION_AGENTS = {"fake", "shell-dummy", "codex-cli"}

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
    if agent_id not in SUPPORTED_SESSION_AGENTS:
        raise ProtocolError(f"Unsupported session agent: {agent_id}")
    if isolation_mode not in {"copy", "worktree"}:
        raise ProtocolError(f"Unsupported isolation_mode: {isolation_mode}")
    if sandbox_mode not in {"read-only", "workspace-write", "danger-full-access"}:
        raise ProtocolError(f"Unsupported sandbox_mode: {sandbox_mode}")
    if agent_id == "shell-dummy" and not dry_run and not shell_command:
        raise ProtocolError("shell-dummy session requires --shell-command")
    if agent_id == "codex-cli":
        if target_model is None or target_provider is None:
            raise ProtocolError("codex-cli session requires target_model and target_provider")
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

    if spec.agent_id == "codex-cli":
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
    )


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
    if spec.agent_id == "codex-cli" and (
        spec.target_model is None or spec.target_provider is None
    ):
        raise ProtocolError("Dispatch binding is missing Codex model or provider")


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
        native_logs = _persist_native_logs(workspace, exc.stdout or "", exc.stderr or "")
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
        native_logs = _persist_native_logs(workspace, "", str(exc))
        _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
        outcome_metrics = _base_outcome_metrics(
            wall_time_ms=max(1, int((time.monotonic() - started_monotonic) * 1000))
        )
        extraction = _empty_agent_extraction("launch_failed", [str(exc)])
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
    native_logs = _persist_native_logs(workspace, completed.stdout, completed.stderr)
    diff_metrics, diff_refs = _collect_workspace_delta(workdir, baseline)
    _set_workspace_state_refs(workspace, baseline.files, _snapshot_workspace_files(workdir))
    codex_metrics, codex_extraction = _extract_codex_jsonl(completed.stdout)
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
) -> dict[str, str]:
    session_root = Path(_as_string(workspace, "session_root"))
    logs_dir = session_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_dir / "stdout.log"
    stderr_path = logs_dir / "stderr.log"
    stdout_text = _text_value(stdout)
    stderr_text = _text_value(stderr)
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
