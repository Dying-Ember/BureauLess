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

export type DagResponse = {
  schema_version: string;
  project: string;
  default_review_model: string;
  nodes: TaskNode[];
  edges: Array<{ id: string; source: string; target: string }>;
};

export type NodeState = 'ready' | 'blocked' | 'completed' | 'needs_review';

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

const params = new URLSearchParams({
  path: 'examples/optimization_dag.yaml',
});

export async function fetchDag(): Promise<DagResponse> {
  const response = await fetch(`/api/dag?${params}`);
  return expectOk(response);
}

export async function fetchState(): Promise<StateResponse> {
  const response = await fetch(
    `/api/state?dag_path=examples/optimization_dag.yaml&runs_dir=runs`,
  );
  return expectOk(response);
}

export async function fetchRuns(): Promise<{ runs: RunRecord[] }> {
  const response = await fetch('/api/runs?runs_dir=runs');
  return expectOk(response);
}

export async function fetchPrompt(taskId: string): Promise<{ task_id: string; prompt: string }> {
  const response = await fetch(
    `/api/prompt/${encodeURIComponent(taskId)}?dag_path=examples/optimization_dag.yaml`,
  );
  return expectOk(response);
}

async function expectOk<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}
