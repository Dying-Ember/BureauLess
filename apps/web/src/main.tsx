import '@xyflow/react/dist/style.css';
import './styles.css';

import { QueryClient, QueryClientProvider, useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Background,
  ConnectionLineType,
  Controls,
  Handle,
  Panel,
  Position,
  ReactFlow,
  ViewportPortal,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
  type XYPosition,
} from '@xyflow/react';
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Copy,
  GitBranch,
  FolderOpen,
  LayoutList,
  Moon,
  Pencil,
  Plus,
  RefreshCcw,
  Save,
  Sun,
  Tag,
  Undo2,
  Workflow,
  X,
  XCircle,
} from 'lucide-react';
import { StrictMode, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';

import {
  createNode,
  DEFAULT_DAG_PATH,
  DEFAULT_RUNS_DIR,
  fetchDag,
  fetchPrompt,
  fetchRuns,
  fetchState,
  fetchValidation,
  type WorkbenchPaths,
  updateNodeDependencies,
  updateNodeMetadata,
  updateReviewStatus,
  type NodeState,
  type ReviewAction,
  type RunRecord,
  type TaskNode,
  type ValidationError,
} from './api/client';
import { type ThemeMode, useThemeMode } from './theme/theme';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

type MetadataDraft = {
  recommended_model: string;
  risk_level: TaskNode['risk_level'];
  review_gate: TaskNode['review_gate'];
  failure_policy: string;
  tags: string;
};

type DependencyDraft = string[];

type DependencySaveDraft = {
  taskId: string;
  dependencies: DependencyDraft;
};

type GraphDependencyDraft = {
  targetId: string;
  dependencies: DependencyDraft;
  undo?: {
    previousDependencies: DependencyDraft;
    label: string;
  };
};

type FlowNodePositions = Record<string, XYPosition>;

type DagFlowNodeData = {
  title: string;
  recommendedModel: string;
  reviewGate: string;
  nodeState: string;
  riskLevel: TaskNode['risk_level'];
};

type DragPreviewState = {
  id: string;
  data: DagFlowNodeData;
  initialPosition: XYPosition;
  currentPosition: XYPosition;
};

type NodeCreationDraft = {
  id: string;
  title: string;
  goal: string;
  dependencies: string;
  target_files: string;
  context_files: string;
  allowed_models: string;
  recommended_model: string;
  risk_level: TaskNode['risk_level'];
  review_gate: TaskNode['review_gate'];
  acceptance_criteria: string;
  verification_commands: string;
  do_not: string;
  prompt_template: string;
  failure_policy: string;
  outputs: string;
  tags: string;
};

const FAILURE_POLICIES = ['retry_same_model', 'escalate_to_large_model', 'send_to_human', 'split_task_further'] as const;

declare global {
  interface Window {
    agentsSwarm?: {
      openDag?: () => Promise<string | null>;
      openRunsDir?: () => Promise<string | null>;
      platform?: string;
    };
  }
}

function App() {
  return (
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <Workbench />
      </QueryClientProvider>
    </StrictMode>
  );
}

function FlowNodeCard({ data, className = '' }: { data: DagFlowNodeData; className?: string }) {
  return (
    <div className={`flow-node ${data.nodeState} risk-${data.riskLevel} ${className}`.trim()}>
      <strong>{data.title}</strong>
      <span>{data.recommendedModel}</span>
      <small>{data.reviewGate}</small>
    </div>
  );
}

function DagFlowNode({ data }: NodeProps<Node<DagFlowNodeData>>) {
  return (
    <div className="flow-node-shell">
      <Handle type="target" position={Position.Left} className="flow-handle target" />
      <FlowNodeCard data={data} />
      <Handle type="source" position={Position.Right} className="flow-handle source" />
    </div>
  );
}

const FLOW_NODE_TYPES = {
  dag: DagFlowNode,
};

function Workbench() {
  const [paths, setPaths] = useState<WorkbenchPaths>(loadWorkbenchPaths);
  const [pathDraft, setPathDraft] = useState<WorkbenchPaths>(paths);
  const [manualNodePositions, setManualNodePositions] = useState<FlowNodePositions>(() => loadGraphNodePositions(paths.dagPath));
  const dag = useQuery({ queryKey: ['dag', paths.dagPath], queryFn: () => fetchDag(paths.dagPath) });
  const validation = useQuery({ queryKey: ['validation', paths.dagPath], queryFn: () => fetchValidation(paths.dagPath) });
  const state = useQuery({
    queryKey: ['state', paths.dagPath, paths.runsDir],
    queryFn: () => fetchState(paths.dagPath, paths.runsDir),
  });
  const runs = useQuery({ queryKey: ['runs', paths.runsDir], queryFn: () => fetchRuns(paths.runsDir) });
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const [selectedRunId, setSelectedRunId] = useState<string | undefined>();
  const [isCreatingNode, setIsCreatingNode] = useState(false);
  const [inspectorHasUnsavedChanges, setInspectorHasUnsavedChanges] = useState(false);
  const [graphDependencyDraft, setGraphDependencyDraft] = useState<GraphDependencyDraft | null>(null);
  const [graphDependencyMessage, setGraphDependencyMessage] = useState<string | null>(null);
  const [dragPreview, setDragPreview] = useState<DragPreviewState | null>(null);
  const { mode, setMode } = useThemeMode();
  const desktopBridge = getDesktopBridge();
  const graphDependencyMutation = useDependencySave(paths);

  useEffect(() => {
    setPathDraft(paths);
  }, [paths]);

  useEffect(() => {
    setManualNodePositions(loadGraphNodePositions(paths.dagPath));
  }, [paths.dagPath]);

  const validationErrors = useMemo(
    () =>
      validation.data?.ok === false
        ? validation.data.errors.map((error) => ({
            key: `${error.code}:${error.message}`,
            headline: diagnosticHeadline(error),
          }))
        : [],
    [validation.data],
  );
  const validationStatus = useMemo(
    () => {
      if (validation.isError) {
        return 'unavailable';
      }
      if (validation.data?.ok === false) {
        return 'error';
      }
      if (validation.isLoading) {
        return 'checking';
      }
      return 'ok';
    },
    [validation.data?.ok, validation.isError, validation.isLoading],
  );
  const validationSummary = useMemo(() => {
    if (validation.isError) {
      return validation.error instanceof Error ? validation.error.message : 'Validation check failed';
    }
    if (validation.data?.ok === false) {
      return validationErrors.length === 1 ? '1 validation issue' : `${validationErrors.length} validation issues`;
    }
    if (validation.isLoading) {
      return 'Checking DAG';
    }
    return 'No validation issues';
  }, [validation.data?.ok, validation.error, validation.isError, validation.isLoading, validationErrors.length]);

  const dagNodes = dag.data?.nodes ?? [];
  const readyNodeIds = state.data?.ready ?? [];
  const readyNodes = useMemo(
    () => readyNodeIds.map((nodeId) => dagNodes.find((node) => node.id === nodeId)).filter((node): node is TaskNode => Boolean(node)),
    [dagNodes, readyNodeIds],
  );
  const selectedNode = dagNodes.find((node) => node.id === selectedId);
  const graphDependencyDraftNode = graphDependencyDraft
    ? dagNodes.find((node) => node.id === graphDependencyDraft.targetId)
    : undefined;
  const graphDependencyDraftValidation = graphDependencyDraft
    ? validateDependencyDraft(dagNodes, graphDependencyDraft.targetId, graphDependencyDraft.dependencies)
    : null;
  const graphDependencyDraftHasChanges = Boolean(
    graphDependencyDraft &&
      graphDependencyDraftNode &&
      !dependencyDraftMatchesList(graphDependencyDraft.dependencies, graphDependencyDraftNode.dependencies),
  );
  const selectedRuns = useMemo(
    () =>
      (runs.data?.runs ?? [])
        .filter((run) => run.task_id === selectedNode?.id)
        .slice()
        .sort((a, b) => b.finished_at.localeCompare(a.finished_at)),
    [runs.data, selectedNode?.id],
  );
  const selectedRun = selectedRuns.find((run) => run.run_id === selectedRunId) ?? selectedRuns[0];
  const hasManualLayout = dagNodes.some((node) => manualNodePositions[node.id] !== undefined);

  useEffect(() => {
    if (dagNodes.length === 0) {
      if (selectedId !== undefined) {
        setSelectedId(undefined);
      }
      return;
    }

    if (selectedId && !dagNodes.some((node) => node.id === selectedId)) {
      setSelectedId(undefined);
    }
  }, [dagNodes, selectedId]);

  useEffect(() => {
    if (selectedRuns.length === 0) {
      if (selectedRunId !== undefined) {
        setSelectedRunId(undefined);
      }
      return;
    }

    if (!selectedRunId || !selectedRuns.some((run) => run.run_id === selectedRunId)) {
      setSelectedRunId(selectedRuns[0].run_id);
    }
  }, [selectedRuns, selectedRunId]);

  useEffect(() => {
    if (!graphDependencyDraft) {
      return;
    }
    const targetNode = dagNodes.find((node) => node.id === graphDependencyDraft.targetId);
    if (!targetNode) {
      setGraphDependencyDraft(null);
      setGraphDependencyMessage(null);
      graphDependencyMutation.reset();
      return;
    }
    if (dependencyDraftMatchesList(graphDependencyDraft.dependencies, targetNode.dependencies)) {
      setGraphDependencyDraft(null);
      setGraphDependencyMessage(null);
      graphDependencyMutation.reset();
    }
  }, [dagNodes, graphDependencyDraft, graphDependencyMutation]);

  const flowNodes = useMemo<Node[]>(() => {
    const automaticPositions = computeFlowNodePositions(
      dagNodes,
      dagNodes.map((node) => ({
        id: node.id,
        dependencies:
          graphDependencyDraft?.targetId === node.id
            ? graphDependencyDraft.dependencies
            : node.dependencies,
      })),
    );

    return dagNodes.map((node) => {
      const nodeState = state.data?.states[node.id] ?? 'blocked';
      return {
        id: node.id,
        position: manualNodePositions[node.id] ?? automaticPositions.get(node.id) ?? { x: 80, y: 120 },
        data: {
          title: node.title,
          recommendedModel: node.recommended_model,
          reviewGate: node.review_gate,
          nodeState,
          riskLevel: node.risk_level,
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        type: 'dag',
      };
    });
  }, [dagNodes, graphDependencyDraft, manualNodePositions, state.data]);

  const flowEdges = useMemo<Edge[]>(() => {
    const persistedEdges = dag.data?.edges ?? [];
    const draftEdgeIds = new Set(
      graphDependencyDraft?.dependencies.map((dependencyId) => dependencyEdgeId(dependencyId, graphDependencyDraft.targetId)) ?? [],
    );
    const visibleEdges = graphDependencyDraft
      ? [
          ...persistedEdges.filter((edge) => edge.target !== graphDependencyDraft.targetId),
          ...graphDependencyDraft.dependencies.map((dependencyId) => ({
            id: dependencyEdgeId(dependencyId, graphDependencyDraft.targetId),
            source: dependencyId,
            target: graphDependencyDraft.targetId,
          })),
        ]
      : persistedEdges;

    return visibleEdges.map((edge) => ({
      ...edge,
      animated: true,
      ariaLabel: `${edge.source} dependency for ${edge.target}`,
      className: draftEdgeIds.has(edge.id) ? 'flow-edge draft' : 'flow-edge',
      deletable: true,
      focusable: true,
      interactionWidth: 24,
      type: 'smoothstep',
    }));
  }, [dag.data?.edges, graphDependencyDraft]);

  if (dag.isError) {
    return <FullPageError error={dag.error} dagPath={paths.dagPath} onRetry={() => void dag.refetch()} />;
  }

  const confirmDiscardInspectorChanges = () => {
    if (!inspectorHasUnsavedChanges) {
      return true;
    }
    return window.confirm('Discard unsaved changes in the inspector?');
  };

  const attemptSelectNode = (nodeId: string) => {
    if (nodeId === selectedId) {
      return;
    }
    if (!confirmDiscardInspectorChanges()) {
      return;
    }
    setIsCreatingNode(false);
    setSelectedId(nodeId);
  };

  const beginCreateNode = () => {
    if (!confirmDiscardInspectorChanges()) {
      return;
    }
    setSelectedId(undefined);
    setSelectedRunId(undefined);
    setIsCreatingNode(true);
  };

  const applyPathDraft = () => {
    const nextPaths = normalizeWorkbenchPaths(pathDraft);
    setPaths(nextPaths);
    persistWorkbenchPaths(nextPaths);
    setSelectedId(undefined);
    setSelectedRunId(undefined);
    setIsCreatingNode(false);
  };

  const persistDraggedNodePosition = (nodeId: string, position: XYPosition) => {
    setManualNodePositions((current) => {
      const next = {
        ...current,
        [nodeId]: position,
      };
      persistGraphNodePositions(paths.dagPath, next);
      return next;
    });
  };

  const resetGraphLayout = () => {
    setManualNodePositions({});
    persistGraphNodePositions(paths.dagPath, {});
  };

  const startDraggedNodePreview = (node: Node<DagFlowNodeData>) => {
    setDragPreview({
      id: node.id,
      data: node.data,
      initialPosition: node.position,
      currentPosition: node.position,
    });
  };

  const updateDraggedNodePreview = (node: Node<DagFlowNodeData>) => {
    setDragPreview((current) =>
      current?.id === node.id
        ? {
            ...current,
            currentPosition: node.position,
          }
        : current,
    );
  };

  const stopDraggedNodePreview = (node: Node<DagFlowNodeData>) => {
    setDragPreview(null);
    persistDraggedNodePosition(node.id, node.position);
  };

  const pathDraftChanged =
    normalizeWorkbenchPaths(pathDraft).dagPath !== paths.dagPath ||
    normalizeWorkbenchPaths(pathDraft).runsDir !== paths.runsDir;

  const chooseDagPath = async () => {
    const nextDagPath = await desktopBridge?.openDag?.();
    if (nextDagPath) {
      setPathDraft((current) => ({ ...current, dagPath: nextDagPath }));
    }
  };

  const chooseRunsDir = async () => {
    const nextRunsDir = await desktopBridge?.openRunsDir?.();
    if (nextRunsDir) {
      setPathDraft((current) => ({ ...current, runsDir: nextRunsDir }));
    }
  };

  const currentGraphDependenciesForTarget = (targetId: string): DependencyDraft => {
    if (graphDependencyDraft?.targetId === targetId) {
      return graphDependencyDraft.dependencies;
    }
    return dagNodes.find((node) => node.id === targetId)?.dependencies ?? [];
  };

  const stageGraphDependencyConnection = (connection: Connection) => {
    const sourceId = connection.source;
    const targetId = connection.target;
    if (!sourceId || !targetId) {
      setGraphDependencyMessage('Drop the connection on another node to create a dependency.');
      return;
    }
    if (graphDependencyMutation.isPending) {
      return;
    }
    const validationError = validateGraphDependencyConnection(dagNodes, graphDependencyDraft, sourceId, targetId);
    if (validationError) {
      setGraphDependencyMessage(validationError);
      graphDependencyMutation.reset();
      return;
    }

    const previousDependencies = currentGraphDependenciesForTarget(targetId);
    setGraphDependencyDraft({
      targetId,
      dependencies: [...previousDependencies, sourceId],
      undo: {
        previousDependencies,
        label: `Added ${sourceId}`,
      },
    });
    setGraphDependencyMessage(null);
    graphDependencyMutation.reset();
  };

  const stageGraphDependencyRemoval = (edgesToRemove: Edge[]) => {
    if (graphDependencyMutation.isPending || edgesToRemove.length === 0) {
      return;
    }
    const targets = new Set(edgesToRemove.map((edge) => edge.target));
    if (targets.size > 1) {
      setGraphDependencyMessage('Remove dependencies for one target node at a time.');
      graphDependencyMutation.reset();
      return;
    }

    const targetId = edgesToRemove[0].target;
    const sourcesToRemove = edgesToRemove.map((edge) => edge.source);
    if (graphDependencyDraft && graphDependencyDraft.targetId !== targetId) {
      setGraphDependencyMessage(`Save or cancel the pending edit for ${graphDependencyDraft.targetId} before editing ${targetId}.`);
      graphDependencyMutation.reset();
      return;
    }

    const previousDependencies = currentGraphDependenciesForTarget(targetId);
    const missingSource = sourcesToRemove.find((sourceId) => !previousDependencies.includes(sourceId));
    if (missingSource) {
      setGraphDependencyMessage(`${targetId} does not currently depend on ${missingSource}.`);
      graphDependencyMutation.reset();
      return;
    }

    setGraphDependencyDraft({
      targetId,
      dependencies: previousDependencies.filter((dependencyId) => !sourcesToRemove.includes(dependencyId)),
      undo: {
        previousDependencies,
        label: sourcesToRemove.length === 1 ? `Removed ${sourcesToRemove[0]}` : 'Removed dependencies',
      },
    });
    setGraphDependencyMessage(null);
    graphDependencyMutation.reset();
  };

  const undoGraphDependencyEdit = () => {
    if (!graphDependencyDraft?.undo || graphDependencyMutation.isPending) {
      return;
    }
    const targetNode = dagNodes.find((node) => node.id === graphDependencyDraft.targetId);
    if (targetNode && dependencyDraftMatchesList(graphDependencyDraft.undo.previousDependencies, targetNode.dependencies)) {
      setGraphDependencyDraft(null);
    } else {
      setGraphDependencyDraft({
        targetId: graphDependencyDraft.targetId,
        dependencies: graphDependencyDraft.undo.previousDependencies,
      });
    }
    setGraphDependencyMessage(null);
    graphDependencyMutation.reset();
  };

  const cancelGraphDependencyEdit = () => {
    setGraphDependencyDraft(null);
    setGraphDependencyMessage(null);
    graphDependencyMutation.reset();
  };

  const saveGraphDependencyEdit = () => {
    if (!graphDependencyDraft || graphDependencyMutation.isPending) {
      return;
    }
    const validationError = validateDependencyDraft(dagNodes, graphDependencyDraft.targetId, graphDependencyDraft.dependencies);
    if (validationError) {
      setGraphDependencyMessage(validationError);
      graphDependencyMutation.reset();
      return;
    }

    graphDependencyMutation.mutate(
      {
        taskId: graphDependencyDraft.targetId,
        dependencies: graphDependencyDraft.dependencies,
      },
      {
        onSuccess: () => {
          setGraphDependencyDraft(null);
          setGraphDependencyMessage(null);
        },
      },
    );
  };

  const graphDependencyInlineError =
    graphDependencyMessage ??
    graphDependencyDraftValidation ??
    (graphDependencyMutation.error instanceof Error
      ? `Dependency update failed: ${formatDependencyUpdateError(graphDependencyMutation.error.message)}`
      : null);

  return (
    <div className="app-shell">
      <Toolbar
        mode={mode}
        setMode={setMode}
        refetch={() => void Promise.all([dag.refetch(), validation.refetch(), state.refetch(), runs.refetch()])}
      />
      <main className="workspace">
        <aside className="sidebar">
          <section className="ready-panel">
            <div className="pane-title">
              Workspace
              <span className={`workspace-mode ${desktopBridge ? 'desktop' : 'browser'}`}>
                {desktopBridge ? 'Desktop bridge connected' : 'Browser mode'}
              </span>
            </div>
            <div className="metadata-form">
              <label className="field">
                <span>DAG path</span>
                <input
                  type="text"
                  value={pathDraft.dagPath}
                  onChange={(event) =>
                    setPathDraft((current) => ({ ...current, dagPath: event.target.value }))
                  }
                />
                {desktopBridge ? (
                  <div className="metadata-actions">
                    <button type="button" className="metadata-cancel" onClick={() => void chooseDagPath()}>
                      <FolderOpen size={14} />
                      Choose file
                    </button>
                  </div>
                ) : null}
              </label>
              <label className="field">
                <span>Runs directory</span>
                <input
                  type="text"
                  value={pathDraft.runsDir}
                  onChange={(event) =>
                    setPathDraft((current) => ({ ...current, runsDir: event.target.value }))
                  }
                />
                {desktopBridge ? (
                  <div className="metadata-actions">
                    <button type="button" className="metadata-cancel" onClick={() => void chooseRunsDir()}>
                      <FolderOpen size={14} />
                      Choose folder
                    </button>
                  </div>
                ) : null}
              </label>
              <div className="metadata-actions">
                <button type="button" className="metadata-save" onClick={applyPathDraft} disabled={!pathDraftChanged}>
                  Apply
                </button>
              </div>
            </div>
          </section>
          <section className={`diagnostics-panel ${validationStatus}`}>
            <div className="pane-title">
              <AlertTriangle size={16} />
              Diagnostics
              <span className={`diagnostics-status ${validationStatus}`}>{validationSummary}</span>
            </div>
            {validation.data?.ok === false ? (
              <ul className="diagnostics-list" aria-live="polite">
                {validationErrors.map((error) => (
                  <li key={error.key} className="diagnostics-item">
                    <strong>{error.headline}</strong>
                  </li>
                ))}
              </ul>
            ) : validation.isError ? (
              <p className="diagnostics-text" role="status" aria-live="polite">
                Validation check unavailable.
              </p>
            ) : validation.isLoading ? (
              <p className="diagnostics-text" role="status" aria-live="polite">
                Checking the DAG for validation issues.
              </p>
            ) : (
              <p className="diagnostics-text">No validation issues detected.</p>
            )}
          </section>
          <section className="ready-panel">
            <div className="pane-title">
              <LayoutList size={16} />
              Ready nodes
              <span className="pane-count">{readyNodes.length}</span>
            </div>
            {state.isLoading ? (
              <p className="empty-state-message">Resolving ready nodes.</p>
            ) : readyNodes.length === 0 ? (
              <div className="empty-state-card" role="status" aria-live="polite">
                <strong>No ready nodes</strong>
                <p>Every node is either blocked, completed, or waiting on review.</p>
              </div>
            ) : (
              <div className="ready-list">
                {readyNodes.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    className={node.id === selectedNode?.id ? 'ready-item selected' : 'ready-item'}
                    onClick={() => attemptSelectNode(node.id)}
                  >
                    <span>{node.title}</span>
                    <small>{node.id}</small>
                  </button>
                ))}
              </div>
            )}
          </section>
          <section>
            <div className="pane-title">
              <Workflow size={16} /> DAG
              <button type="button" className="metadata-toggle" onClick={beginCreateNode}>
                <Plus size={14} />
                Add node
              </button>
            </div>
            <div className="file-pill">{paths.dagPath}</div>
            <div className="file-pill">{paths.runsDir}</div>
            <div className="filter-row" aria-label="Node states">
              <span>ready</span>
              <span>blocked</span>
              <span>needs review</span>
            </div>
            {dagNodes.length === 0 ? (
              <div className="empty-state-card" role="status" aria-live="polite">
                <strong>No DAG nodes</strong>
                <p>The DAG loaded successfully, but it does not contain any task nodes yet.</p>
              </div>
            ) : (
              <nav className="node-list" aria-label="DAG nodes">
                {dagNodes.map((node) => (
                  <button
                    key={node.id}
                    type="button"
                    className={node.id === selectedNode?.id ? 'node-item selected' : 'node-item'}
                    onClick={() => attemptSelectNode(node.id)}
                  >
                    <span>{node.title}</span>
                    <small className={state.data?.states[node.id] ?? 'blocked'}>{state.data?.states[node.id] ?? 'blocked'}</small>
                  </button>
                ))}
              </nav>
            )}
          </section>
        </aside>
        <section className="graph-pane">
          <AssignmentMatrix
            nodes={dagNodes}
            states={state.data?.states}
            readyNodes={readyNodes}
            selectedNodeId={selectedNode?.id}
            onSelectNode={attemptSelectNode}
          />
          <div className="graph-canvas">
            {graphDependencyDraft || graphDependencyInlineError ? (
              <div className="graph-draft-panel">
                <div className="graph-draft-summary">
                  <strong>{graphDependencyDraft ? 'Unsaved graph dependency edit' : 'Graph dependency edit rejected'}</strong>
                  {graphDependencyDraft ? (
                    <span>
                      {graphDependencyDraft.targetId} waits for{' '}
                      {graphDependencyDraft.dependencies.length > 0 ? graphDependencyDraft.dependencies.join(', ') : 'no upstream nodes'}
                    </span>
                  ) : null}
                  {graphDependencyDraft?.undo ? <small>{graphDependencyDraft.undo.label}</small> : null}
                  {graphDependencyInlineError ? (
                    <p role="alert" aria-live="polite">
                      {graphDependencyInlineError}
                    </p>
                  ) : null}
                </div>
                {graphDependencyDraft ? (
                  <div className="graph-draft-actions">
                    <button
                      type="button"
                      className="metadata-cancel"
                      onClick={undoGraphDependencyEdit}
                      disabled={!graphDependencyDraft.undo || graphDependencyMutation.isPending}
                    >
                      <Undo2 size={14} />
                      Undo
                    </button>
                    <button
                      type="button"
                      className="metadata-save"
                      onClick={saveGraphDependencyEdit}
                      disabled={graphDependencyMutation.isPending || !graphDependencyDraftHasChanges || Boolean(graphDependencyDraftValidation)}
                    >
                      <Save size={14} />
                      Save graph edit
                    </button>
                    <button
                      type="button"
                      className="metadata-cancel"
                      onClick={cancelGraphDependencyEdit}
                      disabled={graphDependencyMutation.isPending}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    className="icon-button"
                    onClick={cancelGraphDependencyEdit}
                    aria-label="Dismiss graph dependency message"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>
            ) : null}
            {dagNodes.length === 0 ? (
              <div className="graph-empty" role="status" aria-live="polite">
                <strong>No workflow graph to display</strong>
                <p>The DAG file loaded, but there are no nodes to render.</p>
              </div>
            ) : (
              <ReactFlow
                nodes={flowNodes}
                edges={flowEdges}
                fitView
                nodeTypes={FLOW_NODE_TYPES}
                connectionLineType={ConnectionLineType.SmoothStep}
                defaultEdgeOptions={{ type: 'smoothstep' }}
                onNodeClick={(_, node) => attemptSelectNode(node.id)}
                onNodeDragStart={(_, node) => startDraggedNodePreview(node as Node<DagFlowNodeData>)}
                onNodeDrag={(_, node) => updateDraggedNodePreview(node as Node<DagFlowNodeData>)}
                onNodeDragStop={(_, node) => stopDraggedNodePreview(node as Node<DagFlowNodeData>)}
                onConnect={stageGraphDependencyConnection}
                onEdgesDelete={stageGraphDependencyRemoval}
                onEdgeDoubleClick={(_, edge) => stageGraphDependencyRemoval([edge])}
                deleteKeyCode={['Backspace', 'Delete']}
              >
                <Background gap={18} />
                <Controls showInteractive={false} />
                {dragPreview ? (
                  <ViewportPortal>
                    <div
                      className="graph-drag-placeholder"
                      style={{
                        transform: `translate(${dragPreview.initialPosition.x}px, ${dragPreview.initialPosition.y}px)`,
                      }}
                    >
                      <FlowNodeCard data={dragPreview.data} className="drag-origin-card" />
                    </div>
                    <div
                      className="graph-drag-preview"
                      style={{
                        transform: `translate(${dragPreview.currentPosition.x}px, ${dragPreview.currentPosition.y}px)`,
                      }}
                    >
                      <FlowNodeCard data={dragPreview.data} className="drag-preview-card" />
                    </div>
                  </ViewportPortal>
                ) : null}
                <Panel position="bottom-right">
                  <button
                    type="button"
                    className="graph-reset-button"
                    onClick={resetGraphLayout}
                    disabled={!hasManualLayout}
                  >
                    <RefreshCcw size={14} />
                    Reset layout
                  </button>
                </Panel>
              </ReactFlow>
            )}
          </div>
        </section>
        <Inspector
          node={selectedNode}
          dagNodes={dagNodes}
          readyNodes={readyNodes}
          createNodeMode={isCreatingNode}
          dagHasNodes={dagNodes.length > 0}
          onCancelCreate={() => setIsCreatingNode(false)}
          onCreateNode={(nodeId) => {
            setIsCreatingNode(false);
            setSelectedId(nodeId);
            setSelectedRunId(undefined);
          }}
          state={selectedNode ? state.data?.states[selectedNode.id] : undefined}
          runs={selectedRuns}
          runsLoading={runs.isLoading}
          paths={paths}
          selectedRun={selectedRun}
          selectedRunId={selectedRunId}
          onSelectRun={setSelectedRunId}
          onUnsavedChange={setInspectorHasUnsavedChanges}
        />
      </main>
      <RunTimeline runs={runs.data?.runs ?? []} isLoading={runs.isLoading} />
    </div>
  );
}

function Toolbar({ mode, setMode, refetch }: { mode: ThemeMode; setMode: (mode: ThemeMode) => void; refetch: () => void }) {
  return (
    <header className="toolbar">
      <div className="brand"><GitBranch size={18} /> BureauLess</div>
      <div className="toolbar-center">automation-inspection-optimization</div>
      <button className="icon-button" onClick={refetch} title="Refresh"><RefreshCcw size={16} /></button>
      <div className="theme-toggle" aria-label="Theme">
        {(['system', 'light', 'dark'] as const).map((item) => (
          <button key={item} className={mode === item ? 'active' : ''} onClick={() => setMode(item)}>
            {item === 'light' ? <Sun size={14} /> : item === 'dark' ? <Moon size={14} /> : <CheckCircle2 size={14} />}
            {item}
          </button>
        ))}
      </div>
    </header>
  );
}

function useDependencySave(paths: WorkbenchPaths) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ taskId, dependencies }: DependencySaveDraft) =>
      updateNodeDependencies({
        dag_path: paths.dagPath,
        task_id: taskId,
        dependencies,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['dag', paths.dagPath] }),
        queryClient.invalidateQueries({ queryKey: ['state', paths.dagPath, paths.runsDir] }),
        queryClient.invalidateQueries({ queryKey: ['validation', paths.dagPath] }),
      ]);
    },
  });
}

function FullPageError({ error, dagPath, onRetry }: { error: unknown; dagPath: string; onRetry: () => void }) {
  const message = error instanceof Error ? error.message : 'Unable to load the DAG.';
  const missingDag = isMissingDagFileError(message);
  const headline = missingDag ? 'DAG file not found' : 'Unable to load the DAG';
  const body = missingDag
    ? `The workbench could not open ${dagPath}. ${message}`
    : message;

  return (
    <div className="error-screen">
      <div className="error-card" role="alert" aria-live="assertive">
        <div className="brand"><Workflow size={18} /> BureauLess</div>
        <h1>{headline}</h1>
        <p>{body}</p>
        <div className="error-actions">
          <button type="button" className="review-retry" onClick={onRetry}>
            Retry
          </button>
        </div>
      </div>
    </div>
  );
}

function AssignmentMatrix({
  nodes,
  states,
  readyNodes,
  selectedNodeId,
  onSelectNode,
}: {
  nodes: TaskNode[];
  states?: Record<string, NodeState>;
  readyNodes: TaskNode[];
  selectedNodeId?: string;
  onSelectNode: (nodeId: string) => void;
}) {
  return (
    <section className="assignment-matrix" aria-labelledby="assignment-matrix-heading">
      <div className="assignment-matrix-header">
        <div className="pane-title" id="assignment-matrix-heading">
          <LayoutList size={16} />
          Assignment Matrix
          <span className="pane-count">{nodes.length}</span>
        </div>
        <div className={readyNodes.length > 1 ? 'parallel-ready-batch active' : 'parallel-ready-batch'}>
          <span>{readyNodes.length}</span>{' '}
          {readyNodes.length === 1 ? 'ready node' : 'ready nodes'}
          {readyNodes.length > 1 ? ' can run in parallel' : ''}
        </div>
      </div>
      {nodes.length === 0 ? (
        <div className="empty-state-card" role="status" aria-live="polite">
          <strong>No assignments</strong>
          <p>The DAG loaded successfully, but it does not contain any task nodes yet.</p>
        </div>
      ) : (
        <div className="assignment-table-wrap">
          <table className="assignment-table" aria-label="Assignment Matrix">
            <thead>
              <tr>
                <th scope="col">Node</th>
                <th scope="col">Recommended model</th>
                <th scope="col">Risk</th>
                <th scope="col">State</th>
                <th scope="col">Dependencies</th>
              </tr>
            </thead>
            <tbody>
              {nodes.map((node) => {
                const nodeState = states?.[node.id] ?? 'blocked';
                const isReady = nodeState === 'ready';
                const rowClasses = [
                  'assignment-row',
                  `risk-${node.risk_level}`,
                  isReady ? 'ready-row' : '',
                  node.id === selectedNodeId ? 'selected' : '',
                ]
                  .filter(Boolean)
                  .join(' ');

                return (
                  <tr key={node.id} className={rowClasses}>
                    <th scope="row">
                      <button
                        type="button"
                        className="assignment-node-button"
                        aria-label={`Open assignment ${node.id}`}
                        onClick={() => onSelectNode(node.id)}
                      >
                        <span>{node.title}</span>
                        <small>{node.id}</small>
                      </button>
                    </th>
                    <td>{node.recommended_model}</td>
                    <td>
                      <span className={`matrix-pill risk-${node.risk_level}`}>{node.risk_level}</span>
                    </td>
                    <td>
                      <span className={`matrix-pill state-pill ${nodeState}`}>
                        {isReady ? 'ready to run' : nodeState}
                      </span>
                    </td>
                    <td>{node.dependencies.length > 0 ? node.dependencies.join(', ') : 'none'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Inspector({
  node,
  dagNodes,
  readyNodes,
  createNodeMode,
  dagHasNodes,
  onCancelCreate,
  onCreateNode,
  state,
  runs,
  runsLoading,
  paths,
  selectedRun,
  selectedRunId,
  onSelectRun,
  onUnsavedChange,
}: {
  node?: TaskNode;
  dagNodes: TaskNode[];
  readyNodes: TaskNode[];
  createNodeMode: boolean;
  dagHasNodes: boolean;
  onCancelCreate: () => void;
  onCreateNode: (nodeId: string) => void;
  state?: NodeState;
  runs: RunRecord[];
  runsLoading: boolean;
  paths: WorkbenchPaths;
  selectedRun?: RunRecord;
  selectedRunId?: string;
  onSelectRun: (runId: string) => void;
  onUnsavedChange: (hasUnsavedChanges: boolean) => void;
}) {
  const readyPromptQueries = useQueries({
    queries: readyNodes.map((readyNode) => ({
      queryKey: ['prompt', paths.dagPath, readyNode.id],
      queryFn: () => fetchPrompt(readyNode.id, paths.dagPath),
      enabled: Boolean(readyNode.id),
    })),
  });
  const selectedReadyNodeIndex = readyNodes.findIndex((readyNode) => readyNode.id === node?.id);
  const prompt = useQuery({
    queryKey: ['prompt', paths.dagPath, node?.id],
    queryFn: () => fetchPrompt(node?.id ?? '', paths.dagPath),
    enabled: Boolean(node?.id) && selectedReadyNodeIndex === -1,
  });
  const selectedPromptQuery = selectedReadyNodeIndex >= 0 ? readyPromptQueries[selectedReadyNodeIndex]! : prompt;
  const queryClient = useQueryClient();
  const [lastReviewAction, setLastReviewAction] = useState<ReviewAction | null>(null);
  const [isEditingMetadata, setIsEditingMetadata] = useState(false);
  const [metadataDraft, setMetadataDraft] = useState<MetadataDraft | null>(null);
  const [isEditingDependencies, setIsEditingDependencies] = useState(false);
  const [dependencyDraft, setDependencyDraft] = useState<DependencyDraft>([]);
  const [creationDraft, setCreationDraft] = useState<NodeCreationDraft>(emptyNodeCreationDraft());
  const reviewMutation = useMutation({
    mutationFn: async (reviewAction: ReviewAction) => {
      if (!node || !selectedRun) {
        throw new Error('No run record available for review');
      }
      return updateReviewStatus({
        dag_path: paths.dagPath,
        runs_dir: paths.runsDir,
        task_id: node.id,
        run_id: selectedRun.run_id,
        review_status: reviewStatusForAction(node.review_gate, reviewAction),
      });
    },
    onMutate: (reviewAction) => {
      setLastReviewAction(reviewAction);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['runs'] }),
        queryClient.invalidateQueries({ queryKey: ['state'] }),
      ]);
    },
  });
  const metadataMutation = useMutation({
    mutationFn: async () => {
      if (!node || !metadataDraft) {
        throw new Error('No node metadata available to update');
      }

      return updateNodeMetadata({
        dag_path: paths.dagPath,
        task_id: node.id,
        updates: {
          recommended_model: metadataDraft.recommended_model.trim(),
          risk_level: metadataDraft.risk_level,
          review_gate: metadataDraft.review_gate,
          failure_policy: metadataDraft.failure_policy,
          tags: parseTagInput(metadataDraft.tags),
        },
      });
    },
    onSuccess: async () => {
      setIsEditingMetadata(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['dag', paths.dagPath] }),
        queryClient.invalidateQueries({ queryKey: ['state', paths.dagPath, paths.runsDir] }),
      ]);
    },
  });
  const dependencyMutation = useDependencySave(paths);
  const createNodeMutation = useMutation({
    mutationFn: async () =>
      createNode({
        dag_path: paths.dagPath,
        node: nodeCreationDraftToNode(creationDraft),
      }),
    onSuccess: async (response) => {
      setCreationDraft(emptyNodeCreationDraft());
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['dag', paths.dagPath] }),
        queryClient.invalidateQueries({ queryKey: ['state', paths.dagPath, paths.runsDir] }),
        queryClient.invalidateQueries({ queryKey: ['validation', paths.dagPath] }),
      ]);
      onCreateNode(response.node.id);
    },
  });
  const resetReviewMutation = reviewMutation.reset;
  const resetMetadataMutation = metadataMutation.reset;
  const resetDependencyMutation = dependencyMutation.reset;
  const resetCreateNodeMutation = createNodeMutation.reset;
  const hasUnsavedMetadataChanges = Boolean(
    node &&
      isEditingMetadata &&
      metadataDraft &&
      !metadataDraftMatchesNode(metadataDraft, node),
  );
  const hasUnsavedDependencyChanges = Boolean(
    node &&
      isEditingDependencies &&
      !dependencyDraftMatchesNode(dependencyDraft, node),
  );
  const hasUnsavedCreateNodeChanges =
    createNodeMode && !nodeCreationDraftIsEmpty(creationDraft);

  useEffect(() => {
    resetReviewMutation();
    setLastReviewAction(null);
  }, [resetReviewMutation, node?.id, selectedRun?.run_id]);

  useEffect(() => {
    if (!node) {
      setIsEditingMetadata(false);
      setMetadataDraft(null);
      resetMetadataMutation();
      setIsEditingDependencies(false);
      setDependencyDraft([]);
      resetDependencyMutation();
      return;
    }

    if (!isEditingMetadata) {
      setMetadataDraft(metadataDraftFromNode(node));
    }
    if (!isEditingDependencies) {
      setDependencyDraft(node.dependencies);
    }
  }, [isEditingDependencies, isEditingMetadata, node, resetDependencyMutation, resetMetadataMutation]);

  useEffect(() => {
    if (!createNodeMode) {
      setCreationDraft(emptyNodeCreationDraft());
      resetCreateNodeMutation();
    }
  }, [createNodeMode, resetCreateNodeMutation]);

  useEffect(() => {
    onUnsavedChange(hasUnsavedMetadataChanges || hasUnsavedDependencyChanges || hasUnsavedCreateNodeChanges);
    return () => onUnsavedChange(false);
  }, [hasUnsavedCreateNodeChanges, hasUnsavedDependencyChanges, hasUnsavedMetadataChanges, onUnsavedChange]);

  const handleReviewAction = (reviewAction: ReviewAction) => {
    resetReviewMutation();
    reviewMutation.mutate(reviewAction);
  };

  const handleRetryReview = () => {
    if (lastReviewAction) {
      resetReviewMutation();
      reviewMutation.mutate(lastReviewAction);
    }
  };

  const beginEditMetadata = () => {
    if (!node) {
      return;
    }
    setMetadataDraft(metadataDraftFromNode(node));
    setIsEditingMetadata(true);
    resetMetadataMutation();
  };

  const cancelEditMetadata = () => {
    if (node) {
      setMetadataDraft(metadataDraftFromNode(node));
    } else {
      setMetadataDraft(null);
    }
    setIsEditingMetadata(false);
    resetMetadataMutation();
  };

  const beginEditDependencies = () => {
    if (!node) {
      return;
    }
    setDependencyDraft(node.dependencies);
    setIsEditingDependencies(true);
    resetDependencyMutation();
  };

  const cancelEditDependencies = () => {
    setDependencyDraft(node?.dependencies ?? []);
    setIsEditingDependencies(false);
    resetDependencyMutation();
  };

  const toggleDependency = (dependencyId: string) => {
    setDependencyDraft((current) => toggleDependencyDraftItem(current, dependencyId));
    resetDependencyMutation();
  };

  const saveMetadata = () => {
    metadataMutation.mutate();
  };

  const saveDependencies = () => {
    if (!node) {
      return;
    }
    dependencyMutation.mutate(
      {
        taskId: node.id,
        dependencies: dependencyDraft,
      },
      {
        onSuccess: () => setIsEditingDependencies(false),
      },
    );
  };

  const saveNewNode = () => {
    createNodeMutation.mutate();
  };

  const dependencyCandidates = dagNodes.filter((candidate) => candidate.id !== node?.id);
  const dependencyCandidateIds = new Set(dependencyCandidates.map((candidate) => candidate.id));
  const invalidDependencies = dependencyDraft.filter(
    (dependencyId) => dependencyId === node?.id || !dependencyCandidateIds.has(dependencyId),
  );

  if (createNodeMode) {
    return (
      <aside className="inspector">
        <div className="inspector-header">
          <div className="pane-title">Create Node</div>
          <button type="button" className="metadata-toggle" onClick={onCancelCreate}>
            <X size={14} />
            Cancel
          </button>
        </div>
        <p className="inspector-intro">
          Add a complete task node and let the DAG validator reject anything underspecified.
        </p>
        <form
          className="metadata-form"
          onSubmit={(event) => {
            event.preventDefault();
            saveNewNode();
          }}
        >
          <div className="field-grid">
            <label className="field">
              <span>ID</span>
              <input value={creationDraft.id} onChange={(event) => setCreationDraft((current) => ({ ...current, id: event.target.value }))} />
            </label>
            <label className="field">
              <span>Title</span>
              <input value={creationDraft.title} onChange={(event) => setCreationDraft((current) => ({ ...current, title: event.target.value }))} />
            </label>
            <label className="field field-wide">
              <span>Goal</span>
              <textarea value={creationDraft.goal} onChange={(event) => setCreationDraft((current) => ({ ...current, goal: event.target.value }))} rows={3} />
            </label>
            <label className="field">
              <span>Allowed models</span>
              <textarea value={creationDraft.allowed_models} onChange={(event) => setCreationDraft((current) => ({ ...current, allowed_models: event.target.value }))} rows={3} placeholder="gpt-5.4-mini&#10;gpt-5.4" />
            </label>
            <label className="field">
              <span>Recommended model</span>
              <input value={creationDraft.recommended_model} onChange={(event) => setCreationDraft((current) => ({ ...current, recommended_model: event.target.value }))} />
            </label>
            <label className="field">
              <span>Risk level</span>
              <select value={creationDraft.risk_level} onChange={(event) => setCreationDraft((current) => ({ ...current, risk_level: event.target.value as TaskNode['risk_level'] }))}>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </label>
            <label className="field">
              <span>Review gate</span>
              <select value={creationDraft.review_gate} onChange={(event) => setCreationDraft((current) => ({ ...current, review_gate: event.target.value as TaskNode['review_gate'] }))}>
                <option value="auto_pass">auto_pass</option>
                <option value="orchestrator_review">orchestrator_review</option>
                <option value="human_review">human_review</option>
              </select>
            </label>
            <label className="field">
              <span>Failure policy</span>
              <select value={creationDraft.failure_policy} onChange={(event) => setCreationDraft((current) => ({ ...current, failure_policy: event.target.value }))}>
                {FAILURE_POLICIES.map((policy) => (
                  <option key={policy} value={policy}>
                    {policy}
                  </option>
                ))}
              </select>
            </label>
            <label className="field field-wide">
              <span>Dependencies</span>
              <textarea value={creationDraft.dependencies} onChange={(event) => setCreationDraft((current) => ({ ...current, dependencies: event.target.value }))} rows={3} placeholder="baseline-inventory" />
            </label>
            <label className="field field-wide">
              <span>Target files</span>
              <textarea value={creationDraft.target_files} onChange={(event) => setCreationDraft((current) => ({ ...current, target_files: event.target.value }))} rows={3} placeholder="src/runtime.py" />
            </label>
            <label className="field field-wide">
              <span>Context files</span>
              <textarea value={creationDraft.context_files} onChange={(event) => setCreationDraft((current) => ({ ...current, context_files: event.target.value }))} rows={3} placeholder="docs/design-notes.md" />
            </label>
            <label className="field field-wide">
              <span>Acceptance criteria</span>
              <textarea value={creationDraft.acceptance_criteria} onChange={(event) => setCreationDraft((current) => ({ ...current, acceptance_criteria: event.target.value }))} rows={3} placeholder="New node appears in the graph" />
            </label>
            <label className="field field-wide">
              <span>Verification commands</span>
              <textarea value={creationDraft.verification_commands} onChange={(event) => setCreationDraft((current) => ({ ...current, verification_commands: event.target.value }))} rows={3} placeholder="pytest -q" />
            </label>
            <label className="field field-wide">
              <span>Do not</span>
              <textarea value={creationDraft.do_not} onChange={(event) => setCreationDraft((current) => ({ ...current, do_not: event.target.value }))} rows={3} placeholder="Do not change unrelated files" />
            </label>
            <label className="field field-wide">
              <span>Prompt template</span>
              <textarea value={creationDraft.prompt_template} onChange={(event) => setCreationDraft((current) => ({ ...current, prompt_template: event.target.value }))} rows={5} placeholder="Implement ${title} with care." />
            </label>
            <label className="field">
              <span>Outputs</span>
              <textarea value={creationDraft.outputs} onChange={(event) => setCreationDraft((current) => ({ ...current, outputs: event.target.value }))} rows={3} placeholder="patch" />
            </label>
            <label className="field">
              <span>Tags</span>
              <textarea value={creationDraft.tags} onChange={(event) => setCreationDraft((current) => ({ ...current, tags: event.target.value }))} rows={3} placeholder="runtime&#10;high-risk" />
            </label>
          </div>
          <div className="metadata-actions">
            <button type="submit" className="metadata-save" disabled={createNodeMutation.isPending}>
              <Save size={14} />
              Create node
            </button>
            <button type="button" className="metadata-cancel" onClick={onCancelCreate} disabled={createNodeMutation.isPending}>
              Cancel
            </button>
          </div>
          {createNodeMutation.error instanceof Error ? (
            <div className="metadata-error" role="alert" aria-live="polite">
              <p>Node creation failed: {createNodeMutation.error.message}</p>
            </div>
          ) : null}
        </form>
      </aside>
    );
  }

  if (!node) {
    return (
      <aside className="inspector">
        <div className="pane-title">Node Inspector</div>
        <div className="empty-state-card inspector-empty" role="status" aria-live="polite">
          <strong>{dagHasNodes ? 'No node selected' : 'No selected node'}</strong>
          <p>
            {dagHasNodes
              ? 'Pick a node from the DAG or the ready-node list to inspect its details.'
              : 'The DAG currently has no nodes, so there is nothing to inspect.'}
          </p>
        </div>
      </aside>
    );
  }

  return (
    <aside className="inspector">
      <div className="inspector-header">
        <div className="pane-title">Node Inspector</div>
        <button type="button" className="metadata-toggle" onClick={isEditingMetadata ? cancelEditMetadata : beginEditMetadata}>
          {isEditingMetadata ? <X size={14} /> : <Pencil size={14} />}
          {isEditingMetadata ? 'Cancel edit' : 'Edit metadata'}
        </button>
      </div>
      <h2>{node.id}</h2>
      <div className="badge-row">
        <span className={`badge risk-${node.risk_level}`}>risk: {node.risk_level}</span>
        <span className="badge">{node.recommended_model}</span>
        <span className="badge">{node.review_gate}</span>
        <span className={`badge ${state ?? 'blocked'}`}>{state ?? 'blocked'}</span>
      </div>
      <section className="metadata-section">
        <div className="section-header">
          <h3>Metadata</h3>
          <span className="review-note">Editable fields only</span>
        </div>
        {isEditingMetadata && metadataDraft ? (
          <form
            className="metadata-form"
            onSubmit={(event) => {
              event.preventDefault();
              saveMetadata();
            }}
          >
            <div className="field-grid">
              <label className="field">
                <span>Recommended model</span>
                <select
                  value={metadataDraft.recommended_model}
                  onChange={(event) =>
                    setMetadataDraft((current) =>
                      current
                        ? { ...current, recommended_model: event.target.value }
                        : current,
                    )
                  }
                >
                  {[node.recommended_model, ...node.allowed_models].filter((model, index, list) => list.indexOf(model) === index).map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Risk level</span>
                <select
                  value={metadataDraft.risk_level}
                  onChange={(event) =>
                    setMetadataDraft((current) =>
                      current
                        ? { ...current, risk_level: event.target.value as TaskNode['risk_level'] }
                        : current,
                    )
                  }
                >
                  <option value="low">low</option>
                  <option value="medium">medium</option>
                  <option value="high">high</option>
                </select>
              </label>
              <label className="field">
                <span>Review gate</span>
                <select
                  value={metadataDraft.review_gate}
                  onChange={(event) =>
                    setMetadataDraft((current) =>
                      current
                        ? { ...current, review_gate: event.target.value as TaskNode['review_gate'] }
                        : current,
                    )
                  }
                >
                  <option value="auto_pass">auto_pass</option>
                  <option value="orchestrator_review">orchestrator_review</option>
                  <option value="human_review">human_review</option>
                </select>
              </label>
              <label className="field">
                <span>Failure policy</span>
                <select
                  value={metadataDraft.failure_policy}
                  onChange={(event) =>
                    setMetadataDraft((current) =>
                      current ? { ...current, failure_policy: event.target.value } : current,
                    )
                  }
                >
                  {FAILURE_POLICIES.map((policy) => (
                    <option key={policy} value={policy}>
                      {policy}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field field-wide">
                <span>Tags</span>
                <div className="input-with-icon">
                  <Tag size={14} />
                  <input
                    type="text"
                    value={metadataDraft.tags}
                    onChange={(event) =>
                      setMetadataDraft((current) =>
                        current ? { ...current, tags: event.target.value } : current,
                      )
                    }
                    placeholder="tag-a, tag-b"
                  />
                </div>
              </label>
            </div>
            <div className="metadata-actions">
              <button type="submit" className="metadata-save" disabled={metadataMutation.isPending}>
                <Save size={14} />
                Save
              </button>
              <button type="button" className="metadata-cancel" onClick={cancelEditMetadata} disabled={metadataMutation.isPending}>
                Cancel
              </button>
            </div>
            {metadataMutation.error instanceof Error ? (
              <div className="metadata-error" role="alert" aria-live="polite">
                <p>Metadata update failed: {metadataMutation.error.message}</p>
              </div>
            ) : null}
          </form>
        ) : (
          <div className="metadata-readout">
            <div>
              <span>Recommended model</span>
              <strong>{node.recommended_model}</strong>
            </div>
            <div>
              <span>Risk level</span>
              <strong>{node.risk_level}</strong>
            </div>
            <div>
              <span>Review gate</span>
              <strong>{node.review_gate}</strong>
            </div>
            <div>
              <span>Failure policy</span>
              <strong>{node.failure_policy}</strong>
            </div>
            <div className="metadata-tags">
              <span>Tags</span>
              {node.tags.length > 0 ? (
                <div className="badge-row">
                  {node.tags.map((tag) => (
                    <span key={tag} className="badge">
                      {tag}
                    </span>
                  ))}
                </div>
              ) : (
                <strong>None</strong>
              )}
            </div>
          </div>
        )}
      </section>
      <section className="metadata-section">
        <div className="section-header">
          <h3>Dependencies</h3>
          <button
            type="button"
            className="metadata-toggle"
            onClick={isEditingDependencies ? cancelEditDependencies : beginEditDependencies}
            disabled={dependencyMutation.isPending}
          >
            {isEditingDependencies ? <X size={14} /> : <Pencil size={14} />}
            {isEditingDependencies ? 'Cancel edit' : 'Edit dependencies'}
          </button>
        </div>
        {isEditingDependencies ? (
          <form
            className="metadata-form"
            onSubmit={(event) => {
              event.preventDefault();
              saveDependencies();
            }}
          >
            <p className="dependency-help">Select the upstream tasks this node must wait for before it can run.</p>
            {dependencyDraft.length > 0 ? (
              <div className="dependency-selection" aria-live="polite">
                {dependencyDraft.map((dependencyId) => (
                  invalidDependencies.includes(dependencyId) ? (
                    <button
                      key={dependencyId}
                      type="button"
                      className="dependency-chip selected removable"
                      onClick={() => toggleDependency(dependencyId)}
                    >
                      {dependencyId}
                      <X size={12} />
                    </button>
                  ) : (
                    <span key={dependencyId} className="dependency-chip selected">
                      {dependencyId}
                    </span>
                  )
                ))}
              </div>
            ) : (
              <p className="empty-state-message">No dependencies selected.</p>
            )}
            {invalidDependencies.length > 0 ? (
              <div className="metadata-error" role="status" aria-live="polite">
                <p>
                  Some selected dependencies are not available in this DAG anymore. Remove them from the selection before saving.
                </p>
              </div>
            ) : null}
            {dependencyCandidates.length === 0 ? (
              <div className="empty-state-card" role="status" aria-live="polite">
                <strong>No other nodes available</strong>
                <p>Add another node to create a dependency relationship.</p>
              </div>
            ) : (
              <div className="dependency-options" role="group" aria-label="Dependency selector">
                {dependencyCandidates.map((candidate) => {
                  const checked = dependencyDraft.includes(candidate.id);
                  return (
                    <label
                      key={candidate.id}
                      className={checked ? 'dependency-option selected' : 'dependency-option'}
                    >
                      <input
                        type="checkbox"
                        aria-label={`${candidate.title} (${candidate.id})`}
                        checked={checked}
                        onChange={() => toggleDependency(candidate.id)}
                      />
                      <span className="dependency-option-title">{candidate.title}</span>
                      <small>{candidate.id}</small>
                    </label>
                  );
                })}
              </div>
            )}
            <div className="metadata-actions">
              <button
                type="submit"
                className="metadata-save"
                disabled={dependencyMutation.isPending || invalidDependencies.length > 0}
              >
                <Save size={14} />
                Save dependencies
              </button>
              <button
                type="button"
                className="metadata-cancel"
                onClick={cancelEditDependencies}
                disabled={dependencyMutation.isPending}
              >
                Cancel
              </button>
            </div>
            {dependencyMutation.error instanceof Error ? (
              <div className="metadata-error" role="alert" aria-live="polite">
                <p>Dependency update failed: {formatDependencyUpdateError(dependencyMutation.error.message)}</p>
              </div>
            ) : null}
          </form>
        ) : (
          <div className="dependency-readout">
            {node.dependencies.length > 0 ? (
              <div className="dependency-selection">
                {node.dependencies.map((dependencyId) => (
                  <span key={dependencyId} className="dependency-chip">
                    {dependencyId}
                  </span>
                ))}
              </div>
            ) : (
              <div className="empty-state-card" role="status" aria-live="polite">
                <strong>No dependencies</strong>
                <p>This node can run as soon as its review gate and state allow it.</p>
              </div>
            )}
          </div>
        )}
      </section>
      <section>
        <h3>Goal</h3>
        <p>{node.goal}</p>
      </section>
      <DetailList title="Acceptance Criteria" items={node.acceptance_criteria} />
      <DetailList title="Target Files" items={node.target_files} />
      <DetailList title="Do Not" items={node.do_not} />
      <section>
        <h3>Runs</h3>
        {runsLoading ? (
          <p className="empty-state-message">Loading run records.</p>
        ) : runs.length === 0 ? (
          <div className="empty-state-card" role="status" aria-live="polite">
            <strong>No run records</strong>
            <p>There are no run records for this node yet.</p>
          </div>
        ) : (
          <div className="run-list">
            {runs.map((run) => (
              <button
                key={run.run_id}
                type="button"
                className={run.run_id === selectedRunId ? 'run-item selected' : 'run-item'}
                onClick={() => onSelectRun(run.run_id)}
              >
                <span>{run.run_id}</span>
                <small>{run.status}</small>
              </button>
            ))}
          </div>
        )}
      </section>
      {selectedRun ? (
        <section>
          <h3>Run Details</h3>
          <div className="run-details">
            <div>
              <span>Run ID</span>
              <strong>{selectedRun.run_id}</strong>
            </div>
            <div>
              <span>Status</span>
              <strong>{selectedRun.status}</strong>
            </div>
            <div>
              <span>Review</span>
              <strong>{selectedRun.review_status}</strong>
            </div>
            <div>
              <span>Finished</span>
              <strong>{selectedRun.finished_at}</strong>
            </div>
            <div>
              <span>Model</span>
              <strong>{selectedRun.model}</strong>
            </div>
            {selectedRun.output_commit ? (
              <div>
                <span>Commit</span>
                <strong>{selectedRun.output_commit}</strong>
              </div>
            ) : null}
            {selectedRun.verification_result ? (
              <div>
                <span>Verification</span>
                <strong>{selectedRun.verification_result}</strong>
              </div>
            ) : null}
            {selectedRun.changed_files.length > 0 ? (
              <div className="run-files">
                <span>Changed Files</span>
                <ul>
                  {selectedRun.changed_files.map((file) => (
                    <li key={file}>{file}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}
      {selectedRun ? (
        <section className="review-actions">
          <div className="review-actions-header">
            <h3>Review Actions</h3>
            <span className="review-note">Selected run: {selectedRun.run_id}</span>
          </div>
          <div className="review-actions-buttons">
            <button
              type="button"
              className="review-button approve"
              onClick={() => handleReviewAction('approve')}
              disabled={reviewMutation.isPending}
            >
              <CheckCircle2 size={14} />
              Approve
            </button>
            <button
              type="button"
              className="review-button reject"
              onClick={() => handleReviewAction('reject')}
              disabled={reviewMutation.isPending}
            >
              <XCircle size={14} />
              Reject
            </button>
            <button
              type="button"
              className="review-button pending"
              onClick={() => handleReviewAction('pending')}
              disabled={reviewMutation.isPending}
            >
              <CircleDashed size={14} />
              Mark Pending
            </button>
          </div>
          {reviewMutation.error instanceof Error ? (
            <div className="review-error" role="alert" aria-live="polite">
              <p>Review update failed: {reviewMutation.error.message}</p>
              <button
                type="button"
                className="review-retry"
                onClick={handleRetryReview}
                disabled={reviewMutation.isPending || !lastReviewAction}
              >
                Retry
              </button>
            </div>
          ) : null}
        </section>
      ) : null}
      <section className="prompt-export-panel">
        <div className="section-header">
          <h3>Prompt Export Panel</h3>
          <span className="review-note">Read-only prompt previews and copy actions</span>
        </div>
        <div className="prompt-export-stack">
          <article className="prompt-export-card">
            <div className="prompt-export-card-header">
              <div className="prompt-export-card-title">
                <span className="prompt-export-label">Selected node</span>
                <strong>{node.title}</strong>
                <small>{node.id}</small>
              </div>
              {selectedPromptQuery.data?.prompt ? (
                <button
                  type="button"
                  className="metadata-toggle"
                  onClick={() => void copyTextToClipboard(selectedPromptQuery.data.prompt)}
                >
                  <Copy size={14} />
                  Copy selected prompt
                </button>
              ) : null}
            </div>
            {selectedPromptQuery.isLoading ? (
              <p className="empty-state-message">Loading prompt preview.</p>
            ) : selectedPromptQuery.isError ? (
              <div className="prompt-export-placeholder" role="status" aria-live="polite">
                <strong>Prompt unavailable</strong>
                <p>We could not load the prompt preview for this node.</p>
              </div>
            ) : selectedPromptQuery.data?.prompt ? (
              <pre>{selectedPromptQuery.data.prompt}</pre>
            ) : (
              <div className="prompt-export-placeholder" role="status" aria-live="polite">
                <strong>No prompt preview</strong>
                <p>This node does not expose a prompt preview yet.</p>
              </div>
            )}
          </article>
          <div className="prompt-export-batch">
            <div className="prompt-export-batch-header">
              <span>Ready-node batch preview</span>
              <span className="pane-count">{readyNodes.length}</span>
            </div>
            {readyNodes.length === 0 ? (
              <div className="prompt-export-placeholder" role="status" aria-live="polite">
                <strong>No ready prompts</strong>
                <p>There are no ready nodes to export right now.</p>
              </div>
            ) : (
              <div className="prompt-export-list">
                {readyNodes.map((readyNode, index) => {
                  const readyPrompt = readyPromptQueries[index];
                  if (!readyPrompt) {
                    return null;
                  }
                  return (
                    <article key={readyNode.id} className="prompt-export-card">
                      <div className="prompt-export-card-header">
                        <div className="prompt-export-card-title">
                          <span className="prompt-export-label">Ready node</span>
                          <strong>{readyNode.title}</strong>
                          <small>{readyNode.id}</small>
                        </div>
                        {readyPrompt.data?.prompt ? (
                          <button
                            type="button"
                            className="metadata-toggle"
                            onClick={() => void copyTextToClipboard(readyPrompt.data.prompt)}
                          >
                            <Copy size={14} />
                            Copy prompt
                          </button>
                        ) : null}
                      </div>
                      {readyPrompt.isLoading ? (
                        <p className="empty-state-message">Loading ready-node prompt.</p>
                      ) : readyPrompt.isError ? (
                        <div className="prompt-export-placeholder" role="status" aria-live="polite">
                          <strong>Prompt unavailable</strong>
                          <p>We could not load this ready node's prompt preview.</p>
                        </div>
                      ) : readyPrompt.data?.prompt ? (
                        <pre>{readyPrompt.data.prompt}</pre>
                      ) : (
                        <div className="prompt-export-placeholder" role="status" aria-live="polite">
                          <strong>No prompt preview</strong>
                          <p>This ready node does not expose a prompt preview yet.</p>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </section>
    </aside>
  );
}

async function copyTextToClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', 'true');
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand('copy');
  document.body.removeChild(textarea);
}

function metadataDraftFromNode(node: TaskNode): MetadataDraft {
  return {
    recommended_model: node.recommended_model,
    risk_level: node.risk_level,
    review_gate: node.review_gate,
    failure_policy: node.failure_policy,
    tags: node.tags.join(', '),
  };
}

function emptyNodeCreationDraft(): NodeCreationDraft {
  return {
    id: '',
    title: '',
    goal: '',
    dependencies: '',
    target_files: '',
    context_files: '',
    allowed_models: '',
    recommended_model: '',
    risk_level: 'low',
    review_gate: 'auto_pass',
    acceptance_criteria: '',
    verification_commands: '',
    do_not: '',
    prompt_template: '',
    failure_policy: 'retry_same_model',
    outputs: '',
    tags: '',
  };
}

function nodeCreationDraftToNode(draft: NodeCreationDraft): TaskNode {
  return {
    id: draft.id.trim(),
    title: draft.title.trim(),
    goal: draft.goal.trim(),
    dependencies: parseMultiValueInput(draft.dependencies),
    target_files: parseMultiValueInput(draft.target_files),
    context_files: parseMultiValueInput(draft.context_files),
    allowed_models: parseMultiValueInput(draft.allowed_models),
    recommended_model: draft.recommended_model.trim(),
    risk_level: draft.risk_level,
    review_gate: draft.review_gate,
    acceptance_criteria: parseMultiValueInput(draft.acceptance_criteria),
    verification_commands: parseMultiValueInput(draft.verification_commands),
    do_not: parseMultiValueInput(draft.do_not),
    prompt_template: draft.prompt_template.trim(),
    failure_policy: draft.failure_policy,
    outputs: parseMultiValueInput(draft.outputs),
    tags: parseMultiValueInput(draft.tags),
  };
}

function nodeCreationDraftIsEmpty(draft: NodeCreationDraft): boolean {
  const empty = emptyNodeCreationDraft();
  return Object.entries(draft).every(([key, value]) => value === empty[key as keyof NodeCreationDraft]);
}

function parseMultiValueInput(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function parseTagInput(value: string): string[] {
  return parseMultiValueInput(value);
}

function metadataDraftMatchesNode(draft: MetadataDraft, node: TaskNode): boolean {
  const normalizedTags = parseTagInput(draft.tags);
  return (
    draft.recommended_model.trim() === node.recommended_model &&
    draft.risk_level === node.risk_level &&
    draft.review_gate === node.review_gate &&
    draft.failure_policy === node.failure_policy &&
    normalizedTags.length === node.tags.length &&
    normalizedTags.every((tag, index) => tag === node.tags[index])
  );
}

function dependencyDraftMatchesNode(draft: DependencyDraft, node: TaskNode): boolean {
  return dependencyDraftMatchesList(draft, node.dependencies);
}

function dependencyDraftMatchesList(draft: DependencyDraft, dependencies: string[]): boolean {
  return draft.length === dependencies.length && draft.every((dependency, index) => dependency === dependencies[index]);
}

function computeFlowNodePositions(
  nodes: TaskNode[],
  dependencyView: Array<{ id: string; dependencies: string[] }>,
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const nodeIds = new Set(nodes.map((node) => node.id));
  const order = new Map(nodes.map((node, index) => [node.id, index]));
  const dependenciesById = new Map(
    dependencyView.map((entry) => [
      entry.id,
      entry.dependencies.filter((dependencyId) => dependencyId !== entry.id && nodeIds.has(dependencyId)),
    ]),
  );
  const outgoing = new Map<string, string[]>();
  const indegree = new Map<string, number>();
  const levels = new Map<string, number>();

  for (const node of nodes) {
    outgoing.set(node.id, []);
    indegree.set(node.id, 0);
    levels.set(node.id, 0);
  }

  for (const node of nodes) {
    const dependencies = dependenciesById.get(node.id) ?? [];
    indegree.set(node.id, dependencies.length);
    for (const dependencyId of dependencies) {
      outgoing.get(dependencyId)?.push(node.id);
    }
  }

  const queue = nodes
    .filter((node) => (indegree.get(node.id) ?? 0) === 0)
    .map((node) => node.id);

  while (queue.length > 0) {
    queue.sort((left, right) => (order.get(left) ?? 0) - (order.get(right) ?? 0));
    const currentId = queue.shift()!;
    const currentLevel = levels.get(currentId) ?? 0;
    for (const nextId of outgoing.get(currentId) ?? []) {
      levels.set(nextId, Math.max(levels.get(nextId) ?? 0, currentLevel + 1));
      indegree.set(nextId, (indegree.get(nextId) ?? 0) - 1);
      if ((indegree.get(nextId) ?? 0) === 0) {
        queue.push(nextId);
      }
    }
  }

  for (const node of nodes) {
    if ((indegree.get(node.id) ?? 0) > 0) {
      const fallbackLevel = Math.max(
        0,
        ...((dependenciesById.get(node.id) ?? []).map((dependencyId) => (levels.get(dependencyId) ?? 0) + 1)),
      );
      levels.set(node.id, fallbackLevel);
    }
  }

  const nodesByLevel = new Map<number, TaskNode[]>();
  for (const node of nodes) {
    const level = levels.get(node.id) ?? 0;
    const bucket = nodesByLevel.get(level) ?? [];
    bucket.push(node);
    nodesByLevel.set(level, bucket);
  }

  for (const [level, bucket] of nodesByLevel.entries()) {
    bucket
      .sort((left, right) => (order.get(left.id) ?? 0) - (order.get(right.id) ?? 0))
      .forEach((node, row) => {
        positions.set(node.id, {
          x: 80 + level * 320,
          y: 120 + row * 170,
        });
      });
  }

  return positions;
}

function toggleDependencyDraftItem(draft: DependencyDraft, dependencyId: string): DependencyDraft {
  if (draft.includes(dependencyId)) {
    return draft.filter((item) => item !== dependencyId);
  }
  return [...draft, dependencyId];
}

function dependencyEdgeId(sourceId: string, targetId: string): string {
  return `${sourceId}->${targetId}`;
}

function validateGraphDependencyConnection(
  nodes: TaskNode[],
  draft: GraphDependencyDraft | null,
  sourceId: string,
  targetId: string,
): string | null {
  if (draft && draft.targetId !== targetId) {
    return `Save or cancel the pending edit for ${draft.targetId} before editing ${targetId}.`;
  }
  if (sourceId === targetId) {
    return 'A node cannot depend on itself.';
  }
  const sourceNode = nodes.find((node) => node.id === sourceId);
  const targetNode = nodes.find((node) => node.id === targetId);
  if (!sourceNode || !targetNode) {
    return 'Both ends of a dependency must be existing DAG nodes.';
  }

  const currentDependencies = draft?.targetId === targetId ? draft.dependencies : targetNode.dependencies;
  if (currentDependencies.includes(sourceId)) {
    return `${targetId} already depends on ${sourceId}.`;
  }

  return validateDependencyDraft(nodes, targetId, [...currentDependencies, sourceId]);
}

function validateDependencyDraft(nodes: TaskNode[], targetId: string, dependencies: DependencyDraft): string | null {
  const nodeIds = new Set(nodes.map((node) => node.id));
  if (!nodeIds.has(targetId)) {
    return `${targetId} is not in this DAG.`;
  }

  const duplicateDependency = dependencies.find((dependencyId, index) => dependencies.indexOf(dependencyId) !== index);
  if (duplicateDependency) {
    return `${targetId} already includes ${duplicateDependency}.`;
  }

  const invalidDependency = dependencies.find((dependencyId) => dependencyId === targetId || !nodeIds.has(dependencyId));
  if (invalidDependency === targetId) {
    return 'A node cannot depend on itself.';
  }
  if (invalidDependency) {
    return `${invalidDependency} is not in this DAG.`;
  }

  const cycleNode = findDependencyCycleNode(nodes, targetId, dependencies);
  return cycleNode ? `Saving this graph edit would create a cycle at ${cycleNode}.` : null;
}

function findDependencyCycleNode(nodes: TaskNode[], targetId: string, dependencies: DependencyDraft): string | null {
  const dependencyMap = new Map(nodes.map((node) => [node.id, node.dependencies] as const));
  dependencyMap.set(targetId, dependencies);
  const visiting = new Set<string>();
  const visited = new Set<string>();

  const visit = (nodeId: string): string | null => {
    if (visiting.has(nodeId)) {
      return nodeId;
    }
    if (visited.has(nodeId)) {
      return null;
    }

    visiting.add(nodeId);
    for (const dependencyId of dependencyMap.get(nodeId) ?? []) {
      if (!dependencyMap.has(dependencyId)) {
        continue;
      }
      const cycleNode = visit(dependencyId);
      if (cycleNode) {
        return cycleNode;
      }
    }
    visiting.delete(nodeId);
    visited.add(nodeId);
    return null;
  };

  for (const node of nodes) {
    const cycleNode = visit(node.id);
    if (cycleNode) {
      return cycleNode;
    }
  }
  return null;
}

function loadWorkbenchPaths(): WorkbenchPaths {
  if (typeof window === 'undefined') {
    return {
      dagPath: DEFAULT_DAG_PATH,
      runsDir: DEFAULT_RUNS_DIR,
    };
  }

  return normalizeWorkbenchPaths({
    dagPath: window.localStorage.getItem('bureauless.dagPath') ?? DEFAULT_DAG_PATH,
    runsDir: window.localStorage.getItem('bureauless.runsDir') ?? DEFAULT_RUNS_DIR,
  });
}

function persistWorkbenchPaths(paths: WorkbenchPaths): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem('bureauless.dagPath', paths.dagPath);
  window.localStorage.setItem('bureauless.runsDir', paths.runsDir);
}

function loadGraphNodePositions(dagPath: string): FlowNodePositions {
  if (typeof window === 'undefined') {
    return {};
  }

  const raw = window.localStorage.getItem(graphNodePositionsStorageKey(dagPath));
  if (!raw) {
    return {};
  }

  try {
    const parsed = JSON.parse(raw) as Record<string, { x?: unknown; y?: unknown }>;
    return Object.fromEntries(
      Object.entries(parsed).flatMap(([nodeId, position]) =>
        typeof position?.x === 'number' && typeof position?.y === 'number'
          ? [[nodeId, { x: position.x, y: position.y }]]
          : [],
      ),
    );
  } catch {
    return {};
  }
}

function persistGraphNodePositions(dagPath: string, positions: FlowNodePositions): void {
  if (typeof window === 'undefined') {
    return;
  }

  if (Object.keys(positions).length === 0) {
    window.localStorage.removeItem(graphNodePositionsStorageKey(dagPath));
    return;
  }

  window.localStorage.setItem(graphNodePositionsStorageKey(dagPath), JSON.stringify(positions));
}

function graphNodePositionsStorageKey(dagPath: string): string {
  return `bureauless.graphNodePositions:${dagPath}`;
}

function normalizeWorkbenchPaths(paths: WorkbenchPaths): WorkbenchPaths {
  return {
    dagPath: paths.dagPath.trim() || DEFAULT_DAG_PATH,
    runsDir: paths.runsDir.trim() || DEFAULT_RUNS_DIR,
  };
}

function getDesktopBridge() {
  if (typeof window === 'undefined') {
    return null;
  }
  const bridge = window.agentsSwarm;
  if (!bridge?.openDag || !bridge?.openRunsDir) {
    return null;
  }
  return bridge;
}

function reviewStatusForAction(reviewGate: TaskNode['review_gate'], action: ReviewAction): string {
  if (action === 'reject') {
    return 'rejected';
  }
  if (action === 'pending') {
    return 'pending';
  }
  if (reviewGate === 'orchestrator_review') {
    return 'orchestrator_approved';
  }
  if (reviewGate === 'human_review') {
    return 'human_approved';
  }
  return 'approved';
}

function diagnosticHeadline(error: ValidationError): string {
  if (error.code === 'invalid_yaml') {
    if (error.line && error.column) {
      return `YAML syntax issue at line ${error.line}, column ${error.column}`;
    }
    if (error.line) {
      return `YAML syntax issue at line ${error.line}`;
    }
    return 'YAML syntax issue';
  }

  if (error.code === 'missing_required_fields') {
    return error.fields?.length ? `Missing field${error.fields.length > 1 ? 's' : ''}: ${error.fields.join(', ')}` : 'Missing required fields';
  }

  if (error.code === 'unknown_dependency') {
    return error.node_id && error.dependency
      ? `${error.node_id} depends on missing ${error.dependency}`
      : 'Unknown dependency';
  }

  if (error.code === 'duplicate_node') {
    return error.node_id ? `Duplicate node id: ${error.node_id}` : 'Duplicate node id';
  }

  if (error.code === 'cycle_detected') {
    return error.node_id ? `Cycle detected at ${error.node_id}` : 'Cycle detected';
  }

  return error.node_id ? `${error.node_id}: ${error.message}` : error.message;
}

function formatDependencyUpdateError(message: string): string {
  const unknownDependencyMatch = message.match(/^(?<nodeId>[^:]+): unknown dependency (?<dependency>.+)$/);
  if (unknownDependencyMatch?.groups) {
    const dependency = unknownDependencyMatch.groups.dependency.replace(/^'+|'+$/g, '');
    return `${unknownDependencyMatch.groups.nodeId} depends on missing ${dependency}. Pick an existing node or remove it from the selection.`;
  }

  const cycleMatch = message.match(/^Cycle detected at node (?<nodeId>.+)$/);
  if (cycleMatch?.groups?.nodeId) {
    return `Saving this selection would create a cycle at ${cycleMatch.groups.nodeId}.`;
  }

  return message;
}

function DetailList({ title, items }: { title: string; items: string[] }) {
  return (
    <section>
      <h3>{title}</h3>
      <ul>
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </section>
  );
}

function RunTimeline({ runs, isLoading }: { runs: Array<Record<string, unknown>>; isLoading: boolean }) {
  return (
    <footer className="timeline">
      <div className="pane-title">Runs</div>
      {isLoading ? (
        <span className="empty-state-message">Loading run timeline.</span>
      ) : runs.length === 0 ? (
        <div className="empty-state-card timeline-empty" role="status" aria-live="polite">
          <strong>No run records</strong>
          <p>The runs directory is empty, which is fine for a fresh workbench.</p>
        </div>
      ) : (
        runs.map((run) => (
          <div className="run-row" key={String(run.run_id)}>
            <span>{String(run.task_id)}</span>
            <span>{String(run.model)}</span>
            <span>{String(run.status)}</span>
            <span>{String(run.review_status)}</span>
          </div>
        ))
      )}
    </footer>
  );
}

function isMissingDagFileError(message: string): boolean {
  return /no such file|not found|does not exist|enoent/i.test(message);
}

createRoot(document.getElementById('root')!).render(<App />);
