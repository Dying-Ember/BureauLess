export type TaskNode = {
  id: string;
  title: string;
  goal: string;
  dependencies: string[];
  target_files: string[];
  context_files: string[];
  allowed_models: string[];
  recommended_model: string;
  risk_level: 'low' | 'medium' | 'high';
  review_gate: 'auto_pass' | 'orchestrator_review' | 'human_review';
  acceptance_criteria: string[];
  verification_commands: string[];
  do_not: string[];
  prompt_template: string;
  failure_policy: string;
  outputs: string[];
  tags: string[];
};

export type NodeMetadataUpdates = Partial<
  Pick<TaskNode, 'recommended_model' | 'risk_level' | 'review_gate' | 'failure_policy' | 'tags'>
>;

export type NodeDependenciesUpdateRequest = {
  dag_path: string;
  task_id: string;
  dependencies: string[];
};

export type NodeCreateRequest = {
  dag_path: string;
  node: TaskNode;
};

export type DagResponse = {
  schema_version: string;
  project: string;
  default_review_model: string;
  nodes: TaskNode[];
  edges: Array<{ id: string; source: string; target: string }>;
};

export type NodeState = 'ready' | 'blocked' | 'completed' | 'needs_review';

export type ValidationError = {
  code: string;
  message: string;
  line?: number;
  column?: number;
  fields?: string[];
  node_id?: string;
  dependency?: string;
};

export type ValidationResponse = {
  ok: boolean;
  errors: ValidationError[];
};

export type StateResponse = {
  states: Record<string, NodeState>;
  ready: string[];
};

export type RunRecord = {
  run_id: string;
  task_id: string;
  model: string;
  status: string;
  output_commit?: string | null;
  changed_files: string[];
  verification_result?: string | null;
  review_status: string;
  finished_at: string;
};

export type ReviewAction = 'approve' | 'reject' | 'pending';

export type ReviewRequest = {
  dag_path: string;
  runs_dir?: string;
  task_id: string;
  review_status: string;
  run_id?: string | null;
};

export type WorkbenchPaths = {
  dagPath: string;
  runsDir: string;
};

export type MissionResponse = {
  mission_id: string;
  goal: string;
  status: string;
  default_mode: string;
  allowed_modes: string[];
  budget: Record<string, unknown> | null;
  models: Record<string, unknown>;
  human_gate: Record<string, unknown> | null;
};

export type LedgerResponse = {
  mission_id: string;
  ledger_version: string | number;
  current_goal: string;
  current_plan_ref: string | null;
  public_findings: Array<Record<string, unknown>>;
  decisions: Array<Record<string, unknown>>;
  risks: Array<Record<string, unknown>>;
  artifacts: Array<Record<string, unknown>>;
  broadcasts: Array<Record<string, unknown>>;
  open_questions: Array<Record<string, unknown>>;
  event_log: Array<Record<string, unknown>>;
};

export type MutationProposalInspection = {
  proposal_id: string;
  proposal_event_id: string;
  state: 'pending' | 'accepted' | 'rejected';
  decision_event_id?: string;
  affected_node_ids: string[];
  affected_assignments: string[];
  superseded_assignments: string[];
  evidence_refs: string[];
  proposal: {
    reason?: string;
    rationale?: string;
    proposed_changes?: Record<string, unknown[]>;
  };
};

export type RuntimeWorkflowWaitsFor =
  | string[]
  | {
      all_of?: string[];
      any_of?: string[];
    };

export type RuntimeWorkflowNode = {
  id: string;
  role: string;
  waits_for: RuntimeWorkflowWaitsFor;
  emits: string[];
};

export type RuntimeWorkflowGate = {
  id: string;
  node_id: string;
  requires: string[];
};

export type RuntimeWorkflow = {
  workflow_id: string;
  mission_id?: string;
  mode?: string;
  status?: string;
  reason?: string | null;
  proposed_by?: string | null;
  roles: Record<
    string,
    {
      can_emit: string[];
      can_consume: string[];
    }
  >;
  events: Record<
    string,
    {
      producer_roles: string[];
    }
  >;
  nodes: RuntimeWorkflowNode[];
  gates: RuntimeWorkflowGate[];
  terminal_events: string[];
};

export type MutationInspectionResponse = {
  workflow_id: string;
  current_workflow: RuntimeWorkflow;
  proposals: MutationProposalInspection[];
};

export type GatekeeperBlockedReason = {
  code: string;
  message: string;
  missing_ref?: string;
  gate_id?: string;
  assignment_id?: string;
  mutation_event_id?: string;
};

export type GatekeeperDecisionState =
  | 'runnable'
  | 'blocked'
  | 'completed'
  | 'needs_review'
  | 'superseded'
  | 'ready';

export type GatekeeperDecision = {
  node_id: string;
  state: GatekeeperDecisionState;
  blocked_reasons: GatekeeperBlockedReason[];
};

export type GatekeeperResponse = {
  workflow_id: string;
  ready: string[];
  decisions: Record<string, GatekeeperDecision>;
};

export type ReplayAssignmentAttempt = {
  assignment_id: string;
  node_id: string;
  state:
    | 'in_flight'
    | 'awaiting_acceptance'
    | 'completed'
    | 'rejected'
    | 'timed_out'
    | 'cancelled'
    | 'superseded';
  created_event_id?: string;
  terminal_event_id?: string;
  terminal_event_type?: string;
  retry_of?: string;
  superseded_by?: string;
};

export type ReplayBlockedReason = GatekeeperBlockedReason;

export type ReplayNodeState = {
  node_id: string;
  state: 'runnable' | 'blocked' | 'completed';
  emitted_events: string[];
  blocked_reasons: ReplayBlockedReason[];
  assignment_attempts: ReplayAssignmentAttempt[];
};

export type ReplayMutationProposal = {
  proposal_id: string;
  proposal_event_id: string;
  state: 'pending' | 'accepted' | 'rejected';
  affected_node_ids: string[];
  decision_event_id?: string;
};

export type ReplayResponse = {
  workflow_id: string;
  terminal_complete: boolean;
  nodes: Record<string, ReplayNodeState>;
  mutation_proposals: Record<string, ReplayMutationProposal>;
};

export type MutationWorkbenchPaths = {
  missionPath: string;
  workflowPath: string;
  ledgerPath: string;
  artifactManifestPath: string;
};

export type ArtifactSessionManifestStep = {
  node_id: string;
  assignment_path: string;
  context_capsule_path: string;
  context_request_path?: string | null;
  context_resolution_path?: string | null;
  session_path: string;
  result_path?: string | null;
  node_outcome_path?: string | null;
  review_decision_path?: string | null;
  turn_report_path?: string | null;
  dispatch_packet_path?: string | null;
  record_status: string;
  failure_reason?: string | null;
  emitted_events?: string[];
  outcome_event_id?: string;
  review_event_id?: string;
  ready_after: string[];
  node_state_after: string;
};

export type ArtifactSessionManifestResponse = {
  milestone: string;
  flow_id: string;
  workspace: string;
  mission_path: string;
  workflow_path: string;
  ledger_path: string;
  agent: string;
  target_model: string;
  target_provider: string;
  routing_decision_path?: string | null;
  advisor_gate_decision_path?: string | null;
  advisor_gate_outcome_path?: string | null;
  metrics_summary_path?: string | null;
  workbench_url: string;
  steps: ArtifactSessionManifestStep[];
  failure: Record<string, unknown> | null;
  terminal_complete: boolean;
  ready: string[];
  node_states: Record<string, string>;
  manifest_path: string;
};

export type RoutingDecisionResponse = {
  decision_type: 'routing_decision';
  mission_id: string;
  workflow_id?: string | null;
  selected_mode: string;
  selection_policy_version: string;
  triggered_rules: string[];
  rejected_modes: Array<{ mode: string; rejected_because: string }>;
  estimated_coordination_ratio: number;
  budget_confidence: string;
  reason: string;
  budget_reason?: string | null;
  risk_reason?: string | null;
  advisor_gate_decision: {
    invoked: boolean;
    policy_version: string;
    reason: string[];
    decision_basis: string;
  };
};

export type AssignmentResponse = {
  assignment_id: string;
  workflow_id: string;
  node_id: string;
  role: string;
  goal: string;
  visible_context: Record<string, unknown>;
  artifact_refs: Array<Record<string, unknown>>;
  allowed_tools: string[];
  forbidden_actions: string[];
  expected_events: string[];
  outcome_metrics_policy: Record<string, unknown>;
};

export type ContextCapsuleResponse = Record<string, unknown> & {
  assignment_id: string;
  workflow_id: string;
  node_id: string;
  role: string;
};

export type ContextRequestResponse = {
  context_request_id: string;
  assignment_id: string;
  missing_information: string;
  requested_refs: string[];
  expected_value?: string | null;
};

export type ContextResolutionResponse = {
  context_request_id: string;
  assignment_id: string;
  status: string;
  granted_artifacts: Array<Record<string, unknown>>;
  denied_refs: string[];
  unavailable_refs: string[];
};

export type ResultResponse = {
  result_id: string;
  assignment_id: string;
  agent_id: string;
  status: string;
  effective_model?: string | null;
  effective_provider?: string | null;
  emitted_events: string[];
  artifacts: Array<Record<string, unknown>>;
  outcome_metrics: Record<string, unknown>;
  verification: Record<string, unknown>;
  native_log_refs: Array<Record<string, unknown>>;
  mutation_proposal_refs: string[];
  review_status?: string | null;
};

export type NodeOutcomeResponse = {
  outcome_id: string;
  assignment_id: string;
  session_id: string;
  workflow_id: string;
  node_id: string;
  role: string;
  agent_id: string;
  status: string;
  effective_model?: string | null;
  effective_provider?: string | null;
  pre_state_ref?: string | null;
  post_state_ref?: string | null;
  observed_delta: Record<string, unknown>;
  verification: Record<string, unknown>;
  native_log_refs: Array<Record<string, unknown>>;
  diff_refs: Array<Record<string, unknown>>;
  outcome_metrics: Record<string, unknown>;
  extraction: Record<string, unknown>;
};

export type AdvisorOutcomeResponse = {
  decision_type: 'advisor_outcome';
  outcome_id: string;
  mission_id: string;
  workflow_id?: string | null;
  status: string;
  source_decision_type: string;
  source_decision_ref: string;
  advisor_decision_ref: string;
  advisor_recommendation_ref?: string | null;
  advisor_invocation_ref?: string | null;
  recommendation_applied?: boolean | null;
  classification?: string | null;
  pending_reason?: string | null;
  actual_advisor_tokens?: number;
  actual_advisor_cost_usd?: number;
  actual_total_tokens?: number;
  rework_count?: number;
  broadcast_tokens?: number;
  duplicate_context_observed?: boolean;
  price_snapshot_attribution?: Record<string, unknown> | null;
  notes?: string | null;
};

export type TurnReportResponse = {
  report_id: string;
  assignment_id: string;
  agent_id: string;
  status: string;
  tool_calls_since_last_report: number;
  summary: string;
  new_findings: Array<Record<string, unknown>>;
  artifact_refs: Array<Record<string, unknown>>;
  blockers: Array<Record<string, unknown>>;
  suggested_ledger_updates: Array<Record<string, unknown>>;
  token_usage: {
    input_tokens: number;
    output_tokens: number;
  };
};

export type DispatchPacketResponse = {
  packet_id: string;
  mission_id: string;
  workflow_id: string;
  routing_decision: RoutingDecisionResponse;
  assignment: AssignmentResponse;
  review_constraints: Record<string, unknown>;
  turn_report_policy: Record<string, unknown>;
};

export type MetricsSummaryResponse = {
  entries: Array<Record<string, unknown>>;
  summary?: Array<Record<string, unknown>>;
  observed_budget?: Record<string, unknown>;
  advisor_outcomes?: Array<Record<string, unknown>>;
  advisor_score_summary?: Record<string, unknown>;
  context_summary?: Record<string, unknown>;
  policy_recommendations?: Array<Record<string, unknown>>;
};

export type MutationDecisionRequest = {
  workflow_path: string;
  ledger_path: string;
  proposal_event_id: string;
  decision: 'accept' | 'reject';
  actor?: 'orchestrator' | 'human';
  reason?: string;
};

export const DEFAULT_DAG_PATH = 'examples/optimization_dag.yaml';
export const DEFAULT_RUNS_DIR = 'runs';
export const DEFAULT_MISSION_PATH = 'examples/missions/demo/mission.yaml';
export const DEFAULT_WORKFLOW_PATH = 'examples/missions/demo/workflows/coder_reviewer_committer.yaml';
export const DEFAULT_LEDGER_PATH = 'examples/missions/demo/ledger.yaml';

export async function fetchDag(dagPath: string = DEFAULT_DAG_PATH): Promise<DagResponse> {
  const response = await fetch(`/api/dag?path=${encodeURIComponent(dagPath)}`);
  return expectOk(response);
}

export async function fetchValidation(dagPath: string = DEFAULT_DAG_PATH): Promise<ValidationResponse> {
  const response = await fetch(`/api/validate?path=${encodeURIComponent(dagPath)}`);
  return expectOk(response);
}

export async function fetchState(
  dagPath: string = DEFAULT_DAG_PATH,
  runsDir: string = DEFAULT_RUNS_DIR,
): Promise<StateResponse> {
  const response = await fetch(`/api/state?dag_path=${encodeURIComponent(dagPath)}&runs_dir=${encodeURIComponent(runsDir)}`);
  return expectOk(response);
}

export async function fetchRuns(runsDir: string = DEFAULT_RUNS_DIR): Promise<{ runs: RunRecord[] }> {
  const response = await fetch(`/api/runs?runs_dir=${encodeURIComponent(runsDir)}`);
  return expectOk(response);
}

export async function fetchPrompt(
  taskId: string,
  dagPath: string = DEFAULT_DAG_PATH,
): Promise<{ task_id: string; prompt: string }> {
  const response = await fetch(
    `/api/prompt/${encodeURIComponent(taskId)}?dag_path=${encodeURIComponent(dagPath)}`,
  );
  return expectOk(response);
}

export async function fetchMission(path: string = DEFAULT_MISSION_PATH): Promise<MissionResponse> {
  const response = await fetch(`/api/mission?path=${encodeURIComponent(path)}`);
  return expectOk(response);
}

export async function fetchArtifactSessionManifest(
  path: string,
): Promise<ArtifactSessionManifestResponse> {
  const response = await fetch(`/api/artifact-session-manifest?path=${encodeURIComponent(path)}`);
  return expectOk(response);
}

export async function fetchRoutingDecision(path: string): Promise<RoutingDecisionResponse> {
  const response = await fetch(`/api/routing-decision?path=${encodeURIComponent(path)}`);
  return expectOk(response);
}

export async function fetchAssignment(path: string): Promise<AssignmentResponse> {
  const response = await fetch(`/api/assignment?path=${encodeURIComponent(path)}`);
  return expectOk(response);
}

export async function fetchContextCapsuleByPath(path: string): Promise<ContextCapsuleResponse> {
  const response = await fetch(`/api/context-capsule?path=${encodeURIComponent(path)}`);
  return expectOk(response);
}

export async function fetchContextRequest(path: string): Promise<ContextRequestResponse> {
  const response = await fetch(`/api/context-request?path=${encodeURIComponent(path)}`);
  return expectOk(response);
}

export async function resolveContextRequest(request: {
  assignment_path: string;
  ledger_path: string;
  context_request_path: string;
  max_artifacts?: number;
}): Promise<ContextResolutionResponse> {
  const response = await fetch('/api/context-request/resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      max_artifacts: request.max_artifacts ?? 1,
      ...request,
    }),
  });
  return expectOk(response);
}

export async function fetchLedger(path: string = DEFAULT_LEDGER_PATH): Promise<LedgerResponse> {
  const response = await fetch(`/api/ledger?path=${encodeURIComponent(path)}`);
  return expectOk(response);
}

export async function fetchResult(path: string): Promise<ResultResponse> {
  const response = await fetch(`/api/result?path=${encodeURIComponent(path)}`);
  return expectOk(response);
}

export async function fetchNodeOutcome(path: string): Promise<NodeOutcomeResponse> {
  const response = await fetch(`/api/node-outcome?path=${encodeURIComponent(path)}`);
  return expectOk(response);
}

export async function fetchAdvisorOutcome(path: string): Promise<AdvisorOutcomeResponse> {
  const response = await fetch(`/api/advisor-outcome?path=${encodeURIComponent(path)}`);
  return expectOk(response);
}

export async function fetchTurnReport(path: string): Promise<TurnReportResponse> {
  const response = await fetch(`/api/turn-report?path=${encodeURIComponent(path)}`);
  return expectOk(response);
}

export async function fetchDispatchPacket(path: string): Promise<DispatchPacketResponse> {
  const response = await fetch(`/api/dispatch-packet?path=${encodeURIComponent(path)}`);
  return expectOk(response);
}

export async function fetchMetricsSummary(path: string): Promise<MetricsSummaryResponse> {
  const response = await fetch(`/api/metrics?path=${encodeURIComponent(path)}`);
  return expectOk(response);
}

export async function updateReviewStatus(request: ReviewRequest): Promise<{ path: string }> {
  const { runs_dir, ...body } = request;
  const response = await fetch('/api/review', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      runs_dir: runs_dir ?? DEFAULT_RUNS_DIR,
      ...body,
    }),
  });
  return expectOk(response);
}

export async function updateNodeMetadata(request: {
  dag_path: string;
  task_id: string;
  updates: NodeMetadataUpdates;
}): Promise<{ path: string; backup_path: string; node: TaskNode }> {
  const response = await fetch('/api/dag/node-metadata', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });
  return expectOk(response);
}

export async function updateNodeDependencies(
  request: NodeDependenciesUpdateRequest,
): Promise<{ path: string; backup_path: string; node: TaskNode }> {
  const response = await fetch('/api/dag/node-dependencies', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });
  return expectOk(response);
}

export async function createNode(request: NodeCreateRequest): Promise<{ path: string; backup_path: string; node: TaskNode }> {
  const response = await fetch('/api/dag/nodes', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });
  return expectOk(response);
}

export async function fetchMutations(
  workflowPath: string = DEFAULT_WORKFLOW_PATH,
  ledgerPath: string = DEFAULT_LEDGER_PATH,
): Promise<MutationInspectionResponse> {
  const response = await fetch(
    `/api/mutations?workflow_path=${encodeURIComponent(workflowPath)}&ledger_path=${encodeURIComponent(ledgerPath)}`,
  );
  return expectOk(response);
}

export async function fetchGatekeeper(
  workflowPath: string = DEFAULT_WORKFLOW_PATH,
  ledgerPath: string = DEFAULT_LEDGER_PATH,
): Promise<GatekeeperResponse> {
  const response = await fetch(
    `/api/gatekeeper?workflow_path=${encodeURIComponent(workflowPath)}&ledger_path=${encodeURIComponent(ledgerPath)}`,
  );
  return expectOk(response);
}

export async function fetchReplay(
  workflowPath: string = DEFAULT_WORKFLOW_PATH,
  ledgerPath: string = DEFAULT_LEDGER_PATH,
): Promise<ReplayResponse> {
  const response = await fetch(
    `/api/replay?workflow_path=${encodeURIComponent(workflowPath)}&ledger_path=${encodeURIComponent(ledgerPath)}`,
  );
  return expectOk(response);
}

export async function decideMutation(
  request: MutationDecisionRequest,
): Promise<MutationInspectionResponse> {
  const response = await fetch('/api/mutations/decision', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  return expectOk(response);
}

async function expectOk<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

async function readErrorMessage(response: Response): Promise<string> {
  const fallback = `Request failed: ${response.status}`;
  const contentType = response.headers.get('content-type') ?? '';

  try {
    if (contentType.includes('application/json')) {
      const body = (await response.json()) as Record<string, unknown>;
      const message =
        pickString(body, 'error') ??
        pickString(body, 'message') ??
        pickString(body, 'detail');
      if (message) {
        return message;
      }

      const errors = body.errors;
      if (Array.isArray(errors)) {
        const joined = errors
          .map((error) => {
            if (error && typeof error === 'object') {
              return pickString(error as Record<string, unknown>, 'message');
            }
            return null;
          })
          .filter((message): message is string => Boolean(message))
          .join('; ');
        if (joined) {
          return joined;
        }
      }
    }
    const text = await response.text();
    if (text.trim()) {
      return text.trim();
    }
  } catch {
    return fallback;
  }

  return fallback;
}

function pickString(record: Record<string, unknown>, key: string): string | null {
  const value = record[key];
  return typeof value === 'string' && value.trim() ? value : null;
}
