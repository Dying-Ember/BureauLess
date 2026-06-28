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
    onMutationRequest?: (url: string) => void;
    onMutationDecision?: (payload: unknown) => void;
    mutationDecisionDelayMs?: number;
    mutationDecisionResponse?: (payload: unknown) => { status?: number; body?: unknown };
    gatekeeperResponse?: { status?: number; body?: unknown };
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

  await page.route('**/api/mission?**', async (route) => {
    options.onMissionRequest?.(route.request().url());
    await route.fulfill({
      status: options.missionResponse?.status ?? 200,
      contentType: 'application/json',
      body: JSON.stringify(options.missionResponse?.body ?? missionFixture),
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

  const before = await graphNodeBox(page, 'Baseline Inventory');
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

  const reset = await graphNodeBox(page, 'Baseline Inventory');
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
  await page.getByRole('button', { name: 'Apply' }).click();

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
  await mockWorkbenchApi(page, {
    mutationResponse: { body: mutationFixture },
  });

  await page.goto('/?workflow_path=.bureauless/mutation-demo/workflow.yaml&ledger_path=.bureauless/mutation-demo/ledger.yaml');

  const runtimeSources = page.getByRole('region', { name: 'Runtime sources' });
  const missionPanel = page.getByRole('region', { name: 'Mission summary' });
  const ledgerPanel = page.getByRole('region', { name: 'Ledger summary' });

  await expect(runtimeSources.getByLabel('Mission path')).toHaveValue('.bureauless/mutation-demo/mission.yaml');
  await expect(missionPanel.locator('dd').first()).toHaveText('demo');
  await expect(missionPanel.getByText('Keep the runtime workflow healthy.')).toBeVisible();
  await expect(ledgerPanel.getByText('3')).toBeVisible();
  await expect(ledgerPanel.getByText('2')).toBeVisible();
  await expect(ledgerPanel.getByText('1')).toBeVisible();
  await expect(ledgerPanel.getByText('Artifacts')).toBeVisible();
  await expect(ledgerPanel.getByText('Risks')).toBeVisible();
  await expect(ledgerPanel.getByText('Decisions')).toBeVisible();

  await runtimeSources.getByLabel('Mission path').fill('examples/missions/custom/mission.yaml');
  await runtimeSources.getByLabel('Workflow path').fill('examples/missions/custom/workflow.yaml');
  await runtimeSources.getByLabel('Ledger path').fill('examples/missions/custom/ledger.yaml');
  await expect(runtimeSources.getByLabel('Mission path')).toHaveValue('examples/missions/custom/mission.yaml');
  await expect(runtimeSources.getByLabel('Workflow path')).toHaveValue('examples/missions/custom/workflow.yaml');
  await expect(runtimeSources.getByLabel('Ledger path')).toHaveValue('examples/missions/custom/ledger.yaml');
  const applyRuntimeSources = runtimeSources.getByRole('button', { name: 'Apply runtime sources' });
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
