from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import yaml

from ..agents import doctor_agent, list_agent_specs
from ..application.acceptance import decide_staged_result, stage_result
from ..application.demo import load_artifact_session_manifest, prepare_demo_workspace
from ..application.run_bundles import write_session_run_bundle
from ..core import (
    Dag,
    create_node,
    load_dag,
    load_run_records,
    ready_nodes,
    render_prompt,
    update_node_dependencies,
    update_node_metadata,
    update_review_status,
)
from ..errors import ProtocolError
from ..protocol.advisors import load_advisor_outcome
from ..protocol.acceptance import AcceptancePolicy, load_acceptance_policy
from ..protocol.assignments import compile_context_capsule, export_assignment, load_assignment
from ..protocol.context import load_context_request, resolve_context_request
from ..protocol.dispatch import compile_dispatch_packet, load_dispatch_packet, load_turn_report
from ..protocol.harness import load_ledger, load_mission, load_workflow
from ..protocol.ledger import (
    append_ledger_event,
    require_strict_writable_ledger,
    write_ledger,
)
from ..protocol.mutations import materialize_current_workflow
from ..protocol.outcomes import load_node_outcome, node_outcome_from_session
from ..protocol.results import import_result_proposal, load_result_proposal
from ..protocol.routing import load_routing_decision
from ..protocol.reviews import apply_review_decision, load_review_decision
from ..runtime import (
    build_mutation_supersession_events,
    evaluate_assignment_impacts,
    evaluate_gatekeeper,
    replay_workflow,
    summarize_metrics,
)
from ..runtime.sessions import (
    build_assignment_created_event,
    dispatch_session,
    package_session_result,
)


NodeState = Literal["ready", "blocked", "completed", "needs_review"]


class ReviewRequest(BaseModel):
    dag_path: str
    runs_dir: str = "runs"
    task_id: str
    review_status: str
    run_id: str | None = None


class NodeMetadataUpdateRequest(BaseModel):
    dag_path: str
    task_id: str
    updates: dict[str, Any]


class NodeDependenciesUpdateRequest(BaseModel):
    dag_path: str
    task_id: str
    dependencies: list[str]


class CreateNodeRequest(BaseModel):
    dag_path: str
    node: dict[str, Any]


class RuntimeDemoRequest(BaseModel):
    workspace: str
    agent: str = "shell-dummy"
    shell_command: str | None = None
    assignment_id: str = "assign-implement-demo"
    session_id: str = "session-implement-demo"
    result_id: str = "result-implement-demo"


class MutationDecisionRequest(BaseModel):
    workflow_path: str
    ledger_path: str
    proposal_event_id: str
    decision: Literal["accept", "reject"]
    actor: Literal["orchestrator", "human"] = "human"
    reason: str | None = None
    applied_changes: dict[str, Any] | None = None


class DispatchCompileRequest(BaseModel):
    mission_path: str
    workflow_path: str
    routing_decision_path: str
    assignment_path: str
    packet_id: str
    review_constraints: dict[str, Any] | None = None
    turn_report_policy: dict[str, Any] | None = None


class SessionDispatchRequest(BaseModel):
    mission_path: str
    workflow_path: str
    dispatch_packet_path: str
    session_record_path: str
    ledger_path: str | None = None
    run_bundle_path: str | None = None
    agent: str
    workdir: str = "."
    timeout_seconds: float = 30.0
    dry_run: bool = False
    isolation_mode: Literal["copy", "worktree"] = "copy"
    cleanup_policy: str = "retain_session_root"
    sandbox_mode: Literal["read-only", "workspace-write", "danger-full-access"] = (
        "workspace-write"
    )
    shell_command: str | None = None
    target_model: str | None = None
    target_provider: str | None = None
    provider_base_url: str | None = None
    provider_api_key_env: str | None = None
    provider_wire_api: str | None = None
    session_id: str | None = None


class ContextResolveRequest(BaseModel):
    assignment_path: str
    ledger_path: str
    context_request_path: str
    max_artifacts: int = 1


class ResultStageRequest(BaseModel):
    workflow_path: str
    ledger_path: str
    assignment_path: str
    result_path: str


class ReviewDecisionImportRequest(BaseModel):
    workflow_path: str
    ledger_path: str
    decision_path: str
    decision_ref: str
    event_id: str | None = None


class OutcomeDecisionRequest(BaseModel):
    workflow_path: str
    ledger_path: str
    assignment_path: str
    result_path: str
    outcome_path: str
    verification_status: str
    review_event_id: str | None = None
    acceptance_policy: dict[str, Any]
    accepted_event_types: list[str] | None = None
    actor: str = "harness"
    event_id: str | None = None
    validation_rule: str = "acceptance_policy_v1"


def create_app() -> FastAPI:
    app = FastAPI(title="BureauLess workbench")

    @app.exception_handler(ProtocolError)
    def handle_protocol_error(_request, exc: ProtocolError) -> JSONResponse:
        return JSONResponse(status_code=400, content=protocol_error_payload(exc))

    @app.exception_handler(OSError)
    def handle_os_error(_request, exc: OSError) -> JSONResponse:
        return JSONResponse(status_code=400, content=protocol_error_payload(exc))

    @app.get("/api/dag")
    def api_dag(path: str = "examples/optimization_dag.yaml") -> dict[str, Any]:
        dag = load_dag(Path(path))
        return dag_payload(dag)

    @app.get("/api/validate")
    def api_validate(path: str = "examples/optimization_dag.yaml") -> dict[str, Any]:
        try:
            load_dag(Path(path))
        except yaml.YAMLError as exc:
            return {"ok": False, "errors": [validation_error_from_yaml(exc)]}
        except (ProtocolError, OSError) as exc:
            return {"ok": False, "errors": [validation_error_from_exception(exc)]}
        return {"ok": True, "errors": []}

    @app.get("/api/runs")
    def api_runs(runs_dir: str = "runs") -> dict[str, Any]:
        return {"runs": load_run_records(Path(runs_dir))}

    @app.get("/api/state")
    def api_state(
        dag_path: str = "examples/optimization_dag.yaml",
        runs_dir: str = "runs",
    ) -> dict[str, Any]:
        dag = load_dag(Path(dag_path))
        records = load_run_records(Path(runs_dir))
        return state_payload(dag, records)

    @app.get("/api/prompt/{task_id}")
    def api_prompt(
        task_id: str,
        dag_path: str = "examples/optimization_dag.yaml",
    ) -> dict[str, str]:
        return {"task_id": task_id, "prompt": render_prompt(load_dag(Path(dag_path)), task_id)}

    @app.post("/api/review")
    def api_review(request: ReviewRequest) -> dict[str, str]:
        dag = load_dag(Path(request.dag_path))
        path = update_review_status(
            dag=dag,
            runs_dir=Path(request.runs_dir),
            task_id=request.task_id,
            review_status=request.review_status,
            run_id=request.run_id,
        )
        return {"path": str(path)}

    @app.post("/api/dag/node-metadata")
    def api_update_node_metadata(request: NodeMetadataUpdateRequest) -> dict[str, Any]:
        path, backup_path, dag = update_node_metadata(
            dag_path=Path(request.dag_path),
            task_id=request.task_id,
            updates=request.updates,
        )
        return {
            "path": str(path),
            "backup_path": str(backup_path),
            "node": dag.nodes[request.task_id].to_dict(),
        }

    @app.post("/api/dag/node-dependencies")
    def api_update_node_dependencies(
        request: NodeDependenciesUpdateRequest,
    ) -> dict[str, Any]:
        path, backup_path, dag = update_node_dependencies(
            dag_path=Path(request.dag_path),
            task_id=request.task_id,
            dependencies=request.dependencies,
        )
        return {
            "path": str(path),
            "backup_path": str(backup_path),
            "node": dag.nodes[request.task_id].to_dict(),
        }

    @app.post("/api/dag/nodes")
    def api_create_node(request: CreateNodeRequest) -> dict[str, Any]:
        path, backup_path, dag = create_node(
            dag_path=Path(request.dag_path),
            node_data=request.node,
        )
        node_id = request.node.get("id")
        if not isinstance(node_id, str):
            raise ProtocolError("Field 'id' must be a string")
        return {
            "path": str(path),
            "backup_path": str(backup_path),
            "node": dag.nodes[node_id].to_dict(),
        }

    @app.get("/api/mission")
    def api_mission(path: str = "examples/missions/demo/mission.yaml") -> dict[str, Any]:
        mission = load_mission(Path(path))
        return {
            "mission_id": mission.mission_id,
            "goal": mission.goal,
            "status": mission.status,
            "default_mode": mission.default_mode,
            "allowed_modes": mission.allowed_modes,
            "budget": mission.budget,
            "models": mission.models,
            "human_gate": mission.human_gate,
        }

    @app.get("/api/workflow")
    def api_workflow(path: str = "examples/missions/demo/workflows/coder_reviewer_committer.yaml") -> dict[str, Any]:
        workflow = load_workflow(Path(path))
        return workflow_payload(workflow)

    @app.get("/api/routing-decision")
    def api_routing_decision(path: str) -> dict[str, Any]:
        return load_routing_decision(_load_yaml(path)).to_dict()

    @app.get("/api/artifact-session-manifest")
    def api_artifact_session_manifest(path: str) -> dict[str, Any]:
        return load_artifact_session_manifest(Path(path))

    @app.get("/api/assignment")
    def api_assignment(path: str) -> dict[str, Any]:
        return load_assignment(_load_yaml(path)).to_dict()

    @app.get("/api/context-capsule")
    def api_context_capsule(
        path: str | None = None,
        workflow_path: str | None = None,
        ledger_path: str | None = None,
        node_id: str | None = None,
        assignment_id: str | None = None,
        mission_path: str | None = None,
    ) -> dict[str, Any]:
        if path:
            payload = _load_yaml(path)
            if not isinstance(payload, dict):
                raise ProtocolError("Context capsule YAML must be an object")
            return payload
        if not workflow_path or not ledger_path or not node_id or not assignment_id:
            raise ProtocolError(
                "Context capsule requires either path or workflow_path, ledger_path, node_id, and assignment_id"
            )
        mission = load_mission(Path(mission_path)) if mission_path else None
        return compile_context_capsule(
            load_workflow(Path(workflow_path)),
            load_ledger(Path(ledger_path)),
            node_id,
            assignment_id=assignment_id,
            mission=mission,
        ).to_dict()

    @app.get("/api/context-request")
    def api_context_request(path: str) -> dict[str, Any]:
        return load_context_request(_load_yaml(path)).to_dict()

    @app.post("/api/context-request/resolve")
    def api_context_request_resolve(request: ContextResolveRequest) -> dict[str, Any]:
        return resolve_context_request(
            load_assignment(_load_yaml(request.assignment_path)),
            load_ledger(Path(request.ledger_path)),
            load_context_request(_load_yaml(request.context_request_path)),
            max_artifacts=request.max_artifacts,
        ).to_dict()

    @app.get("/api/ledger")
    def api_ledger(path: str = "examples/missions/demo/ledger.yaml") -> dict[str, Any]:
        ledger = load_ledger(Path(path))
        return {
            "mission_id": ledger.mission_id,
            "ledger_version": ledger.ledger_version,
            "current_goal": ledger.current_goal,
            "current_plan_ref": ledger.current_plan_ref,
            "public_findings": ledger.public_findings,
            "decisions": ledger.decisions,
            "risks": ledger.risks,
            "artifacts": ledger.artifacts,
            "broadcasts": ledger.broadcasts,
            "open_questions": ledger.open_questions,
            "event_log": ledger.event_log,
        }

    @app.get("/api/replay")
    def api_replay(
        workflow_path: str = "examples/missions/demo/workflows/coder_reviewer_committer.yaml",
        ledger_path: str = "examples/missions/demo/ledger.yaml",
    ) -> dict[str, Any]:
        workflow = load_workflow(Path(workflow_path))
        ledger = load_ledger(Path(ledger_path))
        return replay_workflow(workflow, ledger).to_dict()

    @app.get("/api/gatekeeper")
    def api_gatekeeper(
        workflow_path: str = "examples/missions/demo/workflows/coder_reviewer_committer.yaml",
        ledger_path: str = "examples/missions/demo/ledger.yaml",
    ) -> dict[str, Any]:
        workflow = load_workflow(Path(workflow_path))
        ledger = load_ledger(Path(ledger_path))
        return evaluate_gatekeeper(workflow, ledger).to_dict()

    @app.get("/api/mutations")
    def api_mutations(
        workflow_path: str = "examples/missions/demo/workflows/coder_reviewer_committer.yaml",
        ledger_path: str = "examples/missions/demo/ledger.yaml",
    ) -> dict[str, Any]:
        workflow = load_workflow(Path(workflow_path))
        ledger = load_ledger(Path(ledger_path))
        return mutation_inspection_payload(workflow, ledger)

    @app.post("/api/mutations/decision")
    def api_mutation_decision(request: MutationDecisionRequest) -> dict[str, Any]:
        workflow = load_workflow(Path(request.workflow_path))
        ledger_path = Path(request.ledger_path)
        ledger = load_ledger(ledger_path)
        require_strict_writable_ledger(ledger, "mutation decision")
        proposal_event = next(
            (
                event
                for event in ledger.event_log
                if event.get("event_id") == request.proposal_event_id
                and event.get("event_type") == "workflow_mutation_proposed"
            ),
            None,
        )
        if proposal_event is None:
            raise ProtocolError("Unknown workflow mutation proposal event")

        event_id = f"event-mutation-{request.decision}-{uuid4()}"
        decision_event: dict[str, Any] = {
            "event_id": event_id,
            "event_type": f"workflow_mutation_{request.decision}ed",
            "mission_id": workflow.mission_id,
            "workflow_id": workflow.workflow_id,
            "source_event_id": request.proposal_event_id,
            "actor": request.actor,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if request.decision == "reject":
            if not request.reason:
                raise ProtocolError("Mutation rejection requires a reason")
            decision_event["reason"] = request.reason
            updated = append_ledger_event(ledger, decision_event, workflow)
        else:
            proposal = proposal_event.get("mutation_proposal")
            if not isinstance(proposal, dict):
                raise ProtocolError("Mutation proposal event is missing mutation_proposal")
            proposed_changes = proposal.get("proposed_changes")
            if not isinstance(proposed_changes, dict):
                raise ProtocolError("Mutation proposal is missing proposed_changes")
            decision_event["applied_changes"] = (
                request.applied_changes
                if request.applied_changes is not None
                else proposed_changes
            )
            before = materialize_current_workflow(workflow, ledger)
            updated = append_ledger_event(ledger, decision_event, workflow)
            after = materialize_current_workflow(workflow, updated)
            impacts = evaluate_assignment_impacts(
                before,
                after,
                updated,
                decision_event["applied_changes"],
            )
            for supersession_event in build_mutation_supersession_events(
                after, decision_event, impacts
            ):
                updated = append_ledger_event(updated, supersession_event, after)

        write_ledger(ledger_path, updated)
        return mutation_inspection_payload(workflow, updated)

    @app.get("/api/agents")
    def api_agents() -> dict[str, Any]:
        return {"agents": [spec.to_dict() for spec in list_agent_specs()]}

    @app.get("/api/agents/{agent_id}/doctor")
    def api_agent_doctor(agent_id: str) -> dict[str, Any]:
        return doctor_agent(agent_id).to_dict()

    @app.get("/api/result")
    def api_result(path: str) -> dict[str, Any]:
        return load_result_proposal(_load_yaml(path)).to_dict()

    @app.post("/api/result/stage")
    def api_result_stage(request: ResultStageRequest) -> dict[str, Any]:
        workflow = load_workflow(Path(request.workflow_path))
        ledger_path = Path(request.ledger_path)
        ledger = load_ledger(ledger_path)
        require_strict_writable_ledger(ledger, "result stage")
        assignment = load_assignment(_load_yaml(request.assignment_path))
        result = load_result_proposal(_load_yaml(request.result_path))
        updated = import_result_proposal(workflow, ledger, assignment, result)
        write_ledger(ledger_path, updated)
        return {
            "status": "awaiting_acceptance",
            "result_event_id": f"event-{result.result_id}",
            "replay": replay_workflow(workflow, updated).to_dict(),
            "gatekeeper": evaluate_gatekeeper(workflow, updated).to_dict(),
        }

    @app.post("/api/review-decision/import")
    def api_review_decision_import(
        request: ReviewDecisionImportRequest,
    ) -> dict[str, Any]:
        workflow = load_workflow(Path(request.workflow_path))
        ledger_path = Path(request.ledger_path)
        ledger = load_ledger(ledger_path)
        require_strict_writable_ledger(ledger, "review decision import")
        decision = load_review_decision(_load_yaml(request.decision_path))
        updated = apply_review_decision(
            ledger,
            decision,
            workflow=workflow,
            event_id=request.event_id,
            decision_ref=request.decision_ref,
        )
        write_ledger(ledger_path, updated)
        return updated.event_log[-1]

    @app.post("/api/outcome/decide")
    def api_outcome_decide(request: OutcomeDecisionRequest) -> dict[str, Any]:
        workflow = load_workflow(Path(request.workflow_path))
        ledger_path = Path(request.ledger_path)
        ledger = load_ledger(ledger_path)
        require_strict_writable_ledger(ledger, "outcome acceptance")
        accepted = decide_staged_result(
            workflow,
            ledger,
            load_assignment(_load_yaml(request.assignment_path)),
            load_result_proposal(_load_yaml(request.result_path)),
            load_node_outcome(_load_yaml(request.outcome_path)),
            policy=load_acceptance_policy(request.acceptance_policy),
            verification_status=request.verification_status,
            review_event_id=request.review_event_id,
            accepted_event_types=request.accepted_event_types,
            actor=request.actor,
            event_id=request.event_id,
            validation_rule=request.validation_rule,
        )
        write_ledger(ledger_path, accepted.ledger)
        return {
            "status": accepted.disposition,
            "decision": accepted.decision_event,
            "replay": replay_workflow(workflow, accepted.ledger).to_dict(),
            "gatekeeper": evaluate_gatekeeper(workflow, accepted.ledger).to_dict(),
        }

    @app.get("/api/node-outcome")
    def api_node_outcome(path: str) -> dict[str, Any]:
        return load_node_outcome(_load_yaml(path)).to_dict()

    @app.get("/api/advisor-outcome")
    def api_advisor_outcome(path: str) -> dict[str, Any]:
        return load_advisor_outcome(_load_yaml(path)).to_dict()

    @app.get("/api/turn-report")
    def api_turn_report(path: str) -> dict[str, Any]:
        return load_turn_report(_load_yaml(path)).to_dict()

    @app.get("/api/dispatch-packet")
    def api_dispatch_packet(path: str) -> dict[str, Any]:
        return load_dispatch_packet(_load_yaml(path)).to_dict()

    @app.post("/api/dispatch-packet/compile")
    def api_dispatch_packet_compile(request: DispatchCompileRequest) -> dict[str, Any]:
        mission = load_mission(Path(request.mission_path))
        workflow = load_workflow(Path(request.workflow_path))
        routing_decision = load_routing_decision(_load_yaml(request.routing_decision_path))
        assignment = load_assignment(_load_yaml(request.assignment_path))
        return compile_dispatch_packet(
            mission,
            workflow,
            routing_decision,
            assignment,
            packet_id=request.packet_id,
            review_constraints=request.review_constraints,
            turn_report_policy=request.turn_report_policy,
        ).to_dict()

    @app.post("/api/session/dispatch")
    def api_session_dispatch(request: SessionDispatchRequest) -> dict[str, Any]:
        if request.run_bundle_path is not None and request.ledger_path is None:
            raise ProtocolError("Session run bundle generation requires ledger_path")
        packet_path = Path(request.dispatch_packet_path)
        record = dispatch_session(
            load_mission(Path(request.mission_path)),
            load_workflow(Path(request.workflow_path)),
            load_dispatch_packet(_load_yaml(str(packet_path))),
            agent_id=request.agent,
            workdir=Path(request.workdir),
            dispatch_packet_path=packet_path,
            timeout_seconds=request.timeout_seconds,
            dry_run=request.dry_run,
            isolation_mode=request.isolation_mode,
            cleanup_policy=request.cleanup_policy,
            sandbox_mode=request.sandbox_mode,
            shell_command=request.shell_command,
            target_model=request.target_model,
            target_provider=request.target_provider,
            provider_base_url=request.provider_base_url,
            provider_api_key_env=request.provider_api_key_env,
            provider_wire_api=request.provider_wire_api,
            session_id=request.session_id,
            context_ledger=(
                load_ledger(Path(request.ledger_path)) if request.ledger_path else None
            ),
        )
        session_path = Path(request.session_record_path)
        _write_yaml(session_path, record.to_dict())
        response = record.to_dict()
        if request.ledger_path is not None:
            bundle_path = (
                Path(request.run_bundle_path)
                if request.run_bundle_path
                else session_path.with_suffix(".bundle.yaml")
            )
            bundle = write_session_run_bundle(
                bundle_path,
                mission_path=Path(request.mission_path),
                workflow_path=Path(request.workflow_path),
                ledger_path=Path(request.ledger_path),
                dispatch_packet_path=packet_path,
                session_record_path=session_path,
                packet=load_dispatch_packet(_load_yaml(str(packet_path))),
                record=record.to_dict(),
                workspace=Path(request.workdir),
            )
            response["run_bundle_path"] = bundle["manifest_path"]
        return response

    @app.get("/api/metrics")
    def api_metrics(path: str, price_snapshot: str | None = None) -> dict[str, Any]:
        snapshot_path = Path(price_snapshot) if price_snapshot else None
        return summarize_metrics(Path(path), snapshot_path)

    @app.post("/api/runtime-demo")
    def api_runtime_demo(request: RuntimeDemoRequest) -> dict[str, Any]:
        paths = prepare_demo_workspace(
            Path(request.workspace),
            ledger_version=2,
        )
        workflow = load_workflow(paths["workflow"])
        mission = load_mission(paths["mission"])
        ledger = load_ledger(paths["ledger"])
        assignment = export_assignment(
            workflow,
            ledger,
            "implement",
            assignment_id=request.assignment_id,
        )
        assignment_path = paths["assignments_dir"] / "implement_assignment.yaml"
        _write_yaml(assignment_path, assignment.to_dict())
        routing_decision = load_routing_decision(
            _runtime_demo_routing_decision(workflow)
        )
        packet = compile_dispatch_packet(
            mission,
            workflow,
            routing_decision,
            assignment,
            packet_id=f"packet-{request.session_id}",
        )
        packet_path = paths["decisions_dir"] / "implement_dispatch_packet.yaml"

        created_event = build_assignment_created_event(
            workflow,
            assignment,
            request.session_id,
            request.agent,
        )
        ledger = append_ledger_event(ledger, created_event, workflow)
        write_ledger(paths["ledger"], ledger)

        record = dispatch_session(
            mission,
            workflow,
            packet,
            agent_id=request.agent,
            workdir=Path(request.workspace),
            dispatch_packet_path=packet_path,
            shell_command=request.shell_command or _runtime_demo_shell_command(request.result_id),
            session_id=request.session_id,
            context_ledger=ledger,
        )
        session_path = paths["sessions_dir"] / "implement_session.yaml"
        _write_yaml(session_path, record.to_dict())

        result = package_session_result(record, assignment, result_id=request.result_id)
        result_path = paths["packaged_results_dir"] / "implement_result.yaml"
        _write_yaml(result_path, result.to_dict())

        outcome = node_outcome_from_session(
            assignment,
            record.to_dict(),
            outcome_id=f"outcome-{record.session_id}",
        )
        outcome_path = paths["outcomes_dir"] / "implement_outcome.yaml"
        _write_yaml(outcome_path, outcome.to_dict())
        staged = stage_result(workflow, ledger, assignment, result, outcome)
        low_risk_policy = AcceptancePolicy(
            policy_version="acceptance-v1-low-risk-demo",
            review_required=False,
            allowed_review_actors=["orchestrator", "human"],
            required_verification_statuses=["passed"],
            allow_partial_acceptance=False,
        )
        verification_status = result.verification.get("status")
        accepted = decide_staged_result(
            workflow,
            staged.ledger,
            assignment,
            result,
            outcome,
            policy=low_risk_policy,
            verification_status=(
                verification_status
                if isinstance(verification_status, str)
                else "unknown"
            ),
            validation_rule="verified_low_risk_demo_v1",
            created_at=record.finished_at,
        )
        ledger = accepted.ledger
        write_ledger(paths["ledger"], ledger)

        return {
            "workspace": str(Path(request.workspace).resolve()),
            "mission_path": str(paths["mission"]),
            "workflow_path": str(paths["workflow"]),
            "ledger_path": str(paths["ledger"]),
            "assignment_path": str(assignment_path),
            "dispatch_packet_path": str(packet_path),
            "session_path": str(session_path),
            "result_path": str(result_path),
            "outcome_path": str(outcome_path),
            "agent": request.agent,
            "assignment_id": assignment.assignment_id,
            "session_id": record.session_id,
            "result_id": result.result_id,
            "replay": replay_workflow(workflow, ledger).to_dict(),
            "gatekeeper": evaluate_gatekeeper(workflow, ledger).to_dict(),
            "result": result.to_dict(),
            "acceptance": accepted.decision_event,
        }

    return app


def dag_payload(dag: Dag) -> dict[str, Any]:
    nodes = [node.to_dict() for node in dag.nodes.values()]
    edges = [
        {"id": f"{dependency}->{node.id}", "source": dependency, "target": node.id}
        for node in dag.nodes.values()
        for dependency in node.dependencies
    ]
    return {
        "schema_version": dag.schema_version,
        "project": dag.project,
        "default_review_model": dag.default_review_model,
        "nodes": nodes,
        "edges": edges,
    }


def state_payload(dag: Dag, records: list[dict[str, Any]]) -> dict[str, Any]:
    ready = {node.id for node in ready_nodes(dag, records)}
    states = {
        node_id: classify_node_state(dag, node_id, records, ready)
        for node_id in dag.nodes
    }
    return {"states": states, "ready": sorted(ready)}


def _load_yaml(path: str) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProtocolError("YAML payload must be an object")
    return payload


def _runtime_demo_routing_decision(workflow: Any) -> dict[str, Any]:
    return {
        "decision_type": "routing_decision",
        "mission_id": workflow.mission_id,
        "workflow_id": workflow.workflow_id,
        "selected_mode": workflow.mode,
        "selection_policy_version": "runtime-demo-v1",
        "triggered_rules": ["maintained_demo_path"],
        "rejected_modes": [
            {
                "mode": "single_agent",
                "rejected_because": "The maintained demo preserves explicit review and commit nodes.",
            }
        ],
        "estimated_coordination_ratio": 0.18,
        "budget_confidence": "high",
        "reason": "The maintained demo executes the accepted staged workflow.",
        "budget_reason": "The fixture stays within the mission budget.",
        "risk_reason": "Review and commit remain explicit downstream gates.",
        "advisor_gate_decision": {
            "invoked": False,
            "policy_version": "runtime-demo-v1",
            "reason": ["maintained_low_risk_fixture"],
            "decision_basis": "deterministic_fixture",
        },
    }


def workflow_payload(workflow) -> dict[str, Any]:
    return {
        "workflow_id": workflow.workflow_id,
        "mission_id": workflow.mission_id,
        "mode": workflow.mode,
        "status": workflow.status,
        "reason": workflow.reason,
        "proposed_by": workflow.proposed_by,
        "roles": {
            role_name: {
                "can_emit": role.can_emit,
                "can_consume": role.can_consume,
            }
            for role_name, role in workflow.roles.items()
        },
        "events": {
            event_name: {"producer_roles": event.producer_roles}
            for event_name, event in workflow.events.items()
        },
        "nodes": [
            {
                "id": node.id,
                "role": node.role,
                "waits_for": node.waits_for,
                "emits": node.emits,
            }
            for node in workflow.nodes.values()
        ],
        "gates": [
            {
                "id": gate.id,
                "node_id": gate.node_id,
                "requires": gate.requires,
            }
            for gate in workflow.gates
        ],
        "terminal_events": workflow.terminal_events,
        "broadcast_policy": workflow.broadcast_policy,
        "budget_policy": workflow.budget_policy,
    }


def mutation_inspection_payload(workflow, ledger) -> dict[str, Any]:
    replay = replay_workflow(workflow, ledger)
    current = materialize_current_workflow(workflow, ledger)
    event_by_id = {
        event.get("event_id"): event
        for event in ledger.event_log
        if isinstance(event.get("event_id"), str)
    }
    assignment_nodes = {
        event.get("assignment_id"): event.get("node_id")
        for event in ledger.event_log
        if isinstance(event.get("assignment_id"), str)
        and isinstance(event.get("node_id"), str)
    }
    proposals = []
    for event_id, mutation in replay.mutation_proposals.items():
        event = event_by_id.get(event_id, {})
        proposal = event.get("mutation_proposal", {})
        affected_assignments = sorted(
            assignment_id
            for assignment_id, node_id in assignment_nodes.items()
            if node_id in mutation.affected_node_ids
        )
        superseded_assignments = sorted(
            event.get("assignment_id")
            for event in ledger.event_log
            if event.get("event_type") == "assignment_superseded"
            and event.get("mutation_event_id") == mutation.decision_event_id
            and isinstance(event.get("assignment_id"), str)
        )
        proposals.append(
            {
                **mutation.to_dict(),
                "proposal": proposal,
                "evidence_refs": (
                    proposal.get("evidence_refs", [])
                    if isinstance(proposal, dict)
                    else []
                ),
                "affected_assignments": affected_assignments,
                "superseded_assignments": superseded_assignments,
            }
        )
    return {
        "workflow_id": workflow.workflow_id,
        "current_workflow": workflow_payload(current),
        "proposals": proposals,
    }


def protocol_error_payload(exc: Exception) -> dict[str, str]:
    return {"error": str(exc)}


def _runtime_demo_shell_command(result_id: str) -> str:
    payload = yaml.safe_dump(
        {
            "status": "completed",
            "effective_model": "shell-dummy",
            "effective_provider": "fixture",
            "emitted_events": ["patch_ready"],
            "artifacts": [
                {
                    "artifact_id": f"artifact-{result_id}-patch",
                    "path": "artifacts/implement_patch.diff",
                }
            ],
            "verification": {"status": "passed"},
        },
        sort_keys=False,
    ).strip()
    return (
        "mkdir -p artifacts\n"
        "cat <<'EOF' > artifacts/implement_patch.diff\n"
        "--- a/src/demo.py\n"
        "+++ b/src/demo.py\n"
        "@@\n"
        "-print('old')\n"
        "+print('new')\n"
        "EOF\n"
        f"cat <<'EOF'\n{payload}\nEOF"
    )


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


def validation_error_from_yaml(exc: yaml.YAMLError) -> dict[str, Any]:
    message = "Invalid YAML syntax"
    if getattr(exc, "problem", None):
        message = f"{message}: {exc.problem}"

    error: dict[str, Any] = {
        "code": "invalid_yaml",
        "message": message,
    }
    mark = getattr(exc, "problem_mark", None)
    if mark is not None:
        error["line"] = mark.line + 1
        error["column"] = mark.column + 1
    return error


def validation_error_from_exception(exc: Exception) -> dict[str, Any]:
    message = str(exc)

    missing_fields_match = re.fullmatch(
        r"Task node is missing required fields: (?P<fields>.+)",
        message,
    )
    if missing_fields_match:
        fields = [field.strip() for field in missing_fields_match.group("fields").split(",")]
        return {
            "code": "missing_required_fields",
            "message": message,
            "fields": fields,
        }

    unknown_dependency_match = re.fullmatch(
        r"(?P<node_id>[^:]+): unknown dependency (?P<dependency>.+)",
        message,
    )
    if unknown_dependency_match:
        dependency = unknown_dependency_match.group("dependency").strip("'")
        return {
            "code": "unknown_dependency",
            "message": message,
            "node_id": unknown_dependency_match.group("node_id"),
            "dependency": dependency,
        }

    duplicate_node_match = re.fullmatch(r"Duplicate node id: (?P<node_id>.+)", message)
    if duplicate_node_match:
        return {
            "code": "duplicate_node",
            "message": message,
            "node_id": duplicate_node_match.group("node_id"),
        }

    cycle_match = re.fullmatch(r"Cycle detected at node (?P<node_id>.+)", message)
    if cycle_match:
        return {
            "code": "cycle_detected",
            "message": message,
            "node_id": cycle_match.group("node_id"),
        }

    field_match = re.fullmatch(r"Field '(?P<field>[^']+)' must be a string", message)
    if field_match:
        return {
            "code": "missing_required_fields",
            "message": message,
            "fields": [field_match.group("field")],
        }

    return {
        "code": "validation_error",
        "message": message,
    }


def classify_node_state(
    dag: Dag,
    node_id: str,
    records: list[dict[str, Any]],
    ready: set[str],
) -> NodeState:
    node_records = [
        record
        for record in records
        if record.get("task_id") == node_id and record.get("status") == "passed"
    ]
    if node_records:
        latest = node_records[-1]
        review_status = latest.get("review_status")
        if review_status in {"pending", "rejected"}:
            return "needs_review"
        node = dag.nodes[node_id]
        if review_status in {
            "auto_pass": {"not_required", "approved"},
            "orchestrator_review": {"orchestrator_approved"},
            "human_review": {"human_approved"},
        }[node.review_gate]:
            return "completed"
        return "needs_review"
    if node_id in ready:
        return "ready"
    return "blocked"


app = create_app()


__all__ = [
    "CreateNodeRequest",
    "NodeMetadataUpdateRequest",
    "OutcomeDecisionRequest",
    "ProtocolError",
    "ResultStageRequest",
    "ReviewDecisionImportRequest",
    "RuntimeDemoRequest",
    "SessionDispatchRequest",
    "app",
    "classify_node_state",
    "create_app",
    "dag_payload",
    "protocol_error_payload",
    "state_payload",
    "workflow_payload",
]
