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

export const DEFAULT_DAG_PATH = 'examples/optimization_dag.yaml';
export const DEFAULT_RUNS_DIR = 'runs';

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
