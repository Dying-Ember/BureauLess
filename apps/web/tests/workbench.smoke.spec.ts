import { expect, test, type Page } from '@playwright/test';

const dagFixture = {
  schema_version: '1',
  project: 'automation-inspection-optimization',
  default_review_model: 'gpt-5',
  nodes: [
    {
      id: 'baseline-inventory',
      title: 'Baseline Inventory',
      goal: 'Inventory the workflow baseline.',
      dependencies: [],
      target_files: ['docs/baseline.md'],
      context_files: [],
      allowed_models: ['gpt-5.4-mini'],
      recommended_model: 'gpt-5.4-mini',
      risk_level: 'low',
      review_gate: 'auto_pass',
      acceptance_criteria: ['Inventory is captured'],
      verification_commands: ['pytest -q'],
      do_not: ['Do not change unrelated files'],
      prompt_template: 'Baseline prompt',
      failure_policy: 'retry_same_model',
      outputs: [],
      tags: [],
    },
    {
      id: 'worker-stop-lifecycle',
      title: 'Worker Stop Lifecycle',
      goal: 'Make worker stop behavior explicit.',
      dependencies: ['baseline-inventory'],
      target_files: ['src/worker.ts'],
      context_files: [],
      allowed_models: ['gpt-5.4', 'gpt-5.5'],
      recommended_model: 'gpt-5.4',
      risk_level: 'high',
      review_gate: 'human_review',
      acceptance_criteria: ['Stop path is documented'],
      verification_commands: ['pytest -q'],
      do_not: ['Do not bypass review'],
      prompt_template: 'Worker prompt',
      failure_policy: 'send_to_human',
      outputs: [],
      tags: [],
    },
  ],
  edges: [
    {
      id: 'baseline-inventory->worker-stop-lifecycle',
      source: 'baseline-inventory',
      target: 'worker-stop-lifecycle',
    },
  ],
} as const;

const mutationFixture = {
  workflow_id: 'workflow-001',
  current_workflow: {
    workflow_id: 'workflow-001',
    mission_id: 'demo',
    mode: 'small_dag',
    status: 'active',
    reason: null,
    proposed_by: null,
    roles: {
      producer: { can_emit: ['patch_ready', 'verification_ready'], can_consume: [] },
      reviewer: { can_emit: ['review_complete'], can_consume: ['patch_ready', 'verification_ready'] },
      observer: { can_emit: ['audit_complete'], can_consume: [] },
    },
    events: {
      patch_ready: { producer_roles: ['producer'] },
      verification_ready: { producer_roles: ['producer'] },
      review_complete: { producer_roles: ['reviewer'] },
      audit_complete: { producer_roles: ['observer'] },
    },
    nodes: [
      { id: 'prepare', role: 'producer', waits_for: [], emits: ['patch_ready'] },
      { id: 'review', role: 'reviewer', waits_for: ['prepare.patch_ready'], emits: ['review_complete'] },
      { id: 'independent', role: 'observer', waits_for: [], emits: ['audit_complete'] },
    ],
    gates: [{ id: 'gate-review', node_id: 'review', requires: ['prepare.patch_ready'] }],
    terminal_events: ['review_complete', 'audit_complete'],
  },
  proposals: [
    {
      proposal_id: 'mutation-001',
      proposal_event_id: 'event-mutation-001',
      state: 'pending',
      affected_node_ids: ['review'],
      affected_assignments: ['assign-review'],
      superseded_assignments: [],
      evidence_refs: ['artifact-impact-report'],
      proposal: {
        reason: 'discovered_missing_dependency',
        rationale: 'A verification step is required before review.',
        proposed_changes: {
          add_nodes: [{ id: 'verify', role: 'producer', waits_for: [], emits: ['verification_ready'] }],
          add_edges: [{ from_node: 'verify', to_node: 'review', event: 'verification_ready' }],
          remove_edges: [],
          supersede_assignments: ['assign-review'],
        },
      },
    },
  ],
};

const missionFixture = {
  mission_id: 'demo',
  goal: 'Keep the runtime workflow healthy.',
  status: 'active',
  default_mode: 'small_dag',
  allowed_modes: ['small_dag'],
  budget: null,
  models: {},
  human_gate: null,
};

const artifactManifestFixture = {
  milestone: 'runtime-milestone-3',
  flow_id: 'demo-live-session-path',
  workspace: '/tmp/live-demo',
  mission_path: '.bureauless/m3-demo/mission.yaml',
  workflow_path: '.bureauless/m3-demo/workflow.yaml',
  ledger_path: '.bureauless/m3-demo/ledger.yaml',
  agent: 'codex-cli',
  target_model: 'gpt-5.4',
  target_provider: 'openai',
  routing_decision_path: '.bureauless/m3-demo/generated/decisions/routing.yaml',
  advisor_gate_decision_path: '.bureauless/m3-demo/generated/decisions/advisor_gate_decision.yaml',
  advisor_gate_outcome_path: '.bureauless/m3-demo/generated/telemetry/advisor_outcome.yaml',
  metrics_summary_path: '.bureauless/m3-demo/generated/telemetry/metrics_summary.yaml',
  workbench_url: 'http://127.0.0.1:5173/?artifact_manifest_path=.bureauless/m3-demo/generated/telemetry/manifest.yaml',
  steps: [
    {
      node_id: 'prepare',
      assignment_path: '.bureauless/m3-demo/generated/assignments/prepare_assignment.yaml',
      context_capsule_path: '.bureauless/m3-demo/generated/capsules/prepare_context_capsule.yaml',
      context_request_path: '.bureauless/m3-demo/generated/context/prepare_context_request.yaml',
      session_path: '.bureauless/m3-demo/generated/sessions/prepare_session.yaml',
      result_path: '.bureauless/m3-demo/generated/results/prepare_result.yaml',
      node_outcome_path: '.bureauless/m3-demo/generated/outcomes/prepare_node_outcome.yaml',
      review_decision_path: '.bureauless/m3-demo/generated/reviews/prepare_review_decision.yaml',
      turn_report_path: '.bureauless/m3-demo/generated/telemetry/prepare_turn_report.yaml',
      dispatch_packet_path: '.bureauless/m3-demo/generated/decisions/prepare_dispatch_packet.yaml',
      record_status: 'completed',
      emitted_events: ['patch_ready'],
      outcome_event_id: 'event-outcome-session-prepare-live-decision',
      review_event_id: 'event-review-prepare-live',
      ready_after: ['review'],
      node_state_after: 'completed',
    },
  ],
  failure: null,
  terminal_complete: true,
  ready: [],
  node_states: {
    implement: 'completed',
    review: 'completed',
    commit: 'completed',
  },
  manifest_path: '.bureauless/m3-demo/generated/telemetry/manifest.yaml',
} as const;

const routingDecisionFixture = {
  decision_type: 'routing_decision',
  mission_id: 'demo',
  workflow_id: 'workflow-001',
  selected_mode: 'small_dag',
  selection_policy_version: '0.1',
  triggered_rules: ['explicit_review_step_required', 'explicit_commit_step_required'],
  rejected_modes: [
    {
      mode: 'single_agent',
      rejected_because: 'The demo keeps inspectable handoff boundaries between implement, review, and commit.',
    },
  ],
  estimated_coordination_ratio: 0.18,
  budget_confidence: 'high',
  reason: 'The workflow remains a staged small DAG so review and commit stay explicit.',
  budget_reason: 'Observed usage remains below the advisor threshold for escalation.',
  risk_reason: 'The commit path stays review-gated.',
  advisor_gate_decision: {
    invoked: false,
    policy_version: '0.1',
    reason: ['parallel_width < 3', 'estimated_total_tokens < 80000'],
    decision_basis: 'first_run_heuristic',
  },
} as const;

const advisorOutcomeFixture = {
  decision_type: 'advisor_outcome',
  outcome_id: 'advisor-outcome-001',
  mission_id: 'demo',
  workflow_id: 'workflow-001',
  status: 'scored',
  source_decision_type: 'routing_decision',
  source_decision_ref: 'generated/decisions/routing.yaml',
  advisor_decision_ref: 'generated/decisions/advisor_gate_decision.yaml',
  classification: 'good_skip',
  actual_advisor_tokens: 120,
  actual_total_tokens: 1800,
  rework_count: 0,
  broadcast_tokens: 80,
  duplicate_context_observed: false,
  price_snapshot_attribution: {
    provider: 'openai',
    model: 'gpt-5.4',
  },
  notes: 'Skip remained the correct call for the bounded demo graph.',
} as const;

const nodeOutcomeFixture = {
  outcome_id: 'outcome-session-prepare-live',
  assignment_id: 'assign-prepare-live',
  session_id: 'session-prepare-live',
  workflow_id: 'workflow-001',
  node_id: 'prepare',
  role: 'producer',
  agent_id: 'codex-cli',
  status: 'completed',
  effective_model: 'gpt-5.4',
  effective_provider: 'openai',
  pre_state_ref: 'workspace-prepared',
  post_state_ref: 'workspace-updated',
  observed_delta: {
    changed_files_count: 1,
    patch_bytes: 124,
    diff_refs: [{ artifact_id: 'artifact-prepare-patch', path: 'artifacts/prepare.diff' }],
  },
  verification: {
    status: 'passed',
  },
  native_log_refs: [],
  diff_refs: [{ artifact_id: 'artifact-prepare-patch', path: 'artifacts/prepare.diff' }],
  outcome_metrics: {
    wall_time_ms: 1000,
    changed_files_count: 1,
  },
  extraction: {},
} as const;

const assignmentFixture = {
  assignment_id: 'assign-prepare-live',
  workflow_id: 'workflow-001',
  node_id: 'prepare',
  role: 'producer',
  goal: 'Prepare the implementation patch.',
  visible_context: {},
  artifact_refs: [{ artifact_id: 'artifact-prepare-patch', path: 'artifacts/prepare.diff' }],
  allowed_tools: [],
  forbidden_actions: ['update_canonical_ledger'],
  expected_events: ['patch_ready'],
  outcome_metrics_policy: {
    wall_time: 'required',
    final_status: 'required',
  },
} as const;

const agentsFixture = {
  agents: [
    {
      agent_id: 'codex-cli',
      binary: 'codex',
      kind: 'local_agent_cli',
      help_args: ['exec', '--help'],
      version_args: ['--version'],
      cancellation: 'process_kill',
      metrics_capability: {
        wall_time: 'required',
        final_status: 'required',
        changed_files: 'required',
        token_usage: 'optional',
        cost_usage: 'optional',
        progress_events: 'native_jsonl',
      },
    },
  ],
} as const;

const agentDoctorFixture = {
  agent_id: 'codex-cli',
  status: 'usable',
  control_level: 'high',
  binary: 'codex',
  binary_path: '/usr/bin/codex',
  version: 'codex 1.0.0',
  checks: [
    {
      name: 'non_interactive',
      status: 'passed',
      markers: ['exec'],
      missing_markers: [],
    },
    {
      name: 'output_stream',
      status: 'passed',
      markers: ['--json'],
      missing_markers: [],
    },
  ],
  warnings: [],
  metrics_capability: {
    wall_time: 'required',
    final_status: 'required',
    changed_files: 'required',
    token_usage: 'optional',
    cost_usage: 'optional',
    progress_events: 'native_jsonl',
  },
} as const;

const contextResolutionFixture = {
  context_request_id: 'ctxreq-001',
  assignment_id: 'assign-prepare-live',
  status: 'resolved',
  policy_version: 'context-resolution-v1',
  granted_artifacts: [{ artifact_id: 'artifact-test-report-017', path: 'artifacts/test-report.txt' }],
  denied_refs: [{ ref: 'artifact-secret-001', reason: 'Outside assignment scope' }],
  unavailable_refs: [{ ref: 'artifact-missing-001', reason: 'Artifact not found' }],
  added_tokens_estimate: 620,
  continuation_id: 'cont-001',
  session_id: 'session-prepare-live',
  request_index: 1,
  resolved_at: '2026-07-05T00:00:00Z',
} as const;

const dispatchCompileFixture = {
  packet_id: 'packet-assign-prepare-live',
  mission_id: 'demo',
  workflow_id: 'workflow-001',
  routing_decision: routingDecisionFixture,
  assignment: assignmentFixture,
  review_constraints: {
    required_gate_ids: [],
    requires_review_decision: false,
  },
  turn_report_policy: {
    after_each_tool_call: true,
    max_report_tokens: 600,
  },
} as const;

const sessionDispatchFixture = {
  session_id: 'session-prepare-live',
  assignment_id: 'assign-prepare-live',
  agent_id: 'codex-cli',
  status: 'completed',
  started_at: '2026-07-05T00:00:00Z',
  finished_at: '2026-07-05T00:01:00Z',
  exit: { code: 0, reason: 'completed' },
  native_logs: {},
  diff_refs: [],
  artifacts: [],
  workspace: { root: '/tmp/live-demo' },
  outcome_metrics: { wall_time_ms: 60000 },
  extraction: {},
  result_proposal: null,
  dispatch: { packet_id: 'packet-assign-prepare-live' },
  run_bundle_path: '.bureauless/sessions/assign-prepare-live.bundle.yaml',
} as const;

const resultStageFixture = {
  status: 'awaiting_acceptance',
  result_event_id: 'event-result-prepare-live',
  replay: {
    workflow_id: 'workflow-001',
    workflow_version_id: 'workflow-version-002',
    through_event_id: null,
    through_event_ordinal: null,
    terminal_complete: false,
    nodes: {},
    mutation_proposals: {},
    assignment_validity: {},
  },
  gatekeeper: {
    workflow_id: 'workflow-001',
    ready: [],
    decisions: {},
  },
} as const;

const reviewImportFixture = {
  event_id: 'event-review-imported-001',
  event_type: 'review_decision_recorded',
} as const;

const outcomeDecideFixture = {
  status: 'accepted',
  decision: {
    event_id: 'event-outcome-decided-001',
    event_type: 'node_outcome_decided',
    accepted_event_types: ['patch_ready'],
  },
  replay: {
    workflow_id: 'workflow-001',
    workflow_version_id: 'workflow-version-002',
    through_event_id: null,
    through_event_ordinal: null,
    terminal_complete: false,
    nodes: {},
    mutation_proposals: {},
    assignment_validity: {},
  },
  gatekeeper: {
    workflow_id: 'workflow-001',
    ready: [],
    decisions: {},
  },
} as const;

const runtimeDemoFixture = {
  workspace: '/tmp/bureauless-runtime-demo',
  mission_path: '.bureauless/runtime-demo/mission.yaml',
  workflow_path: '.bureauless/runtime-demo/workflow.yaml',
  ledger_path: '.bureauless/runtime-demo/ledger.yaml',
  assignment_path: '.bureauless/runtime-demo/generated/assignments/implement_assignment.yaml',
  dispatch_packet_path: '.bureauless/runtime-demo/generated/decisions/implement_dispatch_packet.yaml',
  session_path: '.bureauless/runtime-demo/generated/sessions/implement_session.yaml',
  result_path: '.bureauless/runtime-demo/generated/results/implement_result.yaml',
  outcome_path: '.bureauless/runtime-demo/generated/outcomes/implement_outcome.yaml',
  agent: 'shell-dummy',
  assignment_id: 'assign-implement-demo',
  session_id: 'session-implement-demo',
  result_id: 'result-implement-demo',
  replay: {
    workflow_id: 'workflow-001',
    workflow_version_id: 'workflow-version-002',
    through_event_id: null,
    through_event_ordinal: null,
    terminal_complete: false,
    nodes: {},
    mutation_proposals: {},
    assignment_validity: {},
  },
  gatekeeper: {
    workflow_id: 'workflow-001',
    ready: [],
    decisions: {},
  },
  result: {
    result_id: 'result-implement-demo',
    assignment_id: 'assign-implement-demo',
    agent_id: 'shell-dummy',
    status: 'completed',
    emitted_events: ['patch_ready'],
    artifacts: [],
    outcome_metrics: {},
    verification: { status: 'passed' },
    native_log_refs: [],
    mutation_proposal_refs: [],
  },
  acceptance: {
    event_id: 'event-runtime-demo-accepted-001',
    event_type: 'node_outcome_decided',
  },
} as const;

const contextCapsuleFixture = {
  context_capsule_id: 'context-assign-prepare-live',
  policy_version: 'context-v1',
  mission_id: 'demo',
  workflow_id: 'workflow-001',
  assignment_id: 'assign-prepare-live',
  node_id: 'prepare',
  role: 'producer',
  workspace_ref: 'workspace-prepared',
  dependency_node_ids: ['prepare'],
  required_gates: [],
  role_permissions: {
    can_emit: ['patch_ready'],
    can_consume: [],
  },
  accepted_facts: [
    {
      finding_id: 'finding-prepare-live',
      content: 'The current implementation baseline is already isolated.',
    },
  ],
  accepted_decisions: [],
  active_risks: [
    {
      risk_id: 'risk-prepare-001',
      summary: 'Patch must preserve the downstream review handoff.',
      status: 'open',
    },
  ],
  open_questions: [],
  artifact_refs: [{ artifact_id: 'artifact-prepare-patch', path: 'artifacts/prepare.diff' }],
  source_event_ids: ['event-review-prepare-live'],
  mission_constraints: {},
  excluded: {
    ledger: 'bounded_context_only',
  },
} as const;

const resultFixture = {
  result_id: 'result-prepare-live',
  assignment_id: 'assign-prepare-live',
  agent_id: 'codex-cli',
  status: 'completed',
  effective_model: 'gpt-5.4',
  effective_provider: 'openai',
  emitted_events: ['patch_ready'],
  artifacts: [{ artifact_id: 'artifact-prepare-patch', path: 'artifacts/prepare.diff' }],
  outcome_metrics: {
    wall_time_ms: 1000,
    input_tokens: 220,
    output_tokens: 80,
    total_tokens: 300,
    changed_files_count: 1,
    cost_usd: 0.012,
  },
  verification: {
    status: 'passed',
  },
  native_log_refs: [],
  mutation_proposal_refs: [],
  review_status: 'approved',
} as const;

const turnReportFixture = {
  report_id: 'turn-session-prepare-live',
  assignment_id: 'assign-prepare-live',
  agent_id: 'codex-cli',
  status: 'completed',
  tool_calls_since_last_report: 1,
  summary: 'Prepared the patch and verified the bounded handoff.',
  new_findings: [{ finding_id: 'finding-prepare-live', summary: 'Patch prepared successfully.' }],
  artifact_refs: [{ artifact_id: 'artifact-prepare-patch', path: 'artifacts/prepare.diff' }],
  blockers: [],
  suggested_ledger_updates: [{ type: 'events_emitted', events: ['patch_ready'] }],
  token_usage: { input_tokens: 220, output_tokens: 80 },
} as const;

const dispatchPacketFixture = {
  packet_id: 'packet-session-prepare-live',
  mission_id: 'demo',
  workflow_id: 'workflow-001',
  routing_decision: routingDecisionFixture,
  assignment: assignmentFixture,
  review_constraints: {
    required_gate_ids: [],
    requires_review_decision: false,
    forbid_scope_expansion: true,
    forbid_new_agents: true,
  },
  turn_report_policy: {
    after_each_tool_call: true,
    max_report_tokens: 600,
  },
} as const;

const sessionMetricsFixture = {
  entries: [
    {
      assignment_id: 'assign-prepare-live',
      status: 'completed',
      agent_id: 'codex-cli',
      role: 'producer',
      task_type: 'prepare',
      risk_level: 'medium',
      model: 'gpt-5.4',
      provider: 'openai',
      workflow_mode: 'small_dag',
      wall_time_ms: 1000,
      input_tokens: 220,
      output_tokens: 80,
      total_tokens: 300,
      cost_usd: 0.012,
      cost_source: 'observed',
      cost_confidence: 'high',
      changed_files_count: 1,
      verification_status: 'passed',
      review_status: 'approved',
      usage_confidence: 'high',
      context_policy_version: 'context-v1',
      context_capsule_tokens: 1800,
      included_fact_ids: ['finding-prepare-live'],
      included_artifact_refs: ['artifact-prepare-patch'],
      context_requests: [
        {
          reason: 'missing_test_failure_details',
          requested_refs: ['artifact-test-report-017'],
          granted_artifacts: [{ artifact_id: 'artifact-test-report-017' }],
          denied_refs: [],
          unavailable_refs: [],
          added_tokens: 620,
        },
      ],
      first_pass_success: true,
      rework_required: false,
      context_fit_classification: 'under_provisioned',
      context_fit_reason: 'Required evidence arrived only after a scoped request.',
    },
  ],
  summary: [],
  observed_budget: {
    session_count: 1,
    completed_count: 1,
    total_tokens_used: 300,
    total_cost_usd: 0.012,
    known_cost_usd_total: 0.012,
    missing_usage_count: 0,
    missing_cost_count: 0,
    observed_coordination_ratio: 0.18,
  },
  advisor_outcomes: [],
  advisor_score_summary: {
    scores: [],
    classification_counts: { good_call: 0, bad_call: 0, good_skip: 1, missed_call: 0 },
    insufficient_evidence_count: 0,
  },
  context_summary: {
    entry_count: 1,
    total_context_requests: 1,
    total_added_tokens: 620,
    fit_counts: {
      under_provisioned: 1,
      well_provisioned: 0,
      over_provisioned: 0,
      mis_scoped: 0,
      insufficient_evidence: 0,
    },
    repeated_requested_refs: [],
  },
  policy_recommendations: [],
} as const;

const aggregateMetricsFixture = {
  ...sessionMetricsFixture,
  observed_budget: {
    session_count: 3,
    completed_count: 3,
    total_tokens_used: 1800,
    total_cost_usd: 0.072,
    known_cost_usd_total: 0.072,
    missing_usage_count: 0,
    missing_cost_count: 0,
    observed_coordination_ratio: 0.18,
  },
  advisor_outcomes: [advisorOutcomeFixture],
  advisor_score_summary: {
    scores: [{ outcome_id: 'advisor-outcome-001', classification: 'good_skip' }],
    classification_counts: { good_call: 0, bad_call: 0, good_skip: 1, missed_call: 0 },
    insufficient_evidence_count: 0,
  },
  context_summary: {
    entry_count: 3,
    total_context_requests: 1,
    total_added_tokens: 620,
    fit_counts: {
      under_provisioned: 1,
      well_provisioned: 2,
      over_provisioned: 0,
      mis_scoped: 0,
      insufficient_evidence: 0,
    },
    repeated_requested_refs: [],
  },
} as const;

const ledgerFixture = {
  mission_id: 'demo',
  ledger_version: '1',
  current_goal: 'Keep the runtime workflow healthy.',
  current_plan_ref: 'plans/demo.yaml',
  public_findings: [],
  decisions: [{ id: 'decision-001' }],
  risks: [{ id: 'risk-001' }, { id: 'risk-002' }],
  artifacts: [{ id: 'artifact-001' }, { id: 'artifact-002' }, { id: 'artifact-003' }],
  broadcasts: [],
  open_questions: [],
  event_log: [],
};

const gatekeeperFixture = {
  workflow_id: 'workflow-001',
  ready: ['prepare', 'independent'],
  decisions: {
    prepare: {
      node_id: 'prepare',
      state: 'runnable',
      blocked_reasons: [],
    },
    review: {
      node_id: 'review',
      state: 'blocked',
      blocked_reasons: [
        {
          code: 'mutation_pending',
          message: 'Workflow mutation mutation-001 may invalidate node review',
          mutation_event_id: 'event-mutation-001',
        },
        {
          code: 'gate_waiting',
          message: 'Gate gate-review is waiting for verification_ready',
          missing_ref: 'verify.verification_ready',
          gate_id: 'gate-review',
        },
      ],
    },
    independent: {
      node_id: 'independent',
      state: 'completed',
      blocked_reasons: [],
    },
  },
} as const;

const replayFixture = {
  workflow_id: 'workflow-001',
  workflow_version_id: 'workflow-version-002',
  through_event_id: null,
  through_event_ordinal: null,
  terminal_complete: false,
  nodes: {
    prepare: {
      node_id: 'prepare',
      state: 'completed',
      emitted_events: ['prepare.patch_ready', 'prepare.verification_ready'],
      blocked_reasons: [],
      assignment_attempts: [
        {
          assignment_id: 'assign-prepare-1',
          node_id: 'prepare',
          state: 'completed',
          created_event_id: 'event-prepare-assigned-001',
          terminal_event_id: 'event-prepare-complete-001',
          terminal_event_type: 'completed',
        },
      ],
    },
    review: {
      node_id: 'review',
      state: 'blocked',
      emitted_events: ['review.review_complete'],
      blocked_reasons: [
        {
          code: 'mutation_pending',
          message: 'Workflow mutation mutation-001 may invalidate node review',
          mutation_event_id: 'event-mutation-001',
        },
        {
          code: 'gate_waiting',
          message: 'Gate gate-review is waiting for verification_ready',
          missing_ref: 'verify.verification_ready',
          gate_id: 'gate-review',
          assignment_id: 'assign-review-1',
        },
      ],
      assignment_attempts: [
        {
          assignment_id: 'assign-review-1',
          node_id: 'review',
          state: 'superseded',
          created_event_id: 'event-review-assigned-001',
          terminal_event_type: 'superseded',
          superseded_by: 'assign-review-2',
        },
        {
          assignment_id: 'assign-review-2',
          node_id: 'review',
          state: 'completed',
          created_event_id: 'event-review-assigned-002',
          terminal_event_id: 'event-review-complete-002',
          terminal_event_type: 'completed',
          retry_of: 'assign-review-1',
        },
      ],
    },
    independent: {
      node_id: 'independent',
      state: 'completed',
      emitted_events: ['audit.audit_complete'],
      blocked_reasons: [],
      assignment_attempts: [],
    },
  },
  mutation_proposals: {
    'event-mutation-001': {
      proposal_id: 'mutation-001',
      proposal_event_id: 'event-mutation-001',
      state: 'pending',
      affected_node_ids: ['review'],
      decision_event_id: 'event-mutation-decision-001',
    },
    'event-mutation-accepted-001': {
      proposal_id: 'mutation-002',
      proposal_event_id: 'event-mutation-accepted-001',
      state: 'accepted',
      affected_node_ids: ['prepare'],
      decision_event_id: 'event-mutation-decision-accepted-001',
    },
  },
} as const;

const replayTimelineFixture = {
  workflow_id: 'workflow-001',
  ledger_version: '1',
  initial_workflow_version_id: 'workflow-version-001',
  current_workflow_version_id: 'workflow-version-002',
  versions: [
    {
      version_id: 'workflow-version-001',
      sequence: 1,
      content_hash: 'hash-001',
    },
    {
      version_id: 'workflow-version-002',
      sequence: 2,
      content_hash: 'hash-002',
      parent_version_id: 'workflow-version-001',
      accepted_event_id: 'event-mutation-accepted-001',
    },
  ],
  events: [
    {
      event_ordinal: 1,
      event_id: 'event-mutation-001',
      event_type: 'workflow_mutation_proposed',
      active_workflow_version_id: 'workflow-version-001',
      assignment_id: 'assign-review-1',
      node_id: 'review',
      version_transition: {
        changed: false,
        workflow_version_before: 'workflow-version-001',
        workflow_version_after: 'workflow-version-001',
        parent_workflow_version_id: null,
        accepted_event_id: null,
      },
    },
    {
      event_ordinal: 2,
      event_id: 'event-mutation-accepted-001',
      event_type: 'workflow_mutation_accepted',
      active_workflow_version_id: 'workflow-version-002',
      assignment_id: 'assign-review-2',
      node_id: 'review',
      version_transition: {
        changed: true,
        workflow_version_before: 'workflow-version-001',
        workflow_version_after: 'workflow-version-002',
        parent_workflow_version_id: 'workflow-version-001',
        accepted_event_id: 'event-mutation-accepted-001',
      },
    },
  ],
} as const;

const replaySnapshotFixture = {
  workflow_id: 'workflow-001',
  cursor: {
    through_event_id: 'event-mutation-accepted-001',
    through_event_ordinal: 2,
    workflow_version_id: 'workflow-version-002',
  },
  selected_event: replayTimelineFixture.events[1],
  workflow: {
    ...mutationFixture.current_workflow,
    nodes: [
      ...mutationFixture.current_workflow.nodes,
      {
        id: 'verify',
        role: 'producer',
        waits_for: [],
        emits: ['verification_ready'],
      },
    ],
    gates: [
      ...mutationFixture.current_workflow.gates,
      {
        id: 'gate-verify',
        node_id: 'review',
        requires: ['verify.verification_ready'],
      },
    ],
  },
  replay: {
    ...replayFixture,
    workflow_version_id: 'workflow-version-002',
    through_event_id: 'event-mutation-accepted-001',
    through_event_ordinal: 2,
    nodes: {
      ...replayFixture.nodes,
      prepare: {
        ...replayFixture.nodes.prepare,
        state: 'runnable',
        assignment_attempts: [
          {
            assignment_id: 'assign-prepare-2',
            node_id: 'prepare',
            state: 'awaiting_context',
            created_event_id: 'event-prepare-assigned-002',
            retry_of: 'assign-prepare-1',
          },
        ],
      },
      review: {
        ...replayFixture.nodes.review,
        state: 'runnable',
        blocked_reasons: [],
        assignment_attempts: [
          {
            assignment_id: 'assign-review-3',
            node_id: 'review',
            state: 'awaiting_context',
            created_event_id: 'event-review-assigned-003',
            retry_of: 'assign-review-2',
          },
        ],
      },
      verify: {
        node_id: 'verify',
        state: 'runnable',
        emitted_events: [],
        blocked_reasons: [],
        assignment_attempts: [],
      },
    },
    assignment_validity: {
      'assign-prepare-1': {
        assignment_id: 'assign-prepare-1',
        node_id: 'prepare',
        creation_version_id: 'workflow-version-001',
        active_version_id: 'workflow-version-002',
        status: 'affected',
        reasons: ['workflow_version_changed'],
        transition_event_id: 'event-mutation-accepted-001',
      },
      'assign-prepare-2': {
        assignment_id: 'assign-prepare-2',
        node_id: 'prepare',
        creation_version_id: 'workflow-version-001',
        active_version_id: 'workflow-version-002',
        status: 'needs_review',
        reasons: ['awaiting_revalidation'],
        transition_event_id: 'event-mutation-accepted-001',
      },
    },
  },
  gatekeeper: {
    ...gatekeeperFixture,
    decisions: {
      ...gatekeeperFixture.decisions,
      review: {
        node_id: 'review',
        state: 'runnable',
        blocked_reasons: [],
      },
      verify: {
        node_id: 'verify',
        state: 'runnable',
        blocked_reasons: [],
      },
    },
    ready: ['prepare', 'review', 'verify'],
  },
} as const;

const replayDiffFixture = {
  workflow_id: 'workflow-001',
  from_cursor: {
    through_event_id: 'event-mutation-001',
    through_event_ordinal: 1,
    workflow_version_id: 'workflow-version-001',
  },
  to_cursor: {
    through_event_id: 'event-mutation-accepted-001',
    through_event_ordinal: 2,
    workflow_version_id: 'workflow-version-002',
  },
  events_between: [
    {
      event_ordinal: 2,
      event_id: 'event-mutation-accepted-001',
      event_type: 'workflow_mutation_accepted',
    },
  ],
  timeline_between: [replayTimelineFixture.events[1]],
  workflow_diff: {
    changed: true,
    nodes_added: [replaySnapshotFixture.workflow.nodes[3]],
    nodes_removed: [],
    nodes_changed: [],
    gates_added: [replaySnapshotFixture.workflow.gates[1]],
    gates_removed: [],
    gates_changed: [],
    terminal_events_before: ['review_complete', 'audit_complete'],
    terminal_events_after: ['review_complete', 'audit_complete'],
  },
  state_diff: {
    terminal_complete_before: false,
    terminal_complete_after: false,
    node_changes: [
      {
        node_id: 'verify',
        before: null,
        after: replaySnapshotFixture.replay.nodes.verify,
      },
      {
        node_id: 'review',
        before: replayFixture.nodes.review,
        after: replaySnapshotFixture.replay.nodes.review,
      },
    ],
    assignment_validity_changes: [
      {
        assignment_id: 'assign-prepare-1',
        before: null,
        after: replaySnapshotFixture.replay.assignment_validity['assign-prepare-1'],
      },
      {
        assignment_id: 'assign-prepare-2',
        before: null,
        after: replaySnapshotFixture.replay.assignment_validity['assign-prepare-2'],
      },
    ],
    mutation_changes: [
      {
        proposal_event_id: 'event-mutation-accepted-001',
        before: null,
        after: replayFixture.mutation_proposals['event-mutation-accepted-001'],
      },
    ],
  },
} as const;

type MockRunRecord = {
  run_id: string;
  task_id: string;
  model: string;
  status: string;
  changed_files: string[];
  verification_result: string;
  review_status: string;
  finished_at: string;
};

async function mockWorkbenchApi(
  page,
  options: {
    runs?: MockRunRecord[] | (() => MockRunRecord[]);
    stateByNode?: Record<string, string> | (() => Record<string, string>);
    onDagRequest?: (url: string) => void;
    onRunsRequest?: (url: string) => void;
    onStateRequest?: (url: string) => void;
    onValidationRequest?: (url: string) => void;
    onPromptRequest?: (taskId: string, url: string) => void;
    onReview?: (payload: unknown) => void;
    reviewResponse?: (payload: unknown) => { status?: number; body?: unknown };
    onNodeMetadata?: (payload: unknown) => void;
    nodeMetadataDelayMs?: number;
    nodeMetadataResponse?: (payload: unknown) => { status?: number; body?: unknown };
    onNodeDependencies?: (payload: unknown) => void;
    nodeDependenciesDelayMs?: number;
    nodeDependenciesResponse?: (payload: unknown) => { status?: number; body?: unknown };
    onCreateNode?: (payload: unknown) => void;
    createNodeResponse?: (payload: unknown) => { status?: number; body?: unknown };
    mutationResponse?: { status?: number; body?: unknown };
    replayResponse?: { status?: number; body?: unknown };
    replayTimelineResponse?: { status?: number; body?: unknown };
    replaySnapshotResponse?: { status?: number; body?: unknown };
    replayDiffResponse?: { status?: number; body?: unknown };
    onReplayTimelineRequest?: (url: string) => void;
    onReplaySnapshotRequest?: (url: string) => void;
    onReplayDiffRequest?: (url: string) => void;
    onMutationRequest?: (url: string) => void;
    onMutationDecision?: (payload: unknown) => void;
    mutationDecisionDelayMs?: number;
    mutationDecisionResponse?: (payload: unknown) => { status?: number; body?: unknown };
    gatekeeperResponse?: { status?: number; body?: unknown };
    routingDecisionResponse?: { status?: number; body?: unknown };
    onRoutingDecisionRequest?: (url: string) => void;
    advisorOutcomeResponse?: { status?: number; body?: unknown };
    onAdvisorOutcomeRequest?: (url: string) => void;
    nodeOutcomeResponse?: { status?: number; body?: unknown };
    onNodeOutcomeRequest?: (url: string) => void;
    assignmentResponse?: { status?: number; body?: unknown };
    onAssignmentRequest?: (url: string) => void;
    agentsResponse?: { status?: number; body?: unknown };
    onAgentsRequest?: (url: string) => void;
    agentDoctorResponse?: { status?: number; body?: unknown } | ((agentId: string) => { status?: number; body?: unknown });
    onAgentDoctorRequest?: (url: string) => void;
    contextCapsuleResponse?: { status?: number; body?: unknown };
    onContextCapsuleRequest?: (url: string) => void;
    contextRequestResponse?: { status?: number; body?: unknown };
    onContextRequest?: (url: string) => void;
    contextResolveResponse?: { status?: number; body?: unknown } | ((payload: unknown) => { status?: number; body?: unknown });
    onContextResolve?: (payload: unknown) => void;
    resultResponse?: { status?: number; body?: unknown };
    onResultRequest?: (url: string) => void;
    resultStageResponse?: { status?: number; body?: unknown } | ((payload: unknown) => { status?: number; body?: unknown });
    onResultStage?: (payload: unknown) => void;
    turnReportResponse?: { status?: number; body?: unknown };
    onTurnReportRequest?: (url: string) => void;
    dispatchPacketResponse?: { status?: number; body?: unknown };
    onDispatchPacketRequest?: (url: string) => void;
    dispatchPacketCompileResponse?: { status?: number; body?: unknown } | ((payload: unknown) => { status?: number; body?: unknown });
    onDispatchPacketCompile?: (payload: unknown) => void;
    sessionDispatchResponse?: { status?: number; body?: unknown } | ((payload: unknown) => { status?: number; body?: unknown });
    onSessionDispatch?: (payload: unknown) => void;
    runtimeDemoResponse?: { status?: number; body?: unknown } | ((payload: unknown) => { status?: number; body?: unknown });
    onRuntimeDemo?: (payload: unknown) => void;
    reviewDecisionImportResponse?: { status?: number; body?: unknown } | ((payload: unknown) => { status?: number; body?: unknown });
    onReviewDecisionImport?: (payload: unknown) => void;
    outcomeDecideResponse?: { status?: number; body?: unknown } | ((payload: unknown) => { status?: number; body?: unknown });
    onOutcomeDecide?: (payload: unknown) => void;
    metricsResponse?: { status?: number; body?: unknown } | ((url: string) => { status?: number; body?: unknown });
    onMetricsRequest?: (url: string) => void;
    artifactManifestResponse?: { status?: number; body?: unknown };
    onArtifactManifestRequest?: (url: string) => void;
    onGatekeeperRequest?: (url: string) => void;
    missionResponse?: { status?: number; body?: unknown };
    onMissionRequest?: (url: string) => void;
    ledgerResponse?: { status?: number; body?: unknown };
    onLedgerRequest?: (url: string) => void;
    dagResponse?: { status?: number; body?: unknown } | (() => { status?: number; body?: unknown });
    validationResponse?: { status?: number; body?: unknown } | (() => { status?: number; body?: unknown });
  } = {},
) {
  const getRuns =
    typeof options.runs === 'function'
      ? options.runs
      : () => options.runs ?? [];
  const getStateByNode =
    typeof options.stateByNode === 'function'
      ? options.stateByNode
      : () =>
          options.stateByNode ?? {
            'baseline-inventory': 'ready',
            'worker-stop-lifecycle': 'blocked',
          };

  await page.route('**/api/dag?**', async (route) => {
    options.onDagRequest?.(route.request().url());
    const response =
      typeof options.dagResponse === 'function'
        ? options.dagResponse()
        : options.dagResponse;
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(response?.body ?? dagFixture),
    });
  });

  await page.route('**/api/validate?**', async (route) => {
    options.onValidationRequest?.(route.request().url());
    const response =
      typeof options.validationResponse === 'function'
        ? options.validationResponse()
        : options.validationResponse;
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(response?.body ?? { ok: true, errors: [] }),
    });
  });

  await page.route('**/api/prompt/**', async (route) => {
    const taskId = route.request().url().split('/api/prompt/')[1]?.split('?')[0] ?? 'unknown';
    options.onPromptRequest?.(decodeURIComponent(taskId), route.request().url());
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: decodeURIComponent(taskId),
        prompt: `Prompt for ${decodeURIComponent(taskId)}`,
      }),
    });
  });

  await page.route('**/api/runs?**', async (route) => {
    options.onRunsRequest?.(route.request().url());
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ runs: getRuns() }),
    });
  });

  await page.route('**/api/state?**', async (route) => {
    options.onStateRequest?.(route.request().url());
    const stateByNode = getStateByNode();
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        states: stateByNode,
        ready: Object.entries(stateByNode)
          .filter(([, value]) => value === 'ready')
          .map(([nodeId]) => nodeId),
      }),
    });
  });

  await page.route('**/api/mutations?**', async (route) => {
    options.onMutationRequest?.(route.request().url());
    await route.fulfill({
      status: options.mutationResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(
        options.mutationResponse?.body ?? { workflow_id: 'workflow-001', proposals: [] },
      ),
    });
  });

  await page.route('**/api/replay?**', async (route) => {
    await route.fulfill({
      status: options.replayResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.replayResponse?.body ?? replayFixture),
    });
  });

  await page.route('**/api/replay/timeline?**', async (route) => {
    options.onReplayTimelineRequest?.(route.request().url());
    await route.fulfill({
      status: options.replayTimelineResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.replayTimelineResponse?.body ?? replayTimelineFixture),
    });
  });

  await page.route('**/api/replay/snapshot?**', async (route) => {
    options.onReplaySnapshotRequest?.(route.request().url());
    await route.fulfill({
      status: options.replaySnapshotResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.replaySnapshotResponse?.body ?? replaySnapshotFixture),
    });
  });

  await page.route('**/api/replay/diff?**', async (route) => {
    options.onReplayDiffRequest?.(route.request().url());
    await route.fulfill({
      status: options.replayDiffResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.replayDiffResponse?.body ?? replayDiffFixture),
    });
  });

  await page.route('**/api/mission?**', async (route) => {
    options.onMissionRequest?.(route.request().url());
    await route.fulfill({
      status: options.missionResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.missionResponse?.body ?? missionFixture),
    });
  });

  await page.route('**/api/artifact-session-manifest?**', async (route) => {
    options.onArtifactManifestRequest?.(route.request().url());
    await route.fulfill({
      status: options.artifactManifestResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.artifactManifestResponse?.body ?? artifactManifestFixture),
    });
  });

  await page.route('**/api/routing-decision?**', async (route) => {
    options.onRoutingDecisionRequest?.(route.request().url());
    await route.fulfill({
      status: options.routingDecisionResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.routingDecisionResponse?.body ?? routingDecisionFixture),
    });
  });

  await page.route('**/api/advisor-outcome?**', async (route) => {
    options.onAdvisorOutcomeRequest?.(route.request().url());
    await route.fulfill({
      status: options.advisorOutcomeResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.advisorOutcomeResponse?.body ?? advisorOutcomeFixture),
    });
  });

  await page.route('**/api/node-outcome?**', async (route) => {
    options.onNodeOutcomeRequest?.(route.request().url());
    await route.fulfill({
      status: options.nodeOutcomeResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.nodeOutcomeResponse?.body ?? nodeOutcomeFixture),
    });
  });

  await page.route('**/api/assignment?**', async (route) => {
    options.onAssignmentRequest?.(route.request().url());
    await route.fulfill({
      status: options.assignmentResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.assignmentResponse?.body ?? assignmentFixture),
    });
  });

  await page.route('**/api/agents', async (route) => {
    options.onAgentsRequest?.(route.request().url());
    await route.fulfill({
      status: options.agentsResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.agentsResponse?.body ?? agentsFixture),
    });
  });

  await page.route('**/api/agents/*/doctor', async (route) => {
    options.onAgentDoctorRequest?.(route.request().url());
    const agentId = route.request().url().split('/api/agents/')[1]?.split('/doctor')[0] ?? 'unknown';
    const response =
      typeof options.agentDoctorResponse === 'function'
        ? options.agentDoctorResponse(decodeURIComponent(agentId))
        : options.agentDoctorResponse;
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(response?.body ?? agentDoctorFixture),
    });
  });

  await page.route('**/api/context-capsule?**', async (route) => {
    options.onContextCapsuleRequest?.(route.request().url());
    await route.fulfill({
      status: options.contextCapsuleResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.contextCapsuleResponse?.body ?? contextCapsuleFixture),
    });
  });

  await page.route('**/api/context-request?**', async (route) => {
    options.onContextRequest?.(route.request().url());
    await route.fulfill({
      status: options.contextRequestResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.contextRequestResponse?.body ?? {
        context_request_id: 'ctxreq-001',
        assignment_id: 'assign-prepare-live',
        missing_information: 'Need the test failure details artifact.',
        requested_refs: ['artifact-test-report-017'],
        expected_value: 'Use the accepted test report instead of guessing the failure.',
      }),
    });
  });

  await page.route('**/api/context-request/resolve', async (route) => {
    const payload = route.request().postDataJSON();
    options.onContextResolve?.(payload);
    const response =
      typeof options.contextResolveResponse === 'function'
        ? options.contextResolveResponse(payload)
        : options.contextResolveResponse;
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(response?.body ?? contextResolutionFixture),
    });
  });

  await page.route('**/api/result?**', async (route) => {
    options.onResultRequest?.(route.request().url());
    await route.fulfill({
      status: options.resultResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.resultResponse?.body ?? resultFixture),
    });
  });

  await page.route('**/api/result/stage', async (route) => {
    const payload = route.request().postDataJSON();
    options.onResultStage?.(payload);
    const response =
      typeof options.resultStageResponse === 'function'
        ? options.resultStageResponse(payload)
        : options.resultStageResponse;
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(response?.body ?? resultStageFixture),
    });
  });

  await page.route('**/api/turn-report?**', async (route) => {
    options.onTurnReportRequest?.(route.request().url());
    await route.fulfill({
      status: options.turnReportResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.turnReportResponse?.body ?? turnReportFixture),
    });
  });

  await page.route('**/api/dispatch-packet?**', async (route) => {
    options.onDispatchPacketRequest?.(route.request().url());
    await route.fulfill({
      status: options.dispatchPacketResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.dispatchPacketResponse?.body ?? dispatchPacketFixture),
    });
  });

  await page.route('**/api/dispatch-packet/compile', async (route) => {
    const payload = route.request().postDataJSON();
    options.onDispatchPacketCompile?.(payload);
    const response =
      typeof options.dispatchPacketCompileResponse === 'function'
        ? options.dispatchPacketCompileResponse(payload)
        : options.dispatchPacketCompileResponse;
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(response?.body ?? dispatchCompileFixture),
    });
  });

  await page.route('**/api/session/dispatch', async (route) => {
    const payload = route.request().postDataJSON();
    options.onSessionDispatch?.(payload);
    const response =
      typeof options.sessionDispatchResponse === 'function'
        ? options.sessionDispatchResponse(payload)
        : options.sessionDispatchResponse;
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(response?.body ?? sessionDispatchFixture),
    });
  });

  await page.route('**/api/runtime-demo', async (route) => {
    const payload = route.request().postDataJSON();
    options.onRuntimeDemo?.(payload);
    const response =
      typeof options.runtimeDemoResponse === 'function'
        ? options.runtimeDemoResponse(payload)
        : options.runtimeDemoResponse;
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(response?.body ?? runtimeDemoFixture),
    });
  });

  await page.route('**/api/review-decision/import', async (route) => {
    const payload = route.request().postDataJSON();
    options.onReviewDecisionImport?.(payload);
    const response =
      typeof options.reviewDecisionImportResponse === 'function'
        ? options.reviewDecisionImportResponse(payload)
        : options.reviewDecisionImportResponse;
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(response?.body ?? reviewImportFixture),
    });
  });

  await page.route('**/api/outcome/decide', async (route) => {
    const payload = route.request().postDataJSON();
    options.onOutcomeDecide?.(payload);
    const response =
      typeof options.outcomeDecideResponse === 'function'
        ? options.outcomeDecideResponse(payload)
        : options.outcomeDecideResponse;
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(response?.body ?? outcomeDecideFixture),
    });
  });

  await page.route('**/api/metrics?**', async (route) => {
    const url = route.request().url();
    options.onMetricsRequest?.(url);
    const response =
      typeof options.metricsResponse === 'function'
        ? options.metricsResponse(url)
        : options.metricsResponse;
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(
        response?.body ??
          (url.includes(encodeURIComponent('metrics_summary.yaml'))
            ? aggregateMetricsFixture
            : sessionMetricsFixture),
      ),
    });
  });

  await page.route('**/api/ledger?**', async (route) => {
    options.onLedgerRequest?.(route.request().url());
    await route.fulfill({
      status: options.ledgerResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.ledgerResponse?.body ?? ledgerFixture),
    });
  });

  await page.route('**/api/mutations/decision', async (route) => {
    const payload = route.request().postDataJSON();
    options.onMutationDecision?.(payload);
    if (options.mutationDecisionDelayMs) {
      await new Promise((resolve) => setTimeout(resolve, options.mutationDecisionDelayMs));
    }
    const response = options.mutationDecisionResponse?.(payload);
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(response?.body ?? { workflow_id: 'workflow-001', proposals: [] }),
    });
  });

  await page.route('**/api/gatekeeper?**', async (route) => {
    options.onGatekeeperRequest?.(route.request().url());
    await route.fulfill({
      status: options.gatekeeperResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.gatekeeperResponse?.body ?? gatekeeperFixture),
    });
  });

  await page.route('**/api/review', async (route) => {
    const payload = route.request().postDataJSON();
    options.onReview?.(payload);
    const response = options.reviewResponse?.(payload);
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(response?.body ?? { path: 'runs/review-updated.yaml' }),
    });
  });

  await page.route('**/api/dag/node-metadata', async (route) => {
    const payload = route.request().postDataJSON();
    options.onNodeMetadata?.(payload);
    if (options.nodeMetadataDelayMs) {
      await new Promise((resolve) => setTimeout(resolve, options.nodeMetadataDelayMs));
    }
    const response = options.nodeMetadataResponse?.(payload);
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(
        response?.body ?? {
          path: 'examples/optimization_dag.yaml',
          backup_path: 'examples/optimization_dag.yaml.20260624T000000Z.bak',
          node: dagFixture.nodes[0],
        },
      ),
    });
  });

  await page.route('**/api/dag/node-dependencies', async (route) => {
    const payload = route.request().postDataJSON();
    options.onNodeDependencies?.(payload);
    if (options.nodeDependenciesDelayMs) {
      await new Promise((resolve) => setTimeout(resolve, options.nodeDependenciesDelayMs));
    }
    const response = options.nodeDependenciesResponse?.(payload);
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(
        response?.body ?? {
          path: 'examples/optimization_dag.yaml',
          backup_path: 'examples/optimization_dag.yaml.20260624T000000Z.bak',
          node: dagFixture.nodes[0],
        },
      ),
    });
  });

  await page.route('**/api/dag/nodes', async (route) => {
    const payload = route.request().postDataJSON();
    options.onCreateNode?.(payload);
    const response = options.createNodeResponse?.(payload);
    const fallbackNode = (payload as { node?: unknown }).node ?? dagFixture.nodes[0];
    await route.fulfill({
      status: response?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(
        response?.body ?? {
          path: 'examples/optimization_dag.yaml',
          backup_path: 'examples/optimization_dag.yaml.20260624T000000Z.bak',
          node: fallbackNode,
        },
      ),
    });
  });
}

async function dragGraphConnection(page: Page, sourceId: string, targetId: string) {
  const sourceHandle = page.locator(`.react-flow__node[data-id="${sourceId}"] .react-flow__handle.source`).first();
  const targetHandle = page.locator(`.react-flow__node[data-id="${targetId}"] .react-flow__handle.target`).first();
  await expect(sourceHandle).toBeVisible();
  await expect(targetHandle).toBeVisible();

  const sourceBox = await sourceHandle.boundingBox();
  const targetBox = await targetHandle.boundingBox();
  expect(sourceBox).not.toBeNull();
  expect(targetBox).not.toBeNull();
  if (!sourceBox || !targetBox) {
    throw new Error(`Unable to locate graph handles for ${sourceId}->${targetId}`);
  }

  await page.mouse.move(sourceBox.x + sourceBox.width / 2, sourceBox.y + sourceBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(targetBox.x + targetBox.width / 2, targetBox.y + targetBox.height / 2, { steps: 12 });
  await page.mouse.up();
}

async function graphNodeBox(page: Page, title: string) {
  const box = await page
    .locator('.react-flow__node')
    .filter({ hasText: title })
    .boundingBox();
  expect(box).not.toBeNull();
  return box!;
}

async function waitForGraphNodeBox(page: Page, title: string) {
  let previous = await graphNodeBox(page, title);
  for (let attempt = 0; attempt < 10; attempt += 1) {
    await page.waitForTimeout(80);
    const current = await graphNodeBox(page, title);
    const distance =
      Math.abs(current.x - previous.x) +
      Math.abs(current.y - previous.y) +
      Math.abs(current.width - previous.width) +
      Math.abs(current.height - previous.height);
    if (distance < 1) {
      return current;
    }
    previous = current;
  }
  return previous;
}

async function graphHandleBox(page: Page, nodeId: string, handleClass: 'source' | 'target') {
  const box = await page.locator(`.react-flow__node[data-id="${nodeId}"] .react-flow__handle.${handleClass}`).first().boundingBox();
  expect(box).not.toBeNull();
  return box!;
}

async function dragFlowNode(page: Page, nodeId: string, deltaX: number, deltaY: number) {
  const node = page.locator(`.react-flow__node[data-id="${nodeId}"]`).first();
  await expect(node).toBeVisible();

  const box = await node.boundingBox();
  expect(box).not.toBeNull();
  if (!box) {
    throw new Error(`Unable to locate node ${nodeId}`);
  }

  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + deltaX, box.y + box.height / 2 + deltaY, { steps: 14 });
  await page.mouse.up();
}

async function dragFlowNodeWithPreview(page: Page, nodeId: string, deltaX: number, deltaY: number) {
  const node = page.locator(`.react-flow__node[data-id="${nodeId}"]`).first();
  await expect(node).toBeVisible();

  const box = await node.boundingBox();
  expect(box).not.toBeNull();
  if (!box) {
    throw new Error(`Unable to locate node ${nodeId}`);
  }

  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + deltaX, box.y + box.height / 2 + deltaY, { steps: 12 });
  await expect(page.locator('.graph-drag-preview')).toBeVisible();
  await expect(page.locator('.graph-drag-placeholder')).toBeVisible();
  await page.mouse.up();
}

test('renders DAG workbench and node inspector', async ({ page }) => {
  await mockWorkbenchApi(page);
  await page.goto('/');

  await expect(page.getByRole('button', { name: 'Planning DAG' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText('BureauLess')).toBeVisible();
  await expect(page.getByText('Baseline Inventory').first()).toBeVisible();
  await expect(page.getByText('Worker Stop Lifecycle').first()).toBeVisible();

  await page.getByRole('button', { name: /worker stop lifecycle/i }).click();

  await expect(page.getByRole('heading', { name: 'worker-stop-lifecycle' })).toBeVisible();
  await expect(page.getByText('risk: high')).toBeVisible();
  await expect(page.getByText('gpt-5.4').first()).toBeVisible();
  await expect(page.getByText('human_review').first()).toBeVisible();
});

test('uses horizontal handles and lets graph nodes be dragged, persisted, and reset', async ({ page }) => {
  await mockWorkbenchApi(page);
  await page.goto('/');

  const before = await waitForGraphNodeBox(page, 'Baseline Inventory');
  const targetHandle = await graphHandleBox(page, 'baseline-inventory', 'target');
  const sourceHandle = await graphHandleBox(page, 'baseline-inventory', 'source');

  expect(targetHandle.x + targetHandle.width / 2).toBeLessThan(before.x + before.width / 2);
  expect(sourceHandle.x + sourceHandle.width / 2).toBeGreaterThan(before.x + before.width / 2);

  await dragFlowNodeWithPreview(page, 'baseline-inventory', 140, 90);
  const after = await graphNodeBox(page, 'Baseline Inventory');

  expect(Math.abs(after.x - before.x) + Math.abs(after.y - before.y)).toBeGreaterThan(40);

  await expect
    .poll(() =>
      page.evaluate(() => window.localStorage.getItem('bureauless.graphNodePositions:examples/optimization_dag.yaml')),
    )
    .not.toBeNull();

  const storedPositions = await page.evaluate(() =>
    JSON.parse(window.localStorage.getItem('bureauless.graphNodePositions:examples/optimization_dag.yaml') ?? '{}'),
  );

  expect(storedPositions).toHaveProperty('baseline-inventory');
  expect(typeof storedPositions['baseline-inventory'].x).toBe('number');
  expect(typeof storedPositions['baseline-inventory'].y).toBe('number');

  await page.getByRole('button', { name: 'Reset layout' }).click();

  await expect
    .poll(() =>
      page.evaluate(() => window.localStorage.getItem('bureauless.graphNodePositions:examples/optimization_dag.yaml')),
    )
    .toBeNull();

  const reset = await waitForGraphNodeBox(page, 'Baseline Inventory');
  expect(Math.abs(reset.x - before.x) + Math.abs(reset.y - before.y)).toBeLessThan(8);
  await expect(page.getByRole('button', { name: 'Reset layout' })).toBeDisabled();
});

test('copies the selected prompt and previews every ready node prompt', async ({ page }) => {
  const requestedPrompts: string[] = [];

  await page.addInitScript(() => {
    (window as typeof window & { __copiedPrompts?: string[] }).__copiedPrompts = [];
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (text: string) => {
          (window as typeof window & { __copiedPrompts?: string[] }).__copiedPrompts?.push(text);
        },
      },
    });
  });

  await mockWorkbenchApi(page, {
    stateByNode: {
      'baseline-inventory': 'ready',
      'worker-stop-lifecycle': 'ready',
    },
    onPromptRequest: (taskId) => {
      requestedPrompts.push(taskId);
    },
  });

  await page.goto('/');
  await page.locator('.ready-item').filter({ hasText: 'worker-stop-lifecycle' }).click();

  await expect(page.getByRole('heading', { name: 'Prompt Export Panel' })).toBeVisible();
  await expect(page.locator('.prompt-export-card').filter({ hasText: 'Selected node' }).getByText('Prompt for worker-stop-lifecycle')).toBeVisible();
  await expect(
    page.locator('.prompt-export-batch .prompt-export-card').filter({ hasText: 'baseline-inventory' }).getByText('Prompt for baseline-inventory'),
  ).toBeVisible();
  await expect(
    page.locator('.prompt-export-batch .prompt-export-card').filter({ hasText: 'worker-stop-lifecycle' }).getByText('Prompt for worker-stop-lifecycle'),
  ).toBeVisible();

  await page.getByRole('button', { name: 'Copy selected prompt' }).click();

  await expect.poll(async () =>
    page.evaluate(() => (window as typeof window & { __copiedPrompts?: string[] }).__copiedPrompts ?? []),
  ).toEqual(['Prompt for worker-stop-lifecycle']);
  await expect.poll(() => requestedPrompts.slice().sort()).toEqual([
    'baseline-inventory',
    'worker-stop-lifecycle',
  ]);
});

test('renders assignment matrix with parallel-ready and high-risk signals', async ({ page }) => {
  const matrixDag = structuredClone(dagFixture);
  matrixDag.nodes.push({
    id: 'api-contract-audit',
    title: 'API Contract Audit',
    goal: 'Audit public API contracts before workers start.',
    dependencies: [],
    target_files: ['src/api/client.ts'],
    context_files: [],
    allowed_models: ['gpt-5.4-mini'],
    recommended_model: 'gpt-5.4-mini',
    risk_level: 'medium',
    review_gate: 'orchestrator_review',
    acceptance_criteria: ['API contract drift is documented'],
    verification_commands: ['npm run web:build'],
    do_not: ['Do not change backend files'],
    prompt_template: 'Audit API contracts',
    failure_policy: 'send_to_human',
    outputs: [],
    tags: [],
  });

  await mockWorkbenchApi(page, {
    dagResponse: { body: matrixDag },
    stateByNode: {
      'baseline-inventory': 'ready',
      'api-contract-audit': 'ready',
      'worker-stop-lifecycle': 'blocked',
    },
  });

  await page.goto('/');

  const matrix = page.getByRole('table', { name: 'Assignment Matrix' });
  await expect(page.getByText('Assignment Matrix')).toBeVisible();
  await expect(matrix.getByRole('columnheader', { name: 'Node' })).toBeVisible();
  await expect(matrix.getByRole('columnheader', { name: 'Recommended model' })).toBeVisible();
  await expect(matrix.getByRole('columnheader', { name: 'Risk' })).toBeVisible();
  await expect(matrix.getByRole('columnheader', { name: 'State' })).toBeVisible();
  await expect(page.locator('.parallel-ready-batch')).toContainText('2 ready nodes can run in parallel');
  await expect(page.locator('.assignment-row.ready-row')).toHaveCount(2);
  await expect(page.locator('.assignment-row.risk-high')).toContainText('Worker Stop Lifecycle');
  await expect(matrix.getByText('ready to run')).toHaveCount(2);

  await matrix.getByRole('button', { name: /open assignment worker-stop-lifecycle/i }).click();

  await expect(page.getByRole('heading', { name: 'worker-stop-lifecycle' })).toBeVisible();
});

test('shows review actions for passed runs and refreshes state after approve', async ({ page }) => {
  const workerRun = {
    run_id: 'run-worker-stop-lifecycle-001',
    task_id: 'worker-stop-lifecycle',
    model: 'gpt-5.4-mini',
    status: 'passed',
    changed_files: ['src/worker.ts'],
    verification_result: 'passed',
    review_status: 'pending',
    finished_at: '2026-06-24T00:00:00Z',
  };
  let reviewStatus = 'pending';

  await mockWorkbenchApi(page, {
    runs: () => [{ ...workerRun, review_status: reviewStatus }],
    stateByNode: () => ({
      'baseline-inventory': 'ready',
      'worker-stop-lifecycle': reviewStatus === 'pending' ? 'needs_review' : 'completed',
    }),
    onReview: (payload) => {
      expect(payload).toMatchObject({
        dag_path: 'examples/optimization_dag.yaml',
        runs_dir: 'runs',
        task_id: 'worker-stop-lifecycle',
        review_status: 'human_approved',
      });
      reviewStatus = 'human_approved';
    },
  });

  await page.goto('/');

  await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0);

  await page.getByRole('button', { name: /worker stop lifecycle/i }).click();

  await expect(page.getByRole('button', { name: 'Approve' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Reject' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Mark Pending' })).toBeVisible();

  await page.getByRole('button', { name: 'Approve' }).click();

  await expect(page.getByText('completed').first()).toBeVisible();
  await expect(page.getByRole('main').getByText('human_approved')).toBeVisible();
});

test('defaults to the latest run and lets review target an older selected run', async ({ page }) => {
  const latestRun = {
    run_id: 'run-worker-stop-lifecycle-002',
    task_id: 'worker-stop-lifecycle',
    model: 'gpt-5.4-mini',
    status: 'passed',
    changed_files: ['src/worker.ts'],
    verification_result: 'passed',
    review_status: 'pending',
    finished_at: '2026-06-24T02:00:00Z',
  };
  const olderRun = {
    run_id: 'run-worker-stop-lifecycle-001',
    task_id: 'worker-stop-lifecycle',
    model: 'gpt-5.4-mini',
    status: 'passed',
    changed_files: ['src/legacy-worker.ts'],
    verification_result: 'passed',
    review_status: 'pending',
    finished_at: '2026-06-24T01:00:00Z',
  };
  let reviewStatusByRun: Record<string, string> = {
    [latestRun.run_id]: latestRun.review_status,
    [olderRun.run_id]: olderRun.review_status,
  };

  await mockWorkbenchApi(page, {
    runs: () => [
      { ...latestRun, review_status: reviewStatusByRun[latestRun.run_id] },
      { ...olderRun, review_status: reviewStatusByRun[olderRun.run_id] },
    ],
    stateByNode: () => ({
      'baseline-inventory': 'ready',
      'worker-stop-lifecycle': 'needs_review',
    }),
    onReview: (payload) => {
      expect(payload).toMatchObject({
        dag_path: 'examples/optimization_dag.yaml',
        runs_dir: 'runs',
        task_id: 'worker-stop-lifecycle',
        run_id: olderRun.run_id,
        review_status: 'human_approved',
      });
      reviewStatusByRun = {
        ...reviewStatusByRun,
        [olderRun.run_id]: 'human_approved',
      };
    },
  });

  await page.goto('/');
  await page.getByRole('button', { name: /worker stop lifecycle/i }).click();

  await expect(page.getByText(`Selected run: ${latestRun.run_id}`)).toBeVisible();
  await expect(
    page.locator('section').filter({ hasText: 'Run Details' }).getByText('src/worker.ts'),
  ).toBeVisible();

  await page.getByRole('button', { name: new RegExp(olderRun.run_id) }).click();

  await expect(page.getByText(`Selected run: ${olderRun.run_id}`)).toBeVisible();
  await expect(
    page.locator('section').filter({ hasText: 'Run Details' }).getByText('src/legacy-worker.ts'),
  ).toBeVisible();

  await page.getByRole('button', { name: 'Approve' }).click();

  await expect(page.getByRole('main').getByText('human_approved')).toBeVisible();
});

test('creates a new node and refreshes the DAG list', async ({ page }) => {
  const dagState = structuredClone(dagFixture);

  await mockWorkbenchApi(page, {
    dagResponse: () => ({ body: dagState }),
    stateByNode: () => ({
      'baseline-inventory': 'ready',
      'worker-stop-lifecycle': 'blocked',
      ...(dagState.nodes.some((node) => node.id === 'integration-review')
        ? { 'integration-review': 'blocked' }
        : {}),
    }),
    onCreateNode: (payload) => {
      expect(payload).toMatchObject({
        dag_path: 'examples/optimization_dag.yaml',
        node: {
          id: 'integration-review',
          recommended_model: 'gpt-5.4',
          risk_level: 'medium',
          review_gate: 'orchestrator_review',
        },
      });
      const createdNode = (payload as { node: (typeof dagFixture.nodes)[number] }).node;
      dagState.nodes.push(createdNode);
      dagState.edges.push({
        id: 'worker-stop-lifecycle->integration-review',
        source: 'worker-stop-lifecycle',
        target: 'integration-review',
      });
    },
  });

  await page.goto('/');

  await page.getByRole('button', { name: /add node/i }).click();
  await expect(page.locator('.inspector .pane-title').getByText('Create Node')).toBeVisible();

  await page.getByLabel('ID').fill('integration-review');
  await page.getByLabel('Title').fill('Integration Review');
  await page.getByLabel('Goal').fill('Review finished task outputs.');
  await page.getByLabel('Allowed models').fill('gpt-5.4');
  await page.getByLabel('Recommended model').fill('gpt-5.4');
  await page.getByLabel('Risk level').selectOption('medium');
  await page.getByLabel('Review gate').selectOption('orchestrator_review');
  await page.getByLabel('Failure policy').selectOption('send_to_human');
  await page.getByLabel('Dependencies').fill('worker-stop-lifecycle');
  await page.getByLabel('Target files').fill('docs/review.md');
  await page.getByLabel('Acceptance criteria').fill('Review report exists');
  await page.getByLabel('Verification commands').fill('pytest -q');
  await page.getByLabel('Do not').fill('Do not merge unreviewed work');
  await page.getByLabel('Prompt template').fill('Review ${id}');
  await page.getByLabel('Outputs', { exact: true }).fill('review-report');
  await page.getByLabel('Tags').fill('review');

  await page.getByRole('button', { name: 'Create node' }).click();

  await expect(page.getByRole('heading', { name: 'integration-review' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'DAG nodes' }).getByText('Integration Review')).toBeVisible();
});

test('shows create-node errors inline when the API rejects the payload', async ({ page }) => {
  await mockWorkbenchApi(page, {
    createNodeResponse: () => ({
      status: 400,
      body: {
        error: 'Task node is missing required fields: goal',
      },
    }),
  });

  await page.goto('/');
  await page.getByRole('button', { name: /add node/i }).click();

  await page.getByLabel('ID').fill('integration-review');
  await page.getByLabel('Title').fill('Integration Review');
  await page.getByLabel('Allowed models').fill('gpt-5.4');
  await page.getByLabel('Recommended model').fill('gpt-5.4');
  await page.getByLabel('Target files').fill('docs/review.md');
  await page.getByLabel('Acceptance criteria').fill('Review report exists');
  await page.getByLabel('Prompt template').fill('Review ${id}');

  await page.getByRole('button', { name: 'Create node' }).click();

  await expect(page.getByText(/Node creation failed:/)).toBeVisible();
  await expect(page.getByText(/missing required fields: goal/i)).toBeVisible();
});

test('shows inline review errors and retries without losing the selected run', async ({ page }) => {
  const workerRun = {
    run_id: 'run-worker-stop-lifecycle-003',
    task_id: 'worker-stop-lifecycle',
    model: 'gpt-5.4-mini',
    status: 'passed',
    changed_files: ['src/worker.ts'],
    verification_result: 'passed',
    review_status: 'pending',
    finished_at: '2026-06-24T03:00:00Z',
  };
  let reviewStatus = 'pending';
  let attemptCount = 0;

  await mockWorkbenchApi(page, {
    runs: () => [{ ...workerRun, review_status: reviewStatus }],
    stateByNode: () => ({
      'baseline-inventory': 'ready',
      'worker-stop-lifecycle': reviewStatus === 'pending' ? 'needs_review' : 'completed',
    }),
    onReview: (payload) => {
      expect(payload).toMatchObject({
        task_id: 'worker-stop-lifecycle',
        run_id: workerRun.run_id,
        review_status: 'human_approved',
      });
      attemptCount += 1;
      if (attemptCount > 1) {
        reviewStatus = 'human_approved';
      }
    },
    reviewResponse: () =>
      attemptCount === 1
        ? { status: 500, body: { error: 'simulated-review-failure' } }
        : { status: 200, body: { path: 'runs/review-updated.yaml' } },
  });

  await page.goto('/');
  await page.getByRole('button', { name: /worker stop lifecycle/i }).click();

  await expect(page.getByText(`Selected run: ${workerRun.run_id}`)).toBeVisible();
  await expect(page.locator('section').filter({ hasText: 'Run Details' }).getByText(workerRun.run_id)).toBeVisible();

  await page.getByRole('button', { name: 'Approve' }).click();

  await expect(page.getByRole('alert')).toContainText('Review update failed');
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();
  await expect(page.getByText(`Selected run: ${workerRun.run_id}`)).toBeVisible();
  await expect(page.locator('section').filter({ hasText: 'Run Details' }).getByText(workerRun.run_id)).toBeVisible();
  await expect(page.getByText('needs_review').first()).toBeVisible();

  await page.getByRole('button', { name: 'Retry' }).click();

  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByRole('main').getByText('human_approved')).toBeVisible();
});

test('shows diagnostics for validation errors while keeping the graph visible', async ({ page }) => {
  await mockWorkbenchApi(page, {
    validationResponse: {
      body: {
        ok: false,
        errors: [
          {
            code: 'unknown_dependency',
            message: "worker-stop-lifecycle: unknown dependency 'missing-node'",
            node_id: 'worker-stop-lifecycle',
            dependency: 'missing-node',
          },
        ],
      },
    },
  });

  await page.goto('/');

  await expect(page.getByText('1 validation issue')).toBeVisible();
  await expect(page.getByText('worker-stop-lifecycle depends on missing missing-node')).toBeVisible();
  await expect(page.getByText('Worker Stop Lifecycle').first()).toBeVisible();
});

test('edits node metadata, disables save in flight, and refreshes the risk badge', async ({ page }) => {
  let currentDag = JSON.parse(JSON.stringify(dagFixture));

  await mockWorkbenchApi(page, {
    dagResponse: () => ({ body: currentDag }),
    nodeMetadataDelayMs: 150,
    onNodeMetadata: (payload) => {
      expect(payload).toMatchObject({
        dag_path: 'examples/optimization_dag.yaml',
        task_id: 'worker-stop-lifecycle',
        updates: {
          recommended_model: 'gpt-5.4',
          risk_level: 'medium',
          review_gate: 'human_review',
          failure_policy: 'send_to_human',
          tags: [],
        },
      });

      currentDag = {
        ...currentDag,
        nodes: currentDag.nodes.map((node) =>
          node.id === 'worker-stop-lifecycle'
            ? { ...node, risk_level: 'medium' }
            : node,
        ),
      };
    },
    nodeMetadataResponse: () => ({
      body: {
        path: 'examples/optimization_dag.yaml',
        backup_path: 'examples/optimization_dag.yaml.20260624T000000Z.bak',
        node: currentDag.nodes.find((node) => node.id === 'worker-stop-lifecycle'),
      },
    }),
  });

  await page.goto('/');
  await page.getByRole('button', { name: /worker stop lifecycle/i }).click();

  await expect(page.getByText('risk: high')).toBeVisible();

  await page.getByRole('button', { name: /edit metadata/i }).click();
  await page.getByLabel('Risk level').selectOption('low');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();

  await page.getByRole('button', { name: /edit metadata/i }).click();
  await expect(page.getByLabel('Risk level')).toHaveValue('high');
  await page.getByLabel('Risk level').selectOption('medium');

  const saveButton = page.getByRole('button', { name: 'Save' });
  await saveButton.click();

  await expect(saveButton).toBeDisabled();
  await expect(page.getByText('risk: medium')).toBeVisible();
  await expect(page.getByRole('button', { name: /edit metadata/i })).toBeVisible();
});

test('edits node dependencies, refreshes DAG and validation state, and redraws graph edges', async ({ page }) => {
  let currentDag = JSON.parse(JSON.stringify(dagFixture));
  currentDag.nodes.push({
    id: 'integration-review',
    title: 'Integration Review',
    goal: 'Review integrated behavior.',
    dependencies: [],
    target_files: ['docs/integration-review.md'],
    context_files: [],
    allowed_models: ['gpt-5.4'],
    recommended_model: 'gpt-5.4',
    risk_level: 'medium',
    review_gate: 'orchestrator_review',
    acceptance_criteria: ['Integration review is captured'],
    verification_commands: ['pytest -q'],
    do_not: ['Do not skip the review'],
    prompt_template: 'Integration review prompt',
    failure_policy: 'send_to_human',
    outputs: [],
    tags: [],
  });

  let dagRequestCount = 0;
  let stateRequestCount = 0;
  let validationRequestCount = 0;

  await mockWorkbenchApi(page, {
    dagResponse: () => ({ body: currentDag }),
    onDagRequest: () => {
      dagRequestCount += 1;
    },
    onStateRequest: () => {
      stateRequestCount += 1;
    },
    onValidationRequest: () => {
      validationRequestCount += 1;
    },
    stateByNode: () => ({
      'baseline-inventory': 'ready',
      'worker-stop-lifecycle': 'blocked',
      'integration-review': 'ready',
    }),
    nodeDependenciesDelayMs: 150,
    onNodeDependencies: (payload) => {
      expect(payload).toMatchObject({
        dag_path: 'examples/optimization_dag.yaml',
        task_id: 'worker-stop-lifecycle',
        dependencies: ['baseline-inventory', 'integration-review'],
      });

      currentDag = {
        ...currentDag,
        nodes: currentDag.nodes.map((node) =>
          node.id === 'worker-stop-lifecycle'
            ? { ...node, dependencies: ['baseline-inventory', 'integration-review'] }
            : node,
        ),
        edges: [
          ...currentDag.edges.filter((edge) => edge.id !== 'integration-review->worker-stop-lifecycle'),
          {
            id: 'integration-review->worker-stop-lifecycle',
            source: 'integration-review',
            target: 'worker-stop-lifecycle',
          },
        ],
      };
    },
    nodeDependenciesResponse: () => ({
      body: {
        path: 'examples/optimization_dag.yaml',
        backup_path: 'examples/optimization_dag.yaml.20260624T000000Z.bak',
        node: currentDag.nodes.find((node) => node.id === 'worker-stop-lifecycle'),
      },
    }),
  });

  await page.goto('/');
  await page.getByRole('button', { name: /worker stop lifecycle/i }).click();

  await expect(page.locator('.react-flow__edge')).toHaveCount(1);

  const initialDagRequestCount = dagRequestCount;
  const initialStateRequestCount = stateRequestCount;
  const initialValidationRequestCount = validationRequestCount;

  await page.getByRole('button', { name: /edit dependencies/i }).click();
  await page.getByLabel('Integration Review (integration-review)').check();

  const saveButton = page.getByRole('button', { name: 'Save dependencies' });
  await saveButton.click();

  await expect(saveButton).toBeDisabled();
  await expect(page.locator('.react-flow__edge')).toHaveCount(2);
  await expect(page.locator('.dependency-readout .dependency-chip')).toContainText([
    'baseline-inventory',
    'integration-review',
  ]);
  await expect.poll(() => dagRequestCount > initialDagRequestCount).toBe(true);
  await expect.poll(() => stateRequestCount > initialStateRequestCount).toBe(true);
  await expect.poll(() => validationRequestCount > initialValidationRequestCount).toBe(true);
});

test('stages graph dependency edits with undo, cancel, save, removal, and inline save errors', async ({ page }) => {
  let currentDag = JSON.parse(JSON.stringify(dagFixture));
  currentDag.nodes.push({
    id: 'integration-review',
    title: 'Integration Review',
    goal: 'Review integrated behavior.',
    dependencies: [],
    target_files: ['docs/integration-review.md'],
    context_files: [],
    allowed_models: ['gpt-5.4'],
    recommended_model: 'gpt-5.4',
    risk_level: 'medium',
    review_gate: 'orchestrator_review',
    acceptance_criteria: ['Integration review is captured'],
    verification_commands: ['pytest -q'],
    do_not: ['Do not skip the review'],
    prompt_template: 'Integration review prompt',
    failure_policy: 'send_to_human',
    outputs: [],
    tags: [],
  });
  const dependencyRequests: unknown[] = [];
  let removalFailureCount = 0;

  const applyDependencies = (taskId: string, dependencies: string[]) => {
    currentDag = {
      ...currentDag,
      nodes: currentDag.nodes.map((node) =>
        node.id === taskId
          ? { ...node, dependencies }
          : node,
      ),
      edges: currentDag.nodes.flatMap((node) => {
        const nodeDependencies = node.id === taskId ? dependencies : node.dependencies;
        return nodeDependencies.map((dependencyId) => ({
          id: `${dependencyId}->${node.id}`,
          source: dependencyId,
          target: node.id,
        }));
      }),
    };
  };

  await mockWorkbenchApi(page, {
    dagResponse: () => ({ body: currentDag }),
    stateByNode: () => ({
      'baseline-inventory': 'ready',
      'worker-stop-lifecycle': 'blocked',
      'integration-review': 'ready',
    }),
    nodeDependenciesDelayMs: 50,
    onNodeDependencies: (payload) => {
      dependencyRequests.push(payload);
    },
    nodeDependenciesResponse: (payload) => {
      const request = payload as { task_id: string; dependencies: string[] };
      if (request.task_id === 'worker-stop-lifecycle' && request.dependencies.length === 1 && removalFailureCount === 0) {
        removalFailureCount += 1;
        return {
          status: 500,
          body: { error: 'simulated graph dependency save failure' },
        };
      }

      applyDependencies(request.task_id, request.dependencies);
      return {
        body: {
          path: 'examples/optimization_dag.yaml',
          backup_path: 'examples/optimization_dag.yaml.20260624T000000Z.bak',
          node: currentDag.nodes.find((node) => node.id === request.task_id),
        },
      };
    },
  });

  await page.goto('/');
  await waitForGraphNodeBox(page, 'Integration Review');
  await expect(page.locator('.react-flow__edge')).toHaveCount(1);

  await dragGraphConnection(page, 'integration-review', 'worker-stop-lifecycle');

  await expect(page.getByText('Unsaved graph dependency edit')).toBeVisible();
  await expect(page.getByText('worker-stop-lifecycle waits for baseline-inventory, integration-review')).toBeVisible();
  await expect(page.locator('.react-flow__edge')).toHaveCount(2);
  expect(dependencyRequests).toHaveLength(0);

  await page.getByRole('button', { name: 'Undo' }).click();
  await expect(page.getByText('Unsaved graph dependency edit')).toHaveCount(0);
  await expect(page.locator('.react-flow__edge')).toHaveCount(1);
  expect(dependencyRequests).toHaveLength(0);

  await dragGraphConnection(page, 'integration-review', 'worker-stop-lifecycle');
  await page.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByText('Unsaved graph dependency edit')).toHaveCount(0);
  await expect(page.locator('.react-flow__edge')).toHaveCount(1);
  expect(dependencyRequests).toHaveLength(0);

  await dragGraphConnection(page, 'integration-review', 'worker-stop-lifecycle');
  await page.getByRole('button', { name: 'Save graph edit' }).click();

  await expect.poll(() => dependencyRequests.length).toBe(1);
  expect(dependencyRequests[0]).toMatchObject({
    dag_path: 'examples/optimization_dag.yaml',
    task_id: 'worker-stop-lifecycle',
    dependencies: ['baseline-inventory', 'integration-review'],
  });
  await expect(page.getByText('Unsaved graph dependency edit')).toHaveCount(0);
  await expect(page.locator('.react-flow__edge')).toHaveCount(2);

  await page.locator('.react-flow__edge').nth(1).dblclick({ force: true });

  await expect(page.getByText('Removed integration-review')).toBeVisible();
  await expect(page.getByText('worker-stop-lifecycle waits for baseline-inventory')).toBeVisible();
  await expect(page.locator('.react-flow__edge')).toHaveCount(1);
  expect(dependencyRequests).toHaveLength(1);

  await page.getByRole('button', { name: 'Save graph edit' }).click();

  await expect(page.getByRole('alert')).toContainText(
    'Dependency update failed: simulated graph dependency save failure',
  );
  await expect(page.locator('.react-flow__edge')).toHaveCount(1);
  await expect.poll(() => dependencyRequests.length).toBe(2);

  await page.getByRole('button', { name: 'Save graph edit' }).click();

  await expect.poll(() => dependencyRequests.length).toBe(3);
  expect(dependencyRequests[2]).toMatchObject({
    task_id: 'worker-stop-lifecycle',
    dependencies: ['baseline-inventory'],
  });
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByText('Unsaved graph dependency edit')).toHaveCount(0);
  await expect(page.locator('.react-flow__edge')).toHaveCount(1);

  const baselineBox = await graphNodeBox(page, 'Baseline Inventory');
  const integrationBox = await graphNodeBox(page, 'Integration Review');
  expect(Math.abs(baselineBox.x - integrationBox.x) + Math.abs(baselineBox.y - integrationBox.y)).toBeGreaterThan(20);
});

test('shows inline dependency-save errors for cycle and unknown dependency rejections', async ({ page }) => {
  const currentDag = JSON.parse(JSON.stringify(dagFixture));
  currentDag.nodes.push({
    id: 'integration-review',
    title: 'Integration Review',
    goal: 'Review integrated behavior.',
    dependencies: [],
    target_files: ['docs/integration-review.md'],
    context_files: [],
    allowed_models: ['gpt-5.4'],
    recommended_model: 'gpt-5.4',
    risk_level: 'medium',
    review_gate: 'orchestrator_review',
    acceptance_criteria: ['Integration review is captured'],
    verification_commands: ['pytest -q'],
    do_not: ['Do not skip the review'],
    prompt_template: 'Integration review prompt',
    failure_policy: 'send_to_human',
    outputs: [],
    tags: [],
  });

  await mockWorkbenchApi(page, {
    dagResponse: () => ({ body: currentDag }),
    stateByNode: () => ({
      'baseline-inventory': 'ready',
      'worker-stop-lifecycle': 'blocked',
      'integration-review': 'ready',
    }),
    nodeDependenciesResponse: (payload) => {
      const request = payload as { task_id: string };
      if (request.task_id === 'baseline-inventory') {
        return {
          status: 400,
          body: {
            error: 'Cycle detected at node baseline-inventory',
          },
        };
      }

      return {
        status: 400,
        body: {
          error: "worker-stop-lifecycle: unknown dependency 'integration-review'",
        },
      };
    },
  });

  await page.goto('/');

  await page.locator('.node-list').getByRole('button', { name: /baseline inventory/i }).click();
  await page.getByRole('button', { name: /edit dependencies/i }).click();
  await page.getByLabel('Worker Stop Lifecycle (worker-stop-lifecycle)').check();
  await page.getByRole('button', { name: 'Save dependencies' }).click();

  await expect(page.getByRole('alert')).toContainText(
    'Dependency update failed: Saving this selection would create a cycle at baseline-inventory.',
  );

  await page
    .locator('section')
    .filter({ hasText: 'Dependencies' })
    .getByRole('button', { name: 'Cancel', exact: true })
    .click();

  await page.getByRole('button', { name: /worker stop lifecycle/i }).click();
  await page.getByRole('button', { name: /edit dependencies/i }).click();
  await page.getByLabel('Integration Review (integration-review)').check();
  await page.getByRole('button', { name: 'Save dependencies' }).click();

  await expect(page.getByRole('alert')).toContainText(
    'Dependency update failed: worker-stop-lifecycle depends on missing integration-review. Pick an existing node or remove it from the selection.',
  );
});

test('warns before switching nodes with unsaved metadata changes', async ({ page }) => {
  await mockWorkbenchApi(page);

  await page.goto('/');
  await page.getByRole('button', { name: /worker stop lifecycle/i }).click();
  await page.getByRole('button', { name: /edit metadata/i }).click();
  await page.getByLabel('Risk level').selectOption('medium');

  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('Discard unsaved changes in the inspector');
    await dialog.dismiss();
  });

  await page.locator('.node-list').getByRole('button', { name: /baseline inventory/i }).click();

  await expect(page.getByRole('heading', { name: 'worker-stop-lifecycle' })).toBeVisible();
  await expect(page.getByLabel('Risk level')).toHaveValue('medium');

  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('Discard unsaved changes in the inspector');
    await dialog.accept();
  });

  await page.locator('.node-list').getByRole('button', { name: /baseline inventory/i }).click();

  await expect(page.getByRole('heading', { name: 'baseline-inventory' })).toBeVisible();
});

test('applies custom DAG and runs paths and persists them across refresh', async ({ page }) => {
  const requestedDagPaths: string[] = [];
  const requestedStateRunsDirs: string[] = [];

  await mockWorkbenchApi(page, {
    onDagRequest: (url) => {
      requestedDagPaths.push(new URL(url).searchParams.get('path') ?? '');
    },
    onStateRequest: (url) => {
      requestedStateRunsDirs.push(new URL(url).searchParams.get('runs_dir') ?? '');
    },
  });

  await page.goto('/');

  await page.getByLabel('DAG path').fill('examples/custom_dag.yaml');
  await page.getByLabel('Runs directory').fill('custom-runs');
  await page.getByRole('button', { name: 'Apply workspace paths' }).click();

  await expect(page.getByText('examples/custom_dag.yaml')).toBeVisible();
  await expect(page.getByText('custom-runs')).toBeVisible();
  await expect.poll(() => requestedDagPaths.includes('examples/custom_dag.yaml')).toBe(true);
  await expect.poll(() => requestedStateRunsDirs.includes('custom-runs')).toBe(true);

  await page.reload();

  await expect(page.locator('input[value="examples/custom_dag.yaml"]')).toBeVisible();
  await expect(page.locator('input[value="custom-runs"]')).toBeVisible();
});

test('shows empty data states when the DAG loads without nodes or runs', async ({ page }) => {
  await mockWorkbenchApi(page, {
    dagResponse: {
      body: {
        schema_version: '1',
        project: 'automation-inspection-optimization',
        default_review_model: 'gpt-5',
        nodes: [],
        edges: [],
      },
    },
    runs: [],
    stateByNode: {},
  });

  await page.goto('/');

  await expect(page.getByText('No selected node')).toBeVisible();
  await expect(page.getByText('No ready nodes')).toBeVisible();
  await expect(page.getByText('No DAG nodes')).toBeVisible();
  await expect(page.getByText('No run records').first()).toBeVisible();
});

test('inspects and accepts a pending workflow mutation', async ({ page }) => {
  let decisionPayload: unknown;
  let mutationRequestUrl = '';
  const accepted = {
    ...mutationFixture,
    current_workflow: {
      ...mutationFixture.current_workflow,
      nodes: [
        mutationFixture.current_workflow.nodes[0],
        { id: 'verify', role: 'producer', waits_for: [], emits: ['verification_ready'] },
        {
          ...mutationFixture.current_workflow.nodes[1],
          waits_for: ['prepare.patch_ready', 'verify.verification_ready'],
        },
        mutationFixture.current_workflow.nodes[2],
      ],
    },
    proposals: [
      {
        ...mutationFixture.proposals[0],
        state: 'accepted',
        decision_event_id: 'event-mutation-accepted-001',
        superseded_assignments: ['assign-review'],
      },
    ],
  };
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    onMutationRequest: (url) => {
      mutationRequestUrl = url;
    },
    onMutationDecision: (payload) => {
      decisionPayload = payload;
    },
    mutationDecisionResponse: () => ({ body: accepted }),
  });

  await page.goto(
    '/?workflow_path=.bureauless/mutation-demo/workflow.yaml&ledger_path=.bureauless/mutation-demo/ledger.yaml',
  );

  await expect(page.getByRole('button', { name: 'Runtime workflow' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('region', { name: 'Runtime workflow summary' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Mission summary' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Ledger summary' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Mission summary' }).getByText('Mission id')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Mission summary' }).locator('dd').first()).toHaveText('demo');
  await expect(page.getByRole('region', { name: 'Mission summary' }).getByText('Keep the runtime workflow healthy.')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Mission summary' }).getByText('active')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Ledger summary' }).getByText('3')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Ledger summary' }).getByText('2')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Ledger summary' }).getByText('1')).toBeVisible();
  const panel = page.getByRole('region', { name: 'Runtime workflow mutations' });
  await expect(panel.getByText('mutation-001')).toBeVisible();
  await expect(
    panel.getByText('.bureauless/mutation-demo/ledger.yaml'),
  ).toBeVisible();
  await expect(panel.getByText('artifact-impact-report')).toBeVisible();
  await expect(panel.getByText('assign-review')).toBeVisible();
  await expect(panel.getByText(/add_nodes: 1/)).toBeVisible();
  await expect(panel.getByText('Runtime workflow now')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Runtime sources' }).getByLabel('Mission path')).toHaveValue('.bureauless/mutation-demo/mission.yaml');
  await expect(
    panel.getByText('This panel reflects the runtime workflow from the ledger. Switch to Planning DAG to edit graph structure.'),
  ).toBeVisible();
  const canvas = page.getByRole('region', { name: 'Runtime workflow canvas' });
  await expect(page.getByTestId('rf__node-prepare')).toBeVisible();
  await expect(page.getByTestId('rf__node-review')).toBeVisible();
  await expect(page.getByTestId('rf__node-independent')).toBeVisible();
  await expect(page.getByTestId('rf__node-verify')).toHaveCount(0);
  await expect(panel.getByText('Current runtime workflow')).toBeVisible();
  await expect(panel.getByText('Proposed workflow')).toBeVisible();
  await expect(panel.getByText(/^prepare, review, independent$/)).toBeVisible();
  await expect(panel.getByText('prepare, review, independent, verify')).toBeVisible();
  await expect(panel.getByText('+ verify -> review')).toBeVisible();
  await expect.poll(() => new URL(mutationRequestUrl).searchParams.get('workflow_path')).toBe(
    '.bureauless/mutation-demo/workflow.yaml',
  );
  await panel.getByRole('button', { name: 'Accept' }).dispatchEvent('click');

  await expect.poll(() => decisionPayload).toMatchObject({
    proposal_event_id: 'event-mutation-001',
    decision: 'accept',
    actor: 'human',
  });
  await expect(panel.getByText('accepted')).toBeVisible();
  await expect(panel.getByText('Applied workflow')).toBeVisible();
  await expect(panel.getByText(/^prepare, verify, review, independent$/)).toHaveCount(2);
  await expect(panel.getByRole('button', { name: 'Accept' })).toHaveCount(0);
  await expect(panel.getByText('Superseded')).toBeVisible();
  await expect(panel.getByText('assign-review')).toHaveCount(2);
  await expect(page.getByTestId('rf__node-verify')).toBeVisible();
});

test('shows decision sync status while refreshing runtime state', async ({ page }) => {
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    gatekeeperResponse: { body: gatekeeperFixture },
    mutationDecisionDelayMs: 150,
    mutationDecisionResponse: () => ({
      body: {
        ...mutationFixture,
        proposals: [
          {
            ...mutationFixture.proposals[0],
            state: 'accepted',
            decision_event_id: 'event-mutation-accepted-001',
            superseded_assignments: ['assign-review'],
          },
        ],
      },
    }),
  });

  await page.goto(
    '/?workflow_path=.bureauless/mutation-demo/workflow.yaml&ledger_path=.bureauless/mutation-demo/ledger.yaml',
  );

  const panel = page.getByRole('region', { name: 'Runtime workflow mutations' });
  await panel.getByRole('button', { name: 'Accept' }).dispatchEvent('click');

  await expect(panel.getByRole('status')).toContainText('Applying decision and refreshing runtime state.');

  await expect(panel.getByText('accepted')).toBeVisible();
  await expect(panel.getByRole('status')).toHaveCount(0);
});

test('renders runtime summary panels and persists runtime source paths', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('bureauless.workbenchViewMode', 'planning');
    window.localStorage.setItem('bureauless.missionPath', 'stale/mission.yaml');
    window.localStorage.setItem('bureauless.workflowPath', 'stale/workflow.yaml');
    window.localStorage.setItem('bureauless.ledgerPath', 'stale/ledger.yaml');
  });
  let missionRequestUrl = '';
  let mutationRequestUrl = '';
  let ledgerRequestUrl = '';
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    onMissionRequest: (url) => {
      missionRequestUrl = url;
    },
    onMutationRequest: (url) => {
      mutationRequestUrl = url;
    },
    onLedgerRequest: (url) => {
      ledgerRequestUrl = url;
    },
  });

  await page.goto('/?workflow_path=.bureauless/mutation-demo/workflow.yaml&ledger_path=.bureauless/mutation-demo/ledger.yaml');

  const runtimeSources = page.getByRole('region', { name: 'Runtime sources' });
  const missionPanel = page.getByRole('region', { name: 'Mission summary' });
  const ledgerPanel = page.getByRole('region', { name: 'Ledger summary' });
  const applyRuntimeSources = runtimeSources.getByRole('button', { name: 'Apply runtime sources' });

  await expect(runtimeSources.getByLabel('Mission path')).toHaveValue('.bureauless/mutation-demo/mission.yaml');
  await expect(runtimeSources.getByLabel('Workflow path')).toHaveValue('.bureauless/mutation-demo/workflow.yaml');
  await expect(runtimeSources.getByLabel('Ledger path')).toHaveValue('.bureauless/mutation-demo/ledger.yaml');
  await expect(applyRuntimeSources).toBeDisabled();
  await expect.poll(() => new URL(missionRequestUrl).searchParams.get('path')).toBe(
    '.bureauless/mutation-demo/mission.yaml',
  );
  await expect.poll(() => new URL(mutationRequestUrl).searchParams.get('workflow_path')).toBe(
    '.bureauless/mutation-demo/workflow.yaml',
  );
  await expect.poll(() => new URL(ledgerRequestUrl).searchParams.get('path')).toBe(
    '.bureauless/mutation-demo/ledger.yaml',
  );
  await expect(missionPanel.locator('dd').first()).toHaveText('demo');
  await expect(missionPanel.getByText('Keep the runtime workflow healthy.')).toBeVisible();
  await expect(ledgerPanel.getByText('3')).toBeVisible();
  await expect(ledgerPanel.getByText('2')).toBeVisible();
  await expect(ledgerPanel.getByText('1')).toBeVisible();
  await expect(ledgerPanel.getByText('Artifacts')).toBeVisible();
  await expect(ledgerPanel.getByText('Risks')).toBeVisible();
  await expect(ledgerPanel.getByText('Decisions')).toBeVisible();
  await expect(runtimeSources.getByRole('status')).toContainText('Runtime sources loaded.');

  await runtimeSources.getByLabel('Mission path').fill('examples/missions/custom/mission.yaml');
  await runtimeSources.getByLabel('Workflow path').fill('examples/missions/custom/workflow.yaml');
  await runtimeSources.getByLabel('Ledger path').fill('examples/missions/custom/ledger.yaml');
  await expect(runtimeSources.getByLabel('Mission path')).toHaveValue('examples/missions/custom/mission.yaml');
  await expect(runtimeSources.getByLabel('Workflow path')).toHaveValue('examples/missions/custom/workflow.yaml');
  await expect(runtimeSources.getByLabel('Ledger path')).toHaveValue('examples/missions/custom/ledger.yaml');
  await expect(runtimeSources.getByRole('status')).toContainText('Runtime source changes are not applied.');
  await applyRuntimeSources.dispatchEvent('click');

  await expect.poll(() => page.evaluate(() => window.localStorage.getItem('bureauless.missionPath'))).toBe(
    'examples/missions/custom/mission.yaml',
  );
  await expect.poll(() => page.evaluate(() => window.localStorage.getItem('bureauless.workflowPath'))).toBe(
    'examples/missions/custom/workflow.yaml',
  );
  await expect.poll(() => page.evaluate(() => window.localStorage.getItem('bureauless.ledgerPath'))).toBe(
    'examples/missions/custom/ledger.yaml',
  );
});

test('loads runtime sources from artifact_manifest_path without frontend YAML parsing', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('bureauless.workbenchViewMode', 'planning');
    window.localStorage.setItem('bureauless.missionPath', 'stale/mission.yaml');
    window.localStorage.setItem('bureauless.workflowPath', 'stale/workflow.yaml');
    window.localStorage.setItem('bureauless.ledgerPath', 'stale/ledger.yaml');
    window.localStorage.setItem('bureauless.artifactManifestPath', 'stale/manifest.yaml');
  });
  let artifactManifestRequestUrl = '';
  let missionRequestUrl = '';
  let mutationRequestUrl = '';
  let ledgerRequestUrl = '';
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    artifactManifestResponse: { body: artifactManifestFixture },
    onArtifactManifestRequest: (url) => {
      artifactManifestRequestUrl = url;
    },
    onMissionRequest: (url) => {
      missionRequestUrl = url;
    },
    onMutationRequest: (url) => {
      mutationRequestUrl = url;
    },
    onLedgerRequest: (url) => {
      ledgerRequestUrl = url;
    },
  });

  await page.goto('/?artifact_manifest_path=.bureauless/m3-demo/generated/telemetry/manifest.yaml');

  const runtimeSources = page.getByRole('region', { name: 'Runtime sources' });
  await expect(runtimeSources.getByLabel('Artifact manifest path')).toHaveValue(
    '.bureauless/m3-demo/generated/telemetry/manifest.yaml',
  );
  await expect.poll(() => new URL(artifactManifestRequestUrl).searchParams.get('path')).toBe(
    '.bureauless/m3-demo/generated/telemetry/manifest.yaml',
  );
  await expect.poll(() => (missionRequestUrl ? new URL(missionRequestUrl).searchParams.get('path') : null)).toBe(
    '.bureauless/m3-demo/mission.yaml',
  );
  await expect.poll(() => (mutationRequestUrl ? new URL(mutationRequestUrl).searchParams.get('workflow_path') : null)).toBe(
    '.bureauless/m3-demo/workflow.yaml',
  );
  await expect.poll(() => (ledgerRequestUrl ? new URL(ledgerRequestUrl).searchParams.get('path') : null)).toBe(
    '.bureauless/m3-demo/ledger.yaml',
  );
  await expect(runtimeSources.getByLabel('Mission path')).toHaveValue('.bureauless/m3-demo/mission.yaml');
  await expect(runtimeSources.getByLabel('Workflow path')).toHaveValue('.bureauless/m3-demo/workflow.yaml');
  await expect(runtimeSources.getByLabel('Ledger path')).toHaveValue('.bureauless/m3-demo/ledger.yaml');
  await expect(runtimeSources.getByRole('status')).toContainText('Runtime sources loaded.');
});

test('renders Runtime M4 timeline, historical snapshot, and diff inspectors from API history surfaces', async ({ page }) => {
  let timelineRequestUrl = '';
  let snapshotRequestUrl = '';
  let diffRequestUrl = '';
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    replayResponse: { body: replayFixture },
    replayTimelineResponse: { body: replayTimelineFixture },
    replaySnapshotResponse: { body: replaySnapshotFixture },
    replayDiffResponse: { body: replayDiffFixture },
    onReplayTimelineRequest: (url) => {
      timelineRequestUrl = url;
    },
    onReplaySnapshotRequest: (url) => {
      snapshotRequestUrl = url;
    },
    onReplayDiffRequest: (url) => {
      diffRequestUrl = url;
    },
  });

  await page.goto(
    '/?workflow_path=.bureauless/mutation-demo/workflow.yaml&ledger_path=.bureauless/mutation-demo/ledger.yaml&through_event_id=event-mutation-accepted-001&from_event_id=event-mutation-001&to_event_id=event-mutation-accepted-001',
  );

  await expect.poll(() => (timelineRequestUrl ? new URL(timelineRequestUrl).searchParams.get('workflow_path') : null)).toBe(
    '.bureauless/mutation-demo/workflow.yaml',
  );
  await expect.poll(() => (snapshotRequestUrl ? new URL(snapshotRequestUrl).searchParams.get('through_event_id') : null)).toBe(
    'event-mutation-accepted-001',
  );
  await expect.poll(() => (diffRequestUrl ? new URL(diffRequestUrl).searchParams.get('from_event_id') : null)).toBe(
    'event-mutation-001',
  );
  await expect.poll(() => (diffRequestUrl ? new URL(diffRequestUrl).searchParams.get('to_event_id') : null)).toBe(
    'event-mutation-accepted-001',
  );

  const historyPanel = page.getByRole('region', { name: 'Timeline and versions' });
  await expect(historyPanel.getByRole('button', { name: /v0002/i })).toBeVisible();
  await expect(historyPanel.getByRole('button', { name: /workflow_mutation_accepted/i })).toBeVisible();

  const snapshotPanel = page.getByRole('region', { name: 'Historical snapshot inspector' });
  await expect(snapshotPanel.getByText('workflow-version-002', { exact: true }).first()).toBeVisible();
  await expect(snapshotPanel.getByText('awaiting_context')).toBeVisible();
  await expect(snapshotPanel.getByText('workflow_version_changed')).toBeVisible();
  await expect(snapshotPanel.getByText('awaiting_revalidation')).toBeVisible();

  const diffPanel = page.getByRole('region', { name: 'Temporal diff inspector' });
  await expect(diffPanel.getByText('node added')).toBeVisible();
  await expect(diffPanel.getByText('verify', { exact: true }).first()).toBeVisible();
  await expect(diffPanel.getByText('assignment validity').first()).toBeVisible();
  await expect(diffPanel.getByText('mutation state').first()).toBeVisible();
});

test('surfaces Runtime M4 unsupported temporal requests as explicit UI errors', async ({ page }) => {
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    replayTimelineResponse: { body: replayTimelineFixture },
    replaySnapshotResponse: {
      status: 400,
      body: {
        code: 'unknown_cursor',
        error: 'Unknown replay cursor: event-missing',
      },
    },
    replayDiffResponse: {
      status: 400,
      body: {
        code: 'unsupported_temporal_request',
        error: 'Rollback comparisons are not supported',
      },
    },
  });

  await page.goto(
    '/?workflow_path=.bureauless/mutation-demo/workflow.yaml&ledger_path=.bureauless/mutation-demo/ledger.yaml&through_event_id=event-missing&from_event_id=event-mutation-accepted-001&to_event_id=event-mutation-001',
  );

  const historyPanel = page.getByRole('region', { name: 'Timeline and versions' });
  await expect(historyPanel).toBeVisible();
  await expect(historyPanel.getByRole('alert')).toContainText('Unknown replay cursor: event-missing');
  await expect(page.getByRole('region', { name: 'Historical snapshot inspector' }).getByRole('alert')).toContainText(
    'Unknown replay cursor: event-missing',
  );
  await expect(page.getByRole('region', { name: 'Temporal diff inspector' }).getByRole('alert')).toContainText(
    'Rollback comparisons are not supported',
  );
});

test('runs Runtime M6 operator actions through validated backend endpoints', async ({ page }) => {
  const observed: Record<string, unknown> = {};
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    artifactManifestResponse: { body: artifactManifestFixture },
    onContextResolve: (payload) => {
      observed.contextResolve = payload;
    },
    onDispatchPacketCompile: (payload) => {
      observed.dispatchCompile = payload;
    },
    onSessionDispatch: (payload) => {
      observed.sessionDispatch = payload;
    },
    onResultStage: (payload) => {
      observed.resultStage = payload;
    },
    onReviewDecisionImport: (payload) => {
      observed.reviewImport = payload;
    },
    onOutcomeDecide: (payload) => {
      observed.outcomeDecide = payload;
    },
  });

  await page.goto('/?artifact_manifest_path=.bureauless/m3-demo/generated/telemetry/manifest.yaml');

  const contextPanel = page.getByRole('region', { name: 'Context request resolution' });
  await contextPanel.getByRole('button', { name: 'Resolve request' }).click();
  await expect(contextPanel.getByText('context-resolution-v1')).toBeVisible();
  await expect(contextPanel.getByText('artifact-test-report-017').first()).toBeVisible();
  await expect(contextPanel.getByText('Outside assignment scope')).toBeVisible();

  const dispatchPanel = page.getByRole('region', { name: 'Dispatch and launch controls' });
  await dispatchPanel.getByRole('button', { name: 'Compile preview' }).click();
  await expect(dispatchPanel.getByText('packet-assign-prepare-live').first()).toBeVisible();
  await dispatchPanel.getByRole('button', { name: 'Launch session' }).click();
  await expect(dispatchPanel.getByText('session-prepare-live').first()).toBeVisible();
  await expect(dispatchPanel.getByText('.bureauless/sessions/assign-prepare-live.bundle.yaml').first()).toBeVisible();

  const acceptancePanel = page.getByRole('region', { name: 'Acceptance and ledger advancement' });
  await acceptancePanel.getByRole('button', { name: 'Stage result' }).click();
  await expect(acceptancePanel.getByText('event-result-prepare-live').first()).toBeVisible();
  await acceptancePanel.getByRole('button', { name: 'Import review' }).click();
  await expect(acceptancePanel.getByText('event-review-imported-001').first()).toBeVisible();
  await acceptancePanel.getByRole('button', { name: 'Decide outcome' }).click();
  await expect(acceptancePanel.getByText('event-outcome-decided-001').first()).toBeVisible();
  await expect(acceptancePanel.getByText('patch_ready').first()).toBeVisible();

  expect(observed.contextResolve).toMatchObject({
    assignment_path: '.bureauless/m3-demo/generated/assignments/prepare_assignment.yaml',
    context_request_path: '.bureauless/m3-demo/generated/context/prepare_context_request.yaml',
    ledger_path: '.bureauless/m3-demo/ledger.yaml',
    max_artifacts: 1,
  });
  expect(observed.dispatchCompile).toMatchObject({
    mission_path: '.bureauless/m3-demo/mission.yaml',
    workflow_path: '.bureauless/m3-demo/workflow.yaml',
    routing_decision_path: '.bureauless/m3-demo/generated/decisions/routing.yaml',
    assignment_path: '.bureauless/m3-demo/generated/assignments/prepare_assignment.yaml',
  });
  expect(observed.sessionDispatch).toMatchObject({
    dispatch_packet_path: '.bureauless/m3-demo/generated/decisions/prepare_dispatch_packet.yaml',
    ledger_path: '.bureauless/m3-demo/ledger.yaml',
    agent: 'codex-cli',
    dry_run: true,
  });
  expect(observed.resultStage).toMatchObject({
    result_path: '.bureauless/m3-demo/generated/results/prepare_result.yaml',
  });
  expect(observed.reviewImport).toMatchObject({
    decision_path: '.bureauless/m3-demo/generated/reviews/prepare_review_decision.yaml',
  });
  expect(observed.outcomeDecide).toMatchObject({
    outcome_path: '.bureauless/m3-demo/generated/outcomes/prepare_node_outcome.yaml',
    verification_status: 'passed',
    accepted_event_types: ['patch_ready'],
  });
});

test('shows Runtime M6 doctor warnings and structured backend rejections without collapsing runtime view', async ({ page }) => {
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    artifactManifestResponse: { body: artifactManifestFixture },
    agentDoctorResponse: () => ({
      body: {
        ...agentDoctorFixture,
        status: 'degraded',
        control_level: 'low',
        checks: [
          ...agentDoctorFixture.checks,
          {
            name: 'working_directory',
            status: 'missing',
            markers: [],
            missing_markers: ['--cd'],
          },
        ],
        warnings: ['Help command exited with 1'],
      },
    }),
    sessionDispatchResponse: () => ({
      status: 400,
      body: {
        code: 'strict_writable_ledger_required',
        error: 'Ledger is not strict-writable for session dispatch',
      },
    }),
    outcomeDecideResponse: () => ({
      status: 400,
      body: {
        code: 'acceptance_review_required',
        error: 'Acceptance review_event_id must reference a review decision',
      },
    }),
  });

  await page.goto('/?artifact_manifest_path=.bureauless/m3-demo/generated/telemetry/manifest.yaml');

  const safetyPanel = page.getByRole('region', { name: 'Action safety and doctoring' });
  await expect(safetyPanel.getByText('degraded').first()).toBeVisible();
  await expect(safetyPanel.getByText('Missing markers: --cd')).toBeVisible();
  await expect(safetyPanel.getByText('Help command exited with 1')).toBeVisible();

  const dispatchPanel = page.getByRole('region', { name: 'Dispatch and launch controls' });
  await dispatchPanel.getByRole('button', { name: 'Launch session' }).click();
  await expect(safetyPanel.getByText('Ledger is not strict-writable for session dispatch')).toBeVisible();

  const acceptancePanel = page.getByRole('region', { name: 'Acceptance and ledger advancement' });
  await acceptancePanel.getByRole('button', { name: 'Decide outcome' }).click();
  await expect(safetyPanel.getByText('Acceptance review_event_id must reference a review decision')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Runtime workflow summary' })).toBeVisible();
});

test('bootstraps a Runtime M7 demo workspace into runtime sources without manual query editing', async ({ page }) => {
  let observedRuntimeDemo: unknown = null;

  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    runtimeDemoResponse: {
      body: runtimeDemoFixture,
    },
    onRuntimeDemo: (payload) => {
      observedRuntimeDemo = payload;
    },
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Runtime workflow' }).click();

  const bootstrapPanel = page.getByLabel('Runtime demo bootstrap');
  await bootstrapPanel.getByLabel('Workspace').fill('/tmp/runtime-m7-demo');
  await bootstrapPanel.getByLabel('Agent').fill('codex-cli');
  await bootstrapPanel.getByLabel('Assignment ID').fill('assign-runtime-m7');
  await bootstrapPanel.getByLabel('Session ID').fill('session-runtime-m7');
  await bootstrapPanel.getByLabel('Result ID').fill('result-runtime-m7');
  await bootstrapPanel.getByLabel('Shell command').fill('printf runtime-m7');
  await bootstrapPanel.getByRole('button', { name: 'Bootstrap runtime demo' }).click();

  await expect(bootstrapPanel.getByText('Bootstrapped session-implement-demo in /tmp/bureauless-runtime-demo.')).toBeVisible();
  await expect(page.getByLabel('Mission path')).toHaveValue('.bureauless/runtime-demo/mission.yaml');
  await expect(page.getByLabel('Workflow path')).toHaveValue('.bureauless/runtime-demo/workflow.yaml');
  await expect(page.getByLabel('Ledger path')).toHaveValue('.bureauless/runtime-demo/ledger.yaml');
  const sourceNavigator = page.getByLabel('Runtime source navigator');
  await expect(sourceNavigator.getByText('Artifact family').locator('..').getByText('direct runtime paths')).toBeVisible();
  await expect(sourceNavigator.getByText('Provenance').locator('..').getByText('bootstrap')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Runtime workflow summary' })).toBeVisible();

  expect(observedRuntimeDemo).toMatchObject({
    workspace: '/tmp/runtime-m7-demo',
    agent: 'codex-cli',
    assignment_id: 'assign-runtime-m7',
    session_id: 'session-runtime-m7',
    result_id: 'result-runtime-m7',
    shell_command: 'printf runtime-m7',
  });
});

test('switches Runtime M7 sources from a run bundle root to the returned manifest root without frontend path synthesis', async ({ page }) => {
  const observedArtifactManifestRequests: string[] = [];
  const ordinarySessionManifest = {
    ...artifactManifestFixture,
    flow_id: 'maintained-session-dispatch',
    metrics_summary_path: '.bureauless/sessions/session-001.yaml',
  };

  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    artifactManifestResponse: { body: ordinarySessionManifest },
    onArtifactManifestRequest: (url) => {
      observedArtifactManifestRequests.push(url);
    },
  });

  await page.goto('/?artifact_manifest_path=.bureauless/sessions/session-001.bundle.yaml');

  const sourceNavigator = page.getByLabel('Runtime source navigator');
  await expect(sourceNavigator.getByText('.bureauless/sessions/session-001.bundle.yaml')).toBeVisible();
  await expect(sourceNavigator.getByText('Artifact family').locator('..').getByText('run bundle')).toBeVisible();

  await sourceNavigator.getByRole('button', { name: 'Use manifest root' }).click();

  await expect(page.getByLabel('Artifact manifest path')).toHaveValue(
    '.bureauless/m3-demo/generated/telemetry/manifest.yaml',
  );
  await expect(
    sourceNavigator.getByText('Current root').locator('..').getByText('.bureauless/m3-demo/generated/telemetry/manifest.yaml'),
  ).toBeVisible();
  expect(observedArtifactManifestRequests.at(-1)).toContain(
    encodeURIComponent('.bureauless/m3-demo/generated/telemetry/manifest.yaml'),
  );
});

test('shows Runtime M7 readiness summary for an ordinary session bundle with explicit unavailable artifacts', async ({ page }) => {
  let advisorOutcomeRequestUrl = '';
  let nodeOutcomeRequestUrl = '';
  let resultRequestUrl = '';
  const ordinarySessionManifest = {
    ...artifactManifestFixture,
    flow_id: 'maintained-session-dispatch',
    advisor_gate_decision_path: null,
    advisor_gate_outcome_path: null,
    metrics_summary_path: '.bureauless/sessions/session-001.yaml',
    steps: [
      {
        ...artifactManifestFixture.steps[0],
        context_request_path: null,
        context_resolution_path: null,
        result_path: null,
        node_outcome_path: null,
        review_decision_path: null,
        outcome_event_id: undefined,
        review_event_id: undefined,
        node_state_after: 'session_completed_unstaged',
      },
    ],
    terminal_complete: false,
    node_states: { prepare: 'session_completed_unstaged' },
  };
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    artifactManifestResponse: { body: ordinarySessionManifest },
    onAdvisorOutcomeRequest: (url) => {
      advisorOutcomeRequestUrl = url;
    },
    onNodeOutcomeRequest: (url) => {
      nodeOutcomeRequestUrl = url;
    },
    onResultRequest: (url) => {
      resultRequestUrl = url;
    },
  });

  await page.goto('/?artifact_manifest_path=.bureauless/sessions/session-001.bundle.yaml');
  await page.getByLabel('Runtime workflow nodes').getByRole('button', { name: /prepare/i }).click();

  const routingInspector = page.getByRole('region', { name: 'Routing and advisor inspector' });
  const nodeInspector = page.getByRole('region', { name: 'Runtime node inspector' });
  const readinessPanel = page.getByLabel('Artifact readiness summary');
  await expect(routingInspector.getByText('Classification').locator('..').getByText('unavailable')).toBeVisible();
  await expect(nodeInspector.getByText('Outcome status').locator('..').getByText('unavailable')).toBeVisible();
  await expect(nodeInspector.getByText('Result status').locator('..').getByText('unavailable')).toBeVisible();
  await expect(readinessPanel.getByText('Actionability:').locator('..').getByText('inspect-only')).toBeVisible();
  await expect(readinessPanel.getByText('Result artifact').locator('..').getByText('needs_review')).toBeVisible();
  await expect(readinessPanel.getByText('Outcome artifact').locator('..').getByText('needs_review')).toBeVisible();
  await expect(readinessPanel.getByText('Review link').locator('..').getByText('needs_review')).toBeVisible();
  expect(advisorOutcomeRequestUrl).toBe('');
  expect(nodeOutcomeRequestUrl).toBe('');
  expect(resultRequestUrl).toBe('');
});

test('renders routing and advisor inspector from manifest-backed runtime artifacts', async ({ page }) => {
  let routingDecisionRequestUrl = '';
  let advisorOutcomeRequestUrl = '';
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    artifactManifestResponse: { body: artifactManifestFixture },
    routingDecisionResponse: { body: routingDecisionFixture },
    advisorOutcomeResponse: { body: advisorOutcomeFixture },
    onRoutingDecisionRequest: (url) => {
      routingDecisionRequestUrl = url;
    },
    onAdvisorOutcomeRequest: (url) => {
      advisorOutcomeRequestUrl = url;
    },
  });

  await page.goto('/?artifact_manifest_path=.bureauless/m3-demo/generated/telemetry/manifest.yaml');

  const inspector = page.getByRole('region', { name: 'Routing and advisor inspector' });
  await expect.poll(() => (routingDecisionRequestUrl ? new URL(routingDecisionRequestUrl).searchParams.get('path') : null)).toBe(
    '.bureauless/m3-demo/generated/decisions/routing.yaml',
  );
  await expect.poll(() => (advisorOutcomeRequestUrl ? new URL(advisorOutcomeRequestUrl).searchParams.get('path') : null)).toBe(
    '.bureauless/m3-demo/generated/telemetry/advisor_outcome.yaml',
  );
  await expect(inspector.getByRole('definition').filter({ hasText: 'small_dag' })).toBeVisible();
  await expect(inspector.getByRole('definition').filter({ hasText: 'good_skip' })).toBeVisible();
  await expect(inspector.getByText('first_run_heuristic')).toBeVisible();
  await expect(inspector.getByText('openai/gpt-5.4')).toBeVisible();
  await expect(inspector.getByText('generated/decisions/routing.yaml')).toBeVisible();
});

test('renders node outcome and accepted evidence for the selected manifest-backed runtime node', async ({ page }) => {
  let nodeOutcomeRequestUrl = '';
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    artifactManifestResponse: { body: artifactManifestFixture },
    nodeOutcomeResponse: { body: nodeOutcomeFixture },
    ledgerResponse: {
      body: {
        ...ledgerFixture,
        event_log: [
          {
            event_id: 'event-review-prepare-live',
            event_type: 'review_decision_recorded',
            evidence_refs: ['artifact-prepare-patch'],
            accepted_findings: [
              {
                finding_id: 'finding-prepare-live',
                content: 'The prepare node patch is safe to land.',
              },
            ],
            rejected_findings: [
              {
                finding_id: 'finding-prepare-rejected',
                reason: 'A speculative claim was not supported by the patch.',
              },
            ],
          },
        ],
      },
    },
    onNodeOutcomeRequest: (url) => {
      nodeOutcomeRequestUrl = url;
    },
  });

  await page.goto('/?artifact_manifest_path=.bureauless/m3-demo/generated/telemetry/manifest.yaml');
  await page.getByLabel('Runtime workflow nodes').getByRole('button', { name: /prepare/i }).click();

  await expect.poll(() => (nodeOutcomeRequestUrl ? new URL(nodeOutcomeRequestUrl).searchParams.get('path') : null)).toBe(
    '.bureauless/m3-demo/generated/outcomes/prepare_node_outcome.yaml',
  );
  const inspector = page.getByRole('region', { name: 'Runtime node inspector' });
  await expect(inspector.getByText('1 changed file, 124 patch bytes')).toBeVisible();
  await expect(inspector.getByText('artifact-prepare-patch').first()).toBeVisible();
  await expect(inspector.getByText('The prepare node patch is safe to land.')).toBeVisible();
  await expect(inspector.getByText('A speculative claim was not supported by the patch.')).toBeVisible();
});

test('renders context delivery details for the selected manifest-backed runtime node', async ({ page }) => {
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    artifactManifestResponse: { body: artifactManifestFixture },
  });

  await page.goto('/?artifact_manifest_path=.bureauless/m3-demo/generated/telemetry/manifest.yaml');
  await page.getByLabel('Runtime workflow nodes').getByRole('button', { name: /prepare/i }).click();

  const inspector = page.getByRole('region', { name: 'Runtime node inspector' });
  await expect(inspector.getByText('context-v1')).toBeVisible();
  await expect(inspector.getByRole('definition').filter({ hasText: '1800' })).toBeVisible();
  await expect(inspector.getByText('artifact-test-report-017').first()).toBeVisible();
  await expect(inspector.getByText('Patch must preserve the downstream review handoff.')).toBeVisible();
  await expect(inspector.getByText('Need the test failure details artifact.')).toBeVisible();
});

test('renders budget telemetry and bounded handoff artifacts for the selected manifest-backed runtime node', async ({ page }) => {
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    artifactManifestResponse: { body: artifactManifestFixture },
  });

  await page.goto('/?artifact_manifest_path=.bureauless/m3-demo/generated/telemetry/manifest.yaml');
  await page.getByLabel('Runtime workflow nodes').getByRole('button', { name: /prepare/i }).click();

  const inspector = page.getByRole('region', { name: 'Runtime node inspector' });
  await expect(inspector.getByText('$0.012')).toBeVisible();
  await expect(inspector.getByText('good_skip: 1')).toBeVisible();
  await expect(inspector.getByText('openai/gpt-5.4')).toBeVisible();
  await expect(inspector.getByText('expected events: patch_ready')).toBeVisible();
  await expect(inspector.getByText('report tokens: 600')).toBeVisible();
  await expect(inspector.getByText('Prepared the patch and verified the bounded handoff.')).toBeVisible();
});

test('covers the manifest-backed M3 inspection path on a narrow viewport and shows explicit missing artifact states', async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 900 });
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    artifactManifestResponse: { body: artifactManifestFixture },
    ledgerResponse: {
      body: {
        ...ledgerFixture,
        event_log: [
          {
            event_id: 'event-review-prepare-live',
            event_type: 'review_decision_recorded',
            evidence_refs: ['artifact-prepare-patch'],
            accepted_findings: [
              {
                finding_id: 'finding-prepare-live',
                content: 'The prepare node patch is safe to land.',
              },
            ],
            rejected_findings: [],
          },
        ],
      },
    },
  });

  await page.goto('/?artifact_manifest_path=.bureauless/m3-demo/generated/telemetry/manifest.yaml');
  await page.getByLabel('Runtime workflow nodes').getByRole('button', { name: /prepare/i }).click();

  const routingInspector = page.getByRole('region', { name: 'Routing and advisor inspector' });
  const nodeInspector = page.getByRole('region', { name: 'Runtime node inspector' });
  await expect(routingInspector.getByText('good_skip')).toBeVisible();
  await expect(nodeInspector.getByText('The prepare node patch is safe to land.')).toBeVisible();
  await expect(nodeInspector.getByText('Need the test failure details artifact.')).toBeVisible();
  await expect(nodeInspector.getByText('Prepared the patch and verified the bounded handoff.')).toBeVisible();

  await page.getByLabel('Runtime workflow nodes').getByRole('button', { name: /review/i }).click();
  await expect(nodeInspector.getByText('No artifact step linked')).toBeVisible();
});

test('keeps runtime structure unchanged when a mutation decision fails', async ({ page }) => {
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    mutationDecisionResponse: () => ({ status: 400, body: { error: 'Mutation decision rejected' } }),
  });

  await page.goto(
    '/?workflow_path=.bureauless/mutation-demo/workflow.yaml&ledger_path=.bureauless/mutation-demo/ledger.yaml',
  );

  const panel = page.getByRole('region', { name: 'Runtime workflow mutations' });
  await panel.getByLabel('Rejection reason for mutation-001').fill('Need more evidence.');
  await panel.getByRole('button', { name: 'Reject' }).dispatchEvent('click');

  await expect(panel.getByRole('alert')).toContainText('Mutation decision rejected');
  await expect(page.getByTestId('rf__node-verify')).toHaveCount(0);
  await expect(panel.getByRole('button', { name: 'Reject' })).toHaveCount(1);
});

test('rejecting a workflow mutation leaves the runtime canvas unchanged', async ({ page }) => {
  const rejected = {
    ...mutationFixture,
    proposals: [
      {
        ...mutationFixture.proposals[0],
        state: 'rejected',
        decision_event_id: 'event-mutation-rejected-001',
      },
    ],
  };
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    mutationDecisionResponse: () => ({ body: rejected }),
  });

  await page.goto(
    '/?workflow_path=.bureauless/mutation-demo/workflow.yaml&ledger_path=.bureauless/mutation-demo/ledger.yaml',
  );

  const canvas = page.getByRole('region', { name: 'Runtime workflow canvas' });
  const panel = page.getByRole('region', { name: 'Runtime workflow mutations' });
  await expect(page.getByTestId('rf__node-prepare')).toBeVisible();
  await expect(page.getByTestId('rf__node-review')).toBeVisible();
  await expect(page.getByTestId('rf__node-verify')).toHaveCount(0);

  await panel.getByLabel('Rejection reason for mutation-001').fill('Evidence does not justify the dependency.');
  await panel.getByRole('button', { name: 'Reject' }).dispatchEvent('click');

  await expect(panel.getByText('rejected')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Reject' })).toHaveCount(0);
  await expect(page.getByTestId('rf__node-prepare')).toBeVisible();
  await expect(page.getByTestId('rf__node-review')).toBeVisible();
  await expect(page.getByTestId('rf__node-verify')).toHaveCount(0);
});

test('keeps runtime node selection separate from planning node selection', async ({ page }) => {
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
  });

  await page.goto(
    '/?workflow_path=.bureauless/mutation-demo/workflow.yaml&ledger_path=.bureauless/mutation-demo/ledger.yaml',
  );

  const runtimeList = page.getByRole('region', { name: /Runtime nodes/ });
  const runtimeInspector = page.getByRole('region', { name: 'Runtime node inspector' });

  await expect(runtimeList.getByRole('button', { name: /^review\b/i })).toBeVisible();
  await runtimeList.getByRole('button', { name: /^review\b/i }).dispatchEvent('click');

  await expect(runtimeInspector.locator('.runtime-node-inspector-header > div strong')).toHaveText('review');
  await expect(runtimeInspector.getByText(/Gatekeeper summary/)).toBeVisible();

  await page.getByRole('button', { name: 'Planning DAG' }).click();
  await page.getByRole('button', { name: /worker stop lifecycle/i }).click();
  await expect(page.getByRole('region', { name: 'Mission summary' })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Ledger summary' })).toHaveCount(0);

  await page.getByRole('button', { name: 'Runtime workflow' }).click();
  await expect(page.getByRole('region', { name: 'Mission summary' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Ledger summary' })).toBeVisible();

  await expect(runtimeInspector.locator('.runtime-node-inspector-header > div strong')).toHaveText('review');
  await expect(runtimeList.getByRole('button', { name: /^review\b/i })).toBeVisible();
});

test('shows replay evidence and follows runtime node selection', async ({ page }) => {
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    replayResponse: { body: replayFixture },
    gatekeeperResponse: { body: gatekeeperFixture },
  });

  await page.goto(
    '/?workflow_path=.bureauless/mutation-demo/workflow.yaml&ledger_path=.bureauless/mutation-demo/ledger.yaml',
  );

  const runtimeList = page.getByRole('region', { name: /Runtime nodes/ });
  const replayInspector = page.getByRole('region', { name: 'Replay inspector' });
  const selectedNodeCard = replayInspector.locator('.runtime-replay-summary .runtime-summary-card').filter({ hasText: 'Selected node' });
  const assignmentAttemptsSection = replayInspector.locator('.runtime-replay-section').filter({ hasText: 'Assignment attempts' });
  const blockedReasonsSection = replayInspector.locator('.runtime-replay-section').filter({ hasText: 'Blocked reasons' });
  const linksSection = replayInspector.locator('.runtime-replay-section').filter({ hasText: 'Supersession / decision links' });
  const reviewAttemptCards = assignmentAttemptsSection.locator('.runtime-replay-card');

  await expect(replayInspector.getByText('Replay inspector')).toBeVisible();
  await expect(selectedNodeCard.locator('strong')).toHaveText('prepare');
  await expect(replayInspector.getByText('assign-prepare-1')).toBeVisible();

  await runtimeList.getByRole('button', { name: /^prepare\b/i }).click();
  await expect(replayInspector.getByText('prepare.patch_ready')).toBeVisible();
  await expect(replayInspector.getByText('assign-prepare-1')).toBeVisible();

  await runtimeList.getByRole('button', { name: /^review\b/i }).dispatchEvent('click');
  await expect(selectedNodeCard.locator('strong')).toHaveText('review');
  await expect(blockedReasonsSection.getByText('mutation pending')).toBeVisible();
  await expect(blockedReasonsSection.getByText('Gate gate-review is waiting for verification_ready')).toBeVisible();
  await expect(linksSection.getByText('event-mutation-001')).toBeVisible();
  await expect(reviewAttemptCards.nth(0).locator('.runtime-replay-card-head > strong')).toHaveText('assign-review-1');
  await expect(reviewAttemptCards.nth(1).locator('.runtime-replay-card-head > strong')).toHaveText('assign-review-2');
  await expect(replayInspector.getByText('verify.verification_ready')).toBeVisible();
  await expect(replayInspector.getByText('event-mutation-decision-001')).toBeVisible();
});

test('shows replay evidence for selected runtime nodes', async ({ page }) => {
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
  });

  await page.goto(
    '/?workflow_path=.bureauless/mutation-demo/workflow.yaml&ledger_path=.bureauless/mutation-demo/ledger.yaml',
  );

  const replayPanel = page.getByRole('region', { name: 'Replay inspector' });
  const runtimeList = page.getByRole('region', { name: /Runtime nodes/ });
  const selectedNodeCard = replayPanel.locator('.runtime-replay-summary .runtime-summary-card').filter({ hasText: 'Selected node' });
  const assignmentAttemptsSection = replayPanel.locator('.runtime-replay-section').filter({ hasText: 'Assignment attempts' });
  const blockedReasonsSection = replayPanel.locator('.runtime-replay-section').filter({ hasText: 'Blocked reasons' });
  const linksSection = replayPanel.locator('.runtime-replay-section').filter({ hasText: 'Supersession / decision links' });
  const reviewAttemptCard = assignmentAttemptsSection.locator('.runtime-replay-card').first();
  const decisionLinkCard = linksSection.locator('.runtime-replay-card').first();

  await expect(selectedNodeCard.locator('strong')).toHaveText('prepare');
  await expect(replayPanel.getByText('Emitted events')).toBeVisible();
  await expect(replayPanel.getByText('Assignment attempts')).toBeVisible();
  await expect(replayPanel.getByText('Blocked reasons')).toBeVisible();
  await expect(replayPanel.getByText('Supersession / decision links')).toBeVisible();
  await expect(replayPanel.getByText('Select a runtime node to inspect replay evidence.')).toHaveCount(0);

  const mutationPanel = page.getByRole('region', { name: 'Runtime workflow mutations' });
  await mutationPanel.getByRole('button', { name: 'review', exact: true }).first().dispatchEvent('click');
  await expect(selectedNodeCard.locator('strong')).toHaveText('review');
  await expect(replayPanel.locator('.runtime-replay-card-head > strong').filter({ hasText: 'assign-review-1' })).toBeVisible();

  await runtimeList.getByRole('button', { name: /^review\b/i }).dispatchEvent('click');

  await expect(selectedNodeCard.locator('strong')).toHaveText('review');
  await expect(replayPanel.getByText('review.review_complete')).toBeVisible();
  await expect(reviewAttemptCard.locator('.runtime-replay-card-head > strong')).toHaveText('assign-review-1');
  await expect(blockedReasonsSection.getByText('mutation pending')).toBeVisible();
  await expect(decisionLinkCard.locator('.runtime-replay-card-head > strong')).toHaveText('mutation-001');
});

test('overlays gatekeeper state and blocked reasons on runtime nodes', async ({ page }) => {
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
    gatekeeperResponse: { body: gatekeeperFixture },
  });

  await page.goto(
    '/?workflow_path=.bureauless/mutation-demo/workflow.yaml&ledger_path=.bureauless/mutation-demo/ledger.yaml',
  );

  const runtimeList = page.getByRole('region', { name: /Runtime nodes/ });
  const runtimeInspector = page.getByRole('region', { name: 'Runtime node inspector' });
  const summary = page.getByRole('region', { name: 'Runtime workflow summary' });

  await expect(summary.getByText('2 runnable')).toBeVisible();
  await expect(summary.getByText(/1 blocked, 0 needs review, 1 completed/)).toBeVisible();

  const reviewChip = runtimeList.getByRole('button', { name: /^review\b/i });
  await expect(reviewChip.locator('.runtime-state-pill.blocked')).toContainText('Blocked');
  await expect(reviewChip.getByText('mutation pending: event-mutation-001')).toBeVisible();

  await reviewChip.dispatchEvent('click');

  await expect(runtimeInspector.locator('.runtime-node-inspector-badges .runtime-state-pill.blocked')).toContainText('Blocked');
  await expect(runtimeInspector.getByText('Why this node is not runnable')).toBeVisible();
  await expect(
    runtimeInspector.getByText('Workflow mutation mutation-001 may invalidate node review'),
  ).toBeVisible();
  await expect(runtimeInspector.getByText('Mutation:')).toBeVisible();
  await expect(runtimeInspector.getByText('event-mutation-001')).toBeVisible();
  await expect(runtimeInspector.getByText('Gate gate-review is waiting for verification_ready')).toBeVisible();
  await expect(runtimeInspector.getByText('Missing ref:')).toBeVisible();
  await expect(runtimeInspector.getByText('verify.verification_ready')).toBeVisible();
  await expect(runtimeInspector.getByText('Gate:')).toBeVisible();
  await expect(runtimeInspector.locator('code').filter({ hasText: 'gate-review' })).toBeVisible();
});

test('shows a clear load failure when the DAG file is missing', async ({ page }) => {
  await mockWorkbenchApi(page, {
    dagResponse: {
      status: 404,
      body: { error: 'No such file or directory: examples/optimization_dag.yaml' },
    },
  });

  await page.addInitScript(() => {
    window.localStorage.clear();
  });
  await page.goto('/');

  await expect(page.getByRole('alert')).toContainText(/DAG file not found|Unable to load the DAG/);
  await expect(page.getByText('examples/optimization_dag.yaml')).toBeVisible();
  await expect(page.getByText('Diagnostics')).toHaveCount(0);
});
