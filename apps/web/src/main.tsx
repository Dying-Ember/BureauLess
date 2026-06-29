import '@xyflow/react/dist/style.css';
import './styles.css';

import { QueryClient, QueryClientProvider, useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Background,
  ConnectionLineType,
  Controls,
  Handle,
  Panel,
  MarkerType,
  Position,
  ReactFlow,
  useReactFlow,
  ViewportPortal,
  type Connection,
  type Edge,
  type EdgeProps,
  type EdgeMouseHandler,
  type Node,
  type NodeProps,
  type XYPosition,
} from '@xyflow/react';
import {
  AlertCircle,
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
import { StrictMode, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { createRoot } from 'react-dom/client';
import ELK from './elk-layout.js';

import {
  createNode,
  decideMutation,
  DEFAULT_DAG_PATH,
  DEFAULT_MISSION_PATH,
  DEFAULT_LEDGER_PATH,
  DEFAULT_RUNS_DIR,
  DEFAULT_WORKFLOW_PATH,
  fetchDag,
  fetchLedger,
  fetchGatekeeper,
  fetchMission,
  fetchMutations,
  fetchReplay,
  fetchPrompt,
  fetchRuns,
  fetchState,
  fetchValidation,
  type GatekeeperBlockedReason,
  type GatekeeperDecision,
  type WorkbenchPaths,
  updateNodeDependencies,
  updateNodeMetadata,
  updateReviewStatus,
  type NodeState,
  type MutationProposalInspection,
  type MutationWorkbenchPaths,
  type MissionResponse,
  type LedgerResponse,
  type RuntimeWorkflow,
  type RuntimeWorkflowNode,
  type RuntimeWorkflowWaitsFor,
  type ReplayAssignmentAttempt,
  type ReplayNodeState,
  type ReplayResponse,
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

type FlowNodePort = {
  id: string;
  y: number;
};

type DagFlowNodeData = {
  title: string;
  recommendedModel: string;
  reviewGate: string;
  nodeState: string;
  riskLevel: TaskNode['risk_level'];
};

type RuntimeFlowNodeData = {
  role: string;
  gatekeeperState: string;
  gatekeeperStateLabel: string;
  gatekeeperTone: 'runnable' | 'blocked' | 'completed' | 'needs_review' | 'superseded' | 'unknown';
  stateSummary: string;
  primaryReason: string | null;
  blockedReasons: GatekeeperBlockedReason[];
  emits: string[];
  waitsForAll: string[];
  waitsForAny: string[];
  isTerminal: boolean;
  gateCount: number;
  incomingPorts: FlowNodePort[];
  outgoingPorts: FlowNodePort[];
};

type OrthogonalFlowEdgeData = {
  sections: XYPosition[][];
  eventRef?: string;
  onSelectEdge?: (edge: { source: string; target: string; eventRef: string }) => void;
  sourceIndex?: number;
  sourceCount?: number;
  targetIndex?: number;
  targetCount?: number;
};

type RuntimeFlowEdgeData = OrthogonalFlowEdgeData & {
  eventRef: string;
};

type RuntimeFlowLayout = {
  nodes: Array<Node<RuntimeFlowNodeData>>;
  edges: Array<Edge<RuntimeFlowEdgeData>>;
  orderedNodes: Array<Node<RuntimeFlowNodeData>>;
};

type PlanningFlowLayout = {
  nodes: Array<Node<DagFlowNodeData>>;
  edges: Array<Edge<OrthogonalFlowEdgeData>>;
  orderedNodes: Array<Node<DagFlowNodeData>>;
};

type DirectedFlowEdgeDescriptor = {
  id: string;
  sourceId: string;
  targetId: string;
  sourceIndex: number;
  sourceCount: number;
  targetIndex: number;
  targetCount: number;
};

type DirectedElkLayoutNode = {
  id: string;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  ports?: Array<{
    id: string;
    x?: number;
    y?: number;
  }>;
};

type DirectedElkLayoutEdge = {
  id: string;
  sections?: Array<{
    startPoint: XYPosition;
    endPoint: XYPosition;
    bendPoints?: XYPosition[];
  }>;
};

type DirectedElkLayout = {
  children?: DirectedElkLayoutNode[];
  edges?: DirectedElkLayoutEdge[];
};

type DirectedNodeLayoutSpacing = {
  originX: number;
  originY: number;
  columnGap: number;
  rowGap: number;
};

type DirectedNodeLayoutOptions = {
  levelStagger?: number;
};

const PLANNING_LAYOUT_SPACING: DirectedNodeLayoutSpacing = {
  originX: 80,
  originY: 120,
  columnGap: 320,
  rowGap: 170,
};

const PLANNING_NODE_WIDTH = 220;
const PLANNING_NODE_HEIGHT = 88;

const RUNTIME_LAYOUT_SPACING: DirectedNodeLayoutSpacing = {
  originX: 72,
  originY: 112,
  columnGap: 400,
  rowGap: 220,
};

const RUNTIME_NODE_WIDTH = 228;
const RUNTIME_NODE_HEIGHT = 120;

const RUNTIME_ELK_LAYOUT_OPTIONS = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.edgeRouting': 'ORTHOGONAL',
  'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
  'elk.layered.considerModelOrder.longEdgeStrategy': 'DUMMY_NODE_OVER',
  'elk.layered.spacing.nodeNodeBetweenLayers': '60',
  'elk.layered.spacing.edgeNodeBetweenLayers': '25',
  'elk.layered.spacing.edgeEdgeBetweenLayers': '18',
};

const runtimeElk = new ELK({
  defaultLayoutOptions: RUNTIME_ELK_LAYOUT_OPTIONS,
});

const planningElk = runtimeElk;

const DAG_ORTHOGONAL_EDGE_TYPE = 'dag-orthogonal';
const RUNTIME_ORTHOGONAL_EDGE_TYPE = 'runtime-orthogonal';

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

type WorkbenchViewMode = 'planning' | 'runtime';

const FAILURE_POLICIES = ['retry_same_model', 'escalate_to_large_model', 'send_to_human', 'split_task_further'] as const;
const WORKBENCH_VIEW_STORAGE_KEY = 'bureauless.workbenchViewMode';

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

function PlanningGraphViewportSync({ fitKey }: { fitKey: number }) {
  const { fitView } = useReactFlow();

  useEffect(() => {
    let cancelled = false;
    const frame = window.requestAnimationFrame(() => {
      if (!cancelled) {
        void fitView({ padding: 0.2, duration: 150 });
      }
    });
    return () => {
      cancelled = true;
      window.cancelAnimationFrame(frame);
    };
  }, [fitKey, fitView]);

  return null;
}

function DagFlowNode({ id, data }: NodeProps<Node<DagFlowNodeData>>) {
  return (
    <div className="flow-node-shell dag-node-shell">
      <Handle
        id={`${id}:in`}
        type="target"
        position={Position.Left}
        className="flow-handle target"
        style={{ top: '50%' }}
      />
      <FlowNodeCard data={data} className="dag-flow-node" />
      <Handle
        id={`${id}:out`}
        type="source"
        position={Position.Right}
        className="flow-handle source"
        style={{ top: '50%' }}
      />
    </div>
  );
}

function RuntimeFlowNode({ id, data }: NodeProps<Node<RuntimeFlowNodeData>>) {
  const incomingPorts = data.incomingPorts.length > 0 ? data.incomingPorts : [{ id: `${id}:in`, y: RUNTIME_NODE_HEIGHT / 2 }];
  const outgoingPorts = data.outgoingPorts.length > 0 ? data.outgoingPorts : [{ id: `${id}:out`, y: RUNTIME_NODE_HEIGHT / 2 }];

  return (
    <div className="flow-node-shell runtime-node-shell">
      {incomingPorts.map((port) => (
        <Handle
          key={port.id}
          id={port.id}
          type="target"
          position={Position.Left}
          className="flow-handle target"
          style={{ top: clampRuntimePortOffset(port.y) }}
        />
      ))}
      <div className={`flow-node runtime-flow-node state-${data.gatekeeperTone}`}>
        <div className="runtime-flow-node-header">
          <strong>{id}</strong>
          <span>{data.role}</span>
        </div>
        <div className="runtime-flow-node-state-row">
          <span className={`state-pill runtime-state-pill ${data.gatekeeperTone}`}>{data.gatekeeperStateLabel}</span>
          {data.gateCount > 0 ? <small>{data.gateCount} gate{data.gateCount === 1 ? '' : 's'}</small> : null}
        </div>
        <small>{data.stateSummary}</small>
        {data.primaryReason ? <small className="runtime-flow-node-reason">{data.primaryReason}</small> : null}
      </div>
      {outgoingPorts.map((port) => (
        <Handle
          key={port.id}
          id={port.id}
          type="source"
          position={Position.Right}
          className="flow-handle source"
          style={{ top: clampRuntimePortOffset(port.y) }}
        />
      ))}
    </div>
  );
}

function OrthogonalFlowEdge({
  id,
  markerEnd,
  style,
  source,
  target,
  data,
  sourceX,
  sourceY,
  sourcePosition,
  targetX,
  targetY,
    targetPosition,
  interactionWidth,
}: EdgeProps<Edge<OrthogonalFlowEdgeData>>) {
  const path = runtimeEdgePath(data?.sections ?? [], {
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    sourceIndex: data?.sourceIndex,
    sourceCount: data?.sourceCount,
    targetIndex: data?.targetIndex,
    targetCount: data?.targetCount,
  });
  const handleSelect = () => {
    data?.onSelectEdge?.({ source, target, eventRef: data?.eventRef ?? 'unavailable' });
  };

  return (
    <g className="runtime-orthogonal-edge">
      <path
        id={id}
        className="react-flow__edge-path"
        d={path}
        markerEnd={markerEnd}
        style={style}
        fill="none"
        pointerEvents="none"
      />
      <path
        d={path}
        fill="none"
        stroke="transparent"
        strokeWidth={interactionWidth ?? 20}
        pointerEvents="stroke"
        onClick={handleSelect}
        onPointerDown={handleSelect}
      />
    </g>
  );
}

const ORTHOGONAL_EDGE_TYPES = {
  [DAG_ORTHOGONAL_EDGE_TYPE]: OrthogonalFlowEdge,
  [RUNTIME_ORTHOGONAL_EDGE_TYPE]: OrthogonalFlowEdge,
};

const FLOW_NODE_TYPES = {
  dag: DagFlowNode,
  runtime: RuntimeFlowNode,
};

function Workbench() {
  const [paths, setPaths] = useState<WorkbenchPaths>(loadWorkbenchPaths);
  const [mutationPaths, setMutationPaths] = useState<MutationWorkbenchPaths>(loadMutationWorkbenchPaths);
  const [mutationPathDraft, setMutationPathDraft] = useState<MutationWorkbenchPaths>(loadMutationWorkbenchPaths);
  const [viewMode, setViewMode] = useState<WorkbenchViewMode>(() => loadWorkbenchViewMode());
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
  const [selectedRuntimeNodeId, setSelectedRuntimeNodeId] = useState<string | undefined>();
  const [selectedRuntimeEdge, setSelectedRuntimeEdge] = useState<{ source: string; target: string; eventRef: string } | null>(null);
  const [elkPlanningFlow, setElkPlanningFlow] = useState<PlanningFlowLayout | null>(null);
  const [planningGraphLayoutRevision, setPlanningGraphLayoutRevision] = useState(0);
  const [elkRuntimeFlow, setElkRuntimeFlow] = useState<RuntimeFlowLayout | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | undefined>();
  const [isCreatingNode, setIsCreatingNode] = useState(false);
  const [inspectorHasUnsavedChanges, setInspectorHasUnsavedChanges] = useState(false);
  const [graphDependencyDraft, setGraphDependencyDraft] = useState<GraphDependencyDraft | null>(null);
  const [graphDependencyMessage, setGraphDependencyMessage] = useState<string | null>(null);
  const [dragPreview, setDragPreview] = useState<DragPreviewState | null>(null);
  const { mode, setMode } = useThemeMode();
  const desktopBridge = getDesktopBridge();
  const graphDependencyMutation = useDependencySave(paths);
  const mutations = useQuery({
    queryKey: ['mutations', mutationPaths.workflowPath, mutationPaths.ledgerPath],
    queryFn: () => fetchMutations(mutationPaths.workflowPath, mutationPaths.ledgerPath),
  });
  const runtimeMissionPath = useMemo(
    () => normalizeMutationWorkbenchPaths(mutationPaths).missionPath,
    [mutationPaths],
  );
  const mission = useQuery({
    queryKey: ['mission', runtimeMissionPath],
    queryFn: () => fetchMission(runtimeMissionPath),
    enabled: viewMode === 'runtime',
  });
  const ledger = useQuery({
    queryKey: ['ledger', mutationPaths.ledgerPath],
    queryFn: () => fetchLedger(mutationPaths.ledgerPath),
    enabled: viewMode === 'runtime',
  });
  const replay = useQuery({
    queryKey: ['replay', mutationPaths.workflowPath, mutationPaths.ledgerPath],
    queryFn: () => fetchReplay(mutationPaths.workflowPath, mutationPaths.ledgerPath),
  });
  const gatekeeper = useQuery({
    queryKey: ['gatekeeper', mutationPaths.workflowPath, mutationPaths.ledgerPath],
    queryFn: () => fetchGatekeeper(mutationPaths.workflowPath, mutationPaths.ledgerPath),
  });
  const mutationDecision = useMutation({
    mutationFn: decideMutation,
    onSuccess: async (response) => {
      queryClient.setQueryData(
        ['mutations', mutationPaths.workflowPath, mutationPaths.ledgerPath],
        response,
      );
      await queryClient.invalidateQueries({
        queryKey: ['gatekeeper', mutationPaths.workflowPath, mutationPaths.ledgerPath],
      });
    },
  });
  const runtimeDecisionSyncing =
    mutationDecision.isPending ||
    (mutationDecision.isSuccess &&
      (mutations.isFetching || gatekeeper.isFetching));

  useEffect(() => {
    setPathDraft(paths);
  }, [paths]);

  useEffect(() => {
    setManualNodePositions(loadGraphNodePositions(paths.dagPath));
  }, [paths.dagPath]);

  useEffect(() => {
    persistWorkbenchViewMode(viewMode);
  }, [viewMode]);

  useEffect(() => {
    persistMutationWorkbenchPaths(mutationPaths);
  }, [mutationPaths]);

  useEffect(() => {
    setMutationPathDraft(mutationPaths);
  }, [mutationPaths]);

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
  const dagEdges = dag.data?.edges ?? [];
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
  const visibleDagEdges = useMemo(
    () =>
      graphDependencyDraft
        ? [
            ...dagEdges.filter((edge) => edge.target !== graphDependencyDraft.targetId),
            ...graphDependencyDraft.dependencies.map((dependencyId) => ({
              id: dependencyEdgeId(dependencyId, graphDependencyDraft.targetId),
              source: dependencyId,
              target: graphDependencyDraft.targetId,
            })),
        ]
        : dagEdges,
    [dagEdges, graphDependencyDraft],
  );
  const draftDagEdgeIds = useMemo(
    () => new Set(graphDependencyDraft?.dependencies.map((dependencyId) => dependencyEdgeId(dependencyId, graphDependencyDraft.targetId)) ?? []),
    [graphDependencyDraft],
  );
  const manualPlanningFlow = useMemo<PlanningFlowLayout | null>(() => {
    if (dagNodes.length === 0) {
      return null;
    }
    return buildPlanningFlowLayoutFallback(dagNodes, visibleDagEdges);
  }, [dagNodes, visibleDagEdges]);
  const planningFlow = elkPlanningFlow ?? manualPlanningFlow;

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

  useEffect(() => {
    let cancelled = false;

    if (dagNodes.length === 0) {
      setElkPlanningFlow(null);
      return;
    }

    setElkPlanningFlow(null);
    void buildPlanningFlowLayout(dagNodes, visibleDagEdges).then(
      (layout) => {
        if (!cancelled) {
          setElkPlanningFlow(layout);
        }
      },
      (error) => {
        console.warn('Planning ELK layout failed, falling back to manual routing.', error);
      },
    );

    return () => {
      cancelled = true;
    };
  }, [dagNodes, visibleDagEdges]);

  useEffect(() => {
    if (elkPlanningFlow) {
      setPlanningGraphLayoutRevision((current) => current + 1);
    }
  }, [elkPlanningFlow]);

  const flowNodes = useMemo<Node<DagFlowNodeData>[]>(() => {
    const planningNodesById = new Map((planningFlow?.nodes ?? []).map((node) => [node.id, node] as const));

    return dagNodes.map((node) => {
      const planningNode = planningNodesById.get(node.id);
      const nodeState = state.data?.states[node.id] ?? 'blocked';
      return {
        id: node.id,
        selected: node.id === selectedId,
        position:
          manualNodePositions[node.id] ??
          planningNode?.position ??
          { x: PLANNING_LAYOUT_SPACING.originX, y: PLANNING_LAYOUT_SPACING.originY },
        style: planningNode?.style ?? {
          width: PLANNING_NODE_WIDTH,
          height: PLANNING_NODE_HEIGHT,
        },
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
  }, [dagNodes, manualNodePositions, planningFlow, selectedId, state.data]);

  const flowEdges = useMemo<Edge<OrthogonalFlowEdgeData>[]>(() => {
    return (planningFlow?.edges ?? []).map((edge) => ({
      ...edge,
      className: draftDagEdgeIds.has(edge.id) ? 'flow-edge draft' : 'flow-edge',
    }));
  }, [draftDagEdgeIds, planningFlow]);

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
    setPlanningGraphLayoutRevision((current) => current + 1);
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

  const applyMutationPathDraft = () => {
    const nextPaths = normalizeMutationWorkbenchPaths(mutationPathDraft);
    setMutationPaths(nextPaths);
    persistMutationWorkbenchPaths(nextPaths);
  };

  const mutationPathDraftChanged = useMemo(
    () => {
      const committed = normalizeMutationWorkbenchPaths(mutationPaths);
      const draft = normalizeMutationWorkbenchPaths(mutationPathDraft);
      return (
        draft.missionPath !== committed.missionPath ||
        draft.workflowPath !== committed.workflowPath ||
        draft.ledgerPath !== committed.ledgerPath
      );
    },
    [mutationPathDraft, mutationPaths],
  );

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
  const runtimeWorkflow = mutations.data?.current_workflow ?? null;
  const runtimeCurrentNodeIds = runtimeWorkflow?.nodes.map((node) => node.id) ?? [];
  const manualRuntimeFlow = useMemo<RuntimeFlowLayout | null>(() => {
    if (!runtimeWorkflow) {
      return null;
    }
    return buildRuntimeFlowLayoutFallback(
      runtimeWorkflow,
      gatekeeper.data?.decisions ?? {},
      selectedRuntimeNodeId,
      (edge) => setSelectedRuntimeEdge(edge),
    );
  }, [gatekeeper.data?.decisions, runtimeWorkflow, selectedRuntimeNodeId]);
  const runtimeFlow = elkRuntimeFlow ?? manualRuntimeFlow;
  const planningViewActive = viewMode === 'planning';
  const firstRuntimeNodeId = runtimeFlow?.orderedNodes[0]?.id ?? runtimeCurrentNodeIds[0];

  useEffect(() => {
    let cancelled = false;

    if (!runtimeWorkflow) {
      setElkRuntimeFlow(null);
      setSelectedRuntimeEdge(null);
      return;
    }

    setElkRuntimeFlow(null);
    void buildRuntimeFlowLayout(
      runtimeWorkflow,
      gatekeeper.data?.decisions ?? {},
      selectedRuntimeNodeId,
      (edge) => setSelectedRuntimeEdge(edge),
    ).then(
      (layout) => {
        if (!cancelled) {
          setElkRuntimeFlow(layout);
        }
      },
    );

    return () => {
      cancelled = true;
    };
  }, [gatekeeper.data?.decisions, runtimeWorkflow, selectedRuntimeNodeId]);

  useEffect(() => {
    if (runtimeCurrentNodeIds.length === 0) {
      if (selectedRuntimeNodeId !== undefined) {
        setSelectedRuntimeNodeId(undefined);
      }
      return;
    }

    if (!selectedRuntimeNodeId || !runtimeCurrentNodeIds.includes(selectedRuntimeNodeId)) {
      setSelectedRuntimeNodeId(firstRuntimeNodeId);
    }
  }, [firstRuntimeNodeId, runtimeCurrentNodeIds, selectedRuntimeNodeId]);

  if (dag.isError) {
    return <FullPageError error={dag.error} dagPath={paths.dagPath} onRetry={() => void dag.refetch()} />;
  }

  return (
    <div className="app-shell">
      <Toolbar
        mode={mode}
        setMode={setMode}
        viewMode={viewMode}
        setViewMode={setViewMode}
        refetch={() =>
          void Promise.all([
            dag.refetch(),
            validation.refetch(),
            state.refetch(),
            runs.refetch(),
            mutations.refetch(),
            replay.refetch(),
            gatekeeper.refetch(),
          ])
        }
      />
      <main className={planningViewActive ? 'workspace planning-view' : 'workspace runtime-view'}>
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
          {planningViewActive ? (
            <>
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
                  <Workflow size={16} /> Planning DAG
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
                        <small>{state.data?.states[node.id] ?? 'blocked'}</small>
                      </button>
                    ))}
                  </nav>
                )}
              </section>
            </>
          ) : (
            <section className="runtime-source-panel" aria-labelledby="runtime-sources-heading">
              <div className="pane-title" id="runtime-sources-heading">
                <GitBranch size={16} />
                Runtime sources
              </div>
              <div className="metadata-form runtime-source-form">
                <label className="field">
                  <span>Mission path</span>
                  <input
                    type="text"
                    value={mutationPathDraft.missionPath}
                    onChange={(event) =>
                      setMutationPathDraft((current) => ({ ...current, missionPath: event.target.value }))
                    }
                  />
                </label>
                <label className="field">
                  <span>Workflow path</span>
                  <input
                    type="text"
                    value={mutationPathDraft.workflowPath}
                    onChange={(event) =>
                      setMutationPathDraft((current) => ({ ...current, workflowPath: event.target.value }))
                    }
                  />
                </label>
                <label className="field">
                  <span>Ledger path</span>
                  <input
                    type="text"
                    value={mutationPathDraft.ledgerPath}
                    onChange={(event) =>
                      setMutationPathDraft((current) => ({ ...current, ledgerPath: event.target.value }))
                    }
                  />
                </label>
                <div className="metadata-actions">
                  <button
                    type="button"
                    className="metadata-save"
                    onClick={applyMutationPathDraft}
                    disabled={!mutationPathDraftChanged}
                  >
                    Apply runtime sources
                  </button>
                </div>
              </div>
              <p className="runtime-source-note">
                Runtime mode reads the workflow, mission, and ledger directly. Switch back to Planning DAG to edit graph structure.
              </p>
            </section>
          )}
        </aside>
        {planningViewActive ? (
          <>
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
                    edgeTypes={ORTHOGONAL_EDGE_TYPES}
                    connectionLineType={ConnectionLineType.SmoothStep}
                    defaultEdgeOptions={{ type: DAG_ORTHOGONAL_EDGE_TYPE }}
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
                    <PlanningGraphViewportSync fitKey={planningGraphLayoutRevision} />
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
          </>
        ) : (
          <>
            <RuntimeWorkflowOverview
              workflowId={mutations.data?.workflow_id ?? 'unavailable'}
              workflowPath={mutationPaths.workflowPath}
              ledgerPath={mutationPaths.ledgerPath}
              missionPath={runtimeMissionPath}
              workflow={runtimeWorkflow}
              missionQuery={mission}
              ledgerQuery={ledger}
              runtimeFlow={runtimeFlow}
              replay={replay.data ?? null}
              gatekeeperReadyCount={gatekeeper.data?.ready.length ?? 0}
              gatekeeperError={gatekeeper.error instanceof Error ? gatekeeper.error.message : null}
              proposals={mutations.data?.proposals ?? []}
              replayLoading={replay.isLoading}
              replayError={replay.error instanceof Error ? replay.error.message : null}
              isLoading={mutations.isLoading || gatekeeper.isLoading}
              isSyncing={runtimeDecisionSyncing}
              selectedNodeId={selectedRuntimeNodeId}
              selectedEdge={selectedRuntimeEdge}
              onSelectNode={(nodeId) => setSelectedRuntimeNodeId(nodeId)}
              onSelectEdge={setSelectedRuntimeEdge}
            />
            <MutationPanel
              proposals={mutations.data?.proposals ?? []}
              currentNodeIds={runtimeCurrentNodeIds}
              ledgerPath={mutationPaths.ledgerPath}
              isLoading={mutations.isLoading}
              error={mutations.error instanceof Error ? mutations.error.message : null}
              decisionError={
                mutationDecision.error instanceof Error
                  ? mutationDecision.error.message
                  : null
              }
              isDeciding={mutationDecision.isPending}
              selectedNodeId={selectedRuntimeNodeId}
              onSelectNode={(nodeId) => setSelectedRuntimeNodeId(nodeId)}
              onDecision={(proposalEventId, decision, reason) =>
                mutationDecision.mutate({
                  workflow_path: mutationPaths.workflowPath,
                  ledger_path: mutationPaths.ledgerPath,
                  proposal_event_id: proposalEventId,
                  decision,
                  actor: 'human',
                  reason,
                })
              }
            />
          </>
        )}
      </main>
      <RunTimeline runs={runs.data?.runs ?? []} isLoading={runs.isLoading} />
    </div>
  );
}

function Toolbar({
  mode,
  setMode,
  viewMode,
  setViewMode,
  refetch,
}: {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
  viewMode: WorkbenchViewMode;
  setViewMode: (mode: WorkbenchViewMode) => void;
  refetch: () => void;
}) {
  return (
    <header className="toolbar">
      <div className="brand"><GitBranch size={18} /> BureauLess</div>
      <div className="toolbar-center">automation-inspection-optimization</div>
      <div className="view-toggle" aria-label="Workbench view">
        <button
          type="button"
          aria-pressed={viewMode === 'planning'}
          aria-selected={viewMode === 'planning'}
          className={viewMode === 'planning' ? 'active' : ''}
          onClick={() => setViewMode('planning')}
        >
          <Workflow size={14} />
          Planning DAG
        </button>
        <button
          type="button"
          aria-pressed={viewMode === 'runtime'}
          aria-selected={viewMode === 'runtime'}
          className={viewMode === 'runtime' ? 'active' : ''}
          onClick={() => setViewMode('runtime')}
        >
          <GitBranch size={14} />
          Runtime workflow
        </button>
      </div>
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

function RuntimeWorkflowOverview({
  workflowId,
  workflowPath,
  ledgerPath,
  missionPath,
  workflow,
  missionQuery,
  ledgerQuery,
  runtimeFlow,
  replay,
  gatekeeperReadyCount,
  gatekeeperError,
  proposals,
  replayLoading,
  replayError,
  isLoading,
  isSyncing,
  selectedNodeId,
  selectedEdge,
  onSelectNode,
  onSelectEdge,
}: {
  workflowId: string;
  workflowPath: string;
  ledgerPath: string;
  missionPath: string;
  workflow: RuntimeWorkflow | null;
  missionQuery: {
    data?: MissionResponse;
    isLoading: boolean;
    isError: boolean;
    error: unknown;
  };
  ledgerQuery: {
    data?: LedgerResponse;
    isLoading: boolean;
    isError: boolean;
    error: unknown;
  };
  runtimeFlow: RuntimeFlowLayout | null;
  replay: ReplayResponse | null;
  gatekeeperReadyCount: number;
  gatekeeperError: string | null;
  proposals: MutationProposalInspection[];
  replayLoading: boolean;
  replayError: string | null;
  isLoading: boolean;
  isSyncing: boolean;
  selectedNodeId?: string;
  selectedEdge: { source: string; target: string; eventRef: string } | null;
  onSelectNode: (nodeId: string) => void;
  onSelectEdge: (edge: { source: string; target: string; eventRef: string } | null) => void;
}) {
  const pendingCount = proposals.filter((proposal) => proposal.state === 'pending').length;
  const currentNodeIds = workflow?.nodes.map((node) => node.id) ?? [];
  const eventCount = workflow ? Object.keys(workflow.events).length : 0;
  const gateCount = workflow?.gates.length ?? 0;
  const terminalCount = workflow?.terminal_events.length ?? 0;
  const selectedNode = runtimeFlow?.nodes.find((node) => node.id === selectedNodeId);
  const replayNode = selectedNodeId && replay?.nodes ? replay.nodes[selectedNodeId] ?? null : null;
  const replayProposalLinks = useMemo(
    () =>
      replay
        ? Object.values(replay.mutation_proposals).filter((proposal) =>
            proposal.affected_node_ids.includes(selectedNodeId ?? ''),
          )
        : [],
    [replay, selectedNodeId],
  );
  const blockedCount = runtimeFlow?.nodes.filter((node) => node.data.gatekeeperTone === 'blocked').length ?? 0;
  const needsReviewCount = runtimeFlow?.nodes.filter((node) => node.data.gatekeeperTone === 'needs_review').length ?? 0;
  const completedCount = runtimeFlow?.nodes.filter((node) => node.data.gatekeeperTone === 'completed').length ?? 0;
  const supersededCount = runtimeFlow?.nodes.filter((node) => node.data.gatekeeperTone === 'superseded').length ?? 0;
  const artifactCount = ledgerQuery.data?.artifacts.length ?? 0;
  const riskCount = ledgerQuery.data?.risks.length ?? 0;
  const decisionCount = ledgerQuery.data?.decisions.length ?? 0;
  const missionGoal = missionQuery.data?.goal ?? ledgerQuery.data?.current_goal ?? 'unavailable';
  const missionStatus = missionQuery.data?.status ?? 'unavailable';

  const handleRuntimeGraphPointerDownCapture = (event: ReactPointerEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement | null;
    const edgeElement = target?.closest('[role="img"][aria-roledescription="edge"]');
    if (!edgeElement || !runtimeFlow) {
      return;
    }
    const edgeId = edgeElement.getAttribute('data-id');
    if (!edgeId) {
      return;
    }
    const selectedRuntimeGraphEdge = runtimeFlow.edges.find((edge) => edge.id === edgeId);
    if (!selectedRuntimeGraphEdge) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    onSelectEdge({
      source: selectedRuntimeGraphEdge.source,
      target: selectedRuntimeGraphEdge.target,
      eventRef: selectedRuntimeGraphEdge.data?.eventRef ?? 'unavailable',
    });
  };

  return (
    <section className="runtime-pane" aria-labelledby="runtime-workflow-summary-heading">
      <div className="runtime-pane-header">
        <div className="pane-title" id="runtime-workflow-summary-heading">
          <GitBranch size={16} />
          Runtime workflow summary
          <span className="pane-count">{pendingCount}</span>
        </div>
        <div className="runtime-source-inline">
          <code title={workflowPath}>{workflowPath}</code>
          <code title={ledgerPath}>{ledgerPath}</code>
        </div>
      </div>
      {isSyncing ? (
        <p className="runtime-sync-note" role="status" aria-live="polite">
          Applying decision and refreshing runtime state.
        </p>
      ) : null}
      <div className="runtime-summary-grid">
        <div className="runtime-summary-card">
          <span>Workflow id</span>
          <strong>{workflowId}</strong>
        </div>
        <div className="runtime-summary-card">
          <span>Current nodes</span>
          <strong>{currentNodeIds.length}</strong>
          <small>{currentNodeIds.join(', ') || 'unavailable'}</small>
        </div>
        <div className="runtime-summary-card">
          <span>Runtime shape</span>
          <strong>{eventCount} events / {gateCount} gates</strong>
          <small>{terminalCount} terminal event{terminalCount === 1 ? '' : 's'}</small>
        </div>
        <div className="runtime-summary-card">
          <span>Gatekeeper</span>
          <strong>{gatekeeperReadyCount} runnable</strong>
          <small>
            {blockedCount} blocked, {needsReviewCount} needs review, {completedCount} completed
            {supersededCount > 0 ? `, ${supersededCount} superseded` : ''}
          </small>
        </div>
      </div>
      <div className="runtime-summary-split">
        <section className="runtime-mini-panel" aria-labelledby="runtime-mission-summary-heading" aria-busy={missionQuery.isLoading}>
          <div className="runtime-mini-panel-header">
            <div className="pane-title" id="runtime-mission-summary-heading">
              <GitBranch size={16} />
              Mission summary
            </div>
            <code title={missionPath}>{missionPath}</code>
          </div>
          {missionQuery.isError ? (
            <p className="runtime-mini-panel-note" role="alert">
              {missionQuery.error instanceof Error ? missionQuery.error.message : 'Mission load failed'}
            </p>
          ) : (
            <div className="runtime-mini-panel-body">
              <dl className="runtime-mini-facts">
                <div>
                  <dt>Mission id</dt>
                  <dd>{missionQuery.data?.mission_id ?? workflow?.mission_id ?? 'unavailable'}</dd>
                </div>
                <div>
                  <dt>Goal</dt>
                  <dd>{missionGoal}</dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>{missionStatus}</dd>
                </div>
              </dl>
              {missionQuery.isLoading ? <p className="runtime-mini-panel-note">Loading mission.</p> : null}
            </div>
          )}
        </section>
        <section className="runtime-mini-panel" aria-labelledby="runtime-ledger-summary-heading" aria-busy={ledgerQuery.isLoading}>
          <div className="runtime-mini-panel-header">
            <div className="pane-title" id="runtime-ledger-summary-heading">
              <GitBranch size={16} />
              Ledger summary
            </div>
            <code title={ledgerPath}>{ledgerPath}</code>
          </div>
          {ledgerQuery.isError ? (
            <p className="runtime-mini-panel-note" role="alert">
              {ledgerQuery.error instanceof Error ? ledgerQuery.error.message : 'Ledger load failed'}
            </p>
          ) : (
            <div className="runtime-mini-panel-body">
              <dl className="runtime-mini-facts runtime-mini-facts-wide">
                <div>
                  <dt>Artifacts</dt>
                  <dd>{artifactCount}</dd>
                </div>
                <div>
                  <dt>Risks</dt>
                  <dd>{riskCount}</dd>
                </div>
                <div>
                  <dt>Decisions</dt>
                  <dd>{decisionCount}</dd>
                </div>
                <div>
                  <dt>Current goal</dt>
                  <dd>{ledgerQuery.data?.current_goal ?? missionGoal}</dd>
                </div>
              </dl>
              {ledgerQuery.isLoading ? <p className="runtime-mini-panel-note">Loading ledger.</p> : null}
            </div>
          )}
        </section>
      </div>
      {gatekeeperError ? <p className="mutation-error" role="alert">{gatekeeperError}</p> : null}
      <section className="runtime-graph-panel" aria-label="Runtime workflow canvas">
        <div className="runtime-graph-header">
          <div className="pane-title">
            <GitBranch size={16} />
            Runtime graph
          </div>
          <div className="runtime-graph-legend">
            <span>{pendingCount} pending proposal{pendingCount === 1 ? '' : 's'}</span>
            <span>{proposals.length > 0 ? 'Accepted decisions redraw this canvas.' : 'No workflow mutations recorded.'}</span>
          </div>
        </div>
        <div className="runtime-graph-canvas" onPointerDownCapture={handleRuntimeGraphPointerDownCapture}>
          {!runtimeFlow || runtimeFlow.nodes.length === 0 ? (
            <div className="empty-state-card" role="status" aria-live="polite">
              <strong>No runtime nodes</strong>
              <p>The ledger has not exposed any current workflow nodes yet.</p>
            </div>
          ) : (
            <ReactFlow
              nodes={runtimeFlow.nodes}
              edges={runtimeFlow.edges}
              fitView
              nodeTypes={FLOW_NODE_TYPES}
              edgeTypes={ORTHOGONAL_EDGE_TYPES}
              connectionLineType={ConnectionLineType.SmoothStep}
              defaultEdgeOptions={{ type: 'smoothstep' }}
              nodesDraggable={false}
              nodesConnectable={false}
              elementsSelectable={true}
              onNodeClick={(_, node) => onSelectNode(node.id)}
              onEdgeClick={(_, edge) =>
                onSelectEdge({
                  source: edge.source,
                  target: edge.target,
                  eventRef: edge.data?.eventRef ?? 'unavailable',
                })
              }
              proOptions={{ hideAttribution: true }}
            >
              <Background gap={18} />
              <Controls showInteractive={false} />
            </ReactFlow>
          )}
        </div>
        {selectedEdge ? (
          <div className="runtime-edge-inspector" aria-label="Selected runtime edge">
            <div className="runtime-edge-inspector-header">
              <div className="runtime-edge-inspector-title">
                <strong>{selectedEdge.source} &rarr; {selectedEdge.target}</strong>
                <code>{selectedEdge.eventRef}</code>
              </div>
              <button type="button" className="icon-button" onClick={() => onSelectEdge(null)} aria-label="Clear edge selection">
                <X size={14} />
              </button>
            </div>
          </div>
        ) : null}
      </section>
      <section className="runtime-replay-panel" aria-labelledby="runtime-replay-heading" aria-busy={replayLoading}>
        <div className="runtime-graph-header">
          <div className="pane-title" id="runtime-replay-heading">
            <GitBranch size={16} />
            Replay inspector
            <span className="pane-count">{replay?.terminal_complete ? 'complete' : 'open'}</span>
          </div>
          <span className="review-note">Read-only replay evidence from the API</span>
        </div>
        <div className="runtime-replay-body">
          {replayLoading ? (
            <p className="diagnostics-text">Loading replay evidence.</p>
          ) : replayError ? (
            <p className="mutation-error" role="alert">{replayError}</p>
          ) : !replay ? (
            <div className="empty-state-card" role="status" aria-live="polite">
              <strong>No replay data</strong>
              <p>The replay API did not return evidence for this workflow.</p>
            </div>
          ) : !replayNode ? (
            <div className="empty-state-card" role="status" aria-live="polite">
              <strong>No replay node selected</strong>
              <p>Select a runtime node to inspect emitted events, attempts, and links.</p>
            </div>
          ) : (
            <>
              <div className="runtime-replay-summary">
                <div className="runtime-summary-card">
                  <span>Workflow id</span>
                  <strong>{replay.workflow_id}</strong>
                </div>
                <div className="runtime-summary-card">
                  <span>Selected node</span>
                  <strong>{replayNode.node_id}</strong>
                  <small>{replayNode.state}</small>
                </div>
                <div className="runtime-summary-card">
                  <span>Terminal replay</span>
                  <strong>{replay.terminal_complete ? 'complete' : 'incomplete'}</strong>
                </div>
              </div>
              <div className="runtime-replay-section">
                <div className="runtime-replay-section-header">
                  <strong>Emitted events</strong>
                  <span className="pane-count">{replayNode.emitted_events.length}</span>
                </div>
                <div className="runtime-link-list">
                  {replayNode.emitted_events.length > 0 ? (
                    replayNode.emitted_events.map((eventId) => (
                      <code key={eventId} className="runtime-link-chip">{eventId}</code>
                    ))
                  ) : (
                    <span className="runtime-link-empty">none</span>
                  )}
                </div>
              </div>
              <div className="runtime-replay-section">
                <div className="runtime-replay-section-header">
                  <strong>Assignment attempts</strong>
                  <span className="pane-count">{replayNode.assignment_attempts.length}</span>
                </div>
                <div className="runtime-replay-list">
                  {replayNode.assignment_attempts.length > 0 ? (
                    replayNode.assignment_attempts.map((attempt) => (
                      <article className="runtime-replay-card" key={`${replayNode.node_id}:${attempt.assignment_id}`}>
                        <div className="runtime-replay-card-head">
                          <strong>{attempt.assignment_id}</strong>
                          <span className={`state-pill runtime-state-pill ${attempt.state === 'superseded' ? 'superseded' : attempt.state === 'completed' ? 'completed' : 'blocked'}`}>
                            {attempt.state}
                          </span>
                        </div>
                        <dl className="runtime-link-facts">
                          <div>
                            <dt>Created</dt>
                            <dd>{attempt.created_event_id ?? 'none'}</dd>
                          </div>
                          <div>
                            <dt>Terminal</dt>
                            <dd>{attempt.terminal_event_type ?? attempt.terminal_event_id ?? 'none'}</dd>
                          </div>
                          <div>
                            <dt>Retry of</dt>
                            <dd>{attempt.retry_of ?? 'none'}</dd>
                          </div>
                          <div>
                            <dt>Superseded by</dt>
                            <dd>{attempt.superseded_by ?? 'none'}</dd>
                          </div>
                        </dl>
                      </article>
                    ))
                  ) : (
                    <span className="runtime-link-empty">none</span>
                  )}
                </div>
              </div>
              <div className="runtime-replay-section">
                <div className="runtime-replay-section-header">
                  <strong>Blocked reasons</strong>
                  <span className="pane-count">{replayNode.blocked_reasons.length}</span>
                </div>
                <div className="runtime-replay-list">
                  {replayNode.blocked_reasons.length > 0 ? (
                    replayNode.blocked_reasons.map((reason, index) => (
                      <article className="runtime-replay-card" key={`${replayNode.node_id}:${reason.code}:${index}`}>
                        <div className="runtime-replay-card-head">
                          <span className={`state-pill runtime-state-pill ${runtimeReasonTone(reason.code)}`}>
                            {formatReasonCode(reason.code)}
                          </span>
                          <p>{reason.message}</p>
                        </div>
                        <div className="runtime-reason-meta">
                          {reason.missing_ref ? <span>Missing ref: <code>{reason.missing_ref}</code></span> : null}
                          {reason.assignment_id ? <span>Assignment: <code>{reason.assignment_id}</code></span> : null}
                          {reason.gate_id ? <span>Gate: <code>{reason.gate_id}</code></span> : null}
                          {reason.mutation_event_id ? <span>Decision: <code>{reason.mutation_event_id}</code></span> : null}
                        </div>
                      </article>
                    ))
                  ) : (
                    <span className="runtime-link-empty">none</span>
                  )}
                </div>
              </div>
              <div className="runtime-replay-section">
                <div className="runtime-replay-section-header">
                  <strong>Supersession / decision links</strong>
                  <span className="pane-count">{replayProposalLinks.length}</span>
                </div>
                <div className="runtime-replay-list">
                  {replayProposalLinks.length > 0 ? (
                    replayProposalLinks.map((proposal) => (
                      <article className="runtime-replay-card" key={proposal.proposal_event_id}>
                        <div className="runtime-replay-card-head">
                          <strong>{proposal.proposal_id}</strong>
                          <span className={`state-pill runtime-state-pill ${proposal.state}`}>
                            {proposal.state}
                          </span>
                        </div>
                        <dl className="runtime-link-facts">
                          <div>
                            <dt>Proposal event</dt>
                            <dd>{proposal.proposal_event_id}</dd>
                          </div>
                          <div>
                            <dt>Decision event</dt>
                            <dd>{proposal.decision_event_id ?? 'pending'}</dd>
                          </div>
                          <div>
                            <dt>Affected nodes</dt>
                            <dd>{proposal.affected_node_ids.join(', ') || 'none'}</dd>
                          </div>
                        </dl>
                      </article>
                    ))
                  ) : (
                    <span className="runtime-link-empty">none</span>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </section>
      <section className="runtime-node-surface" aria-label="Runtime node surface">
        <section className="runtime-node-list-panel" aria-labelledby="runtime-node-list-heading">
          <div className="runtime-node-list-header">
            <div className="pane-title" id="runtime-node-list-heading">
              <LayoutList size={16} />
              Runtime nodes
              <span className="pane-count">{runtimeFlow?.nodes.length ?? 0}</span>
            </div>
            <span className="review-note">Sorted to match the graph layout</span>
          </div>
          {!runtimeFlow || runtimeFlow.nodes.length === 0 ? (
            <div className="empty-state-card" role="status" aria-live="polite">
              <strong>No runtime nodes</strong>
              <p>The ledger has not exposed any current workflow nodes yet.</p>
            </div>
          ) : (
            <div className="runtime-node-list" aria-label="Runtime workflow nodes">
              {runtimeFlow.orderedNodes.map((node) => {
                const isSelected = node.id === selectedNodeId;
                return (
                  <button
                    key={node.id}
                    type="button"
                    className={`runtime-node-chip state-${node.data.gatekeeperTone}${isSelected ? ' selected' : ''}`}
                    onClick={() => onSelectNode(node.id)}
                  >
                    <div className="runtime-node-chip-title">
                      <strong>{node.id}</strong>
                      <span className={`state-pill runtime-state-pill ${node.data.gatekeeperTone}`}>
                        {node.data.gatekeeperStateLabel}
                      </span>
                    </div>
                    <span>{node.data.role}</span>
                    <small>{node.data.stateSummary}</small>
                    {node.data.primaryReason ? <small className="runtime-node-chip-reason">{node.data.primaryReason}</small> : null}
                  </button>
                );
              })}
            </div>
          )}
        </section>
        <section className="runtime-node-inspector" aria-labelledby="runtime-node-inspector-heading">
          <div className="runtime-node-list-header">
            <div className="pane-title" id="runtime-node-inspector-heading">
              <GitBranch size={16} />
              Runtime node inspector
            </div>
            {selectedNode ? <span className="pane-count">{selectedNode.data.role}</span> : null}
          </div>
          {!selectedNode ? (
            <div className="empty-state-card" role="status" aria-live="polite">
              <strong>No runtime node selected</strong>
              <p>Select a runtime node from the list or graph to inspect its state.</p>
            </div>
          ) : (
            <div className="runtime-node-inspector-card">
              <div className="runtime-node-inspector-header">
                <div>
                  <span className="review-note">Selected node</span>
                  <strong>{selectedNode.id}</strong>
                </div>
                <div className="badge-row runtime-node-inspector-badges">
                  <span className="badge">{selectedNode.data.role}</span>
                  <span className={`state-pill runtime-state-pill ${selectedNode.data.gatekeeperTone}`}>
                    {selectedNode.data.gatekeeperStateLabel}
                  </span>
                </div>
              </div>
              <div className="runtime-node-inspector-summary">
                <span>Gatekeeper summary</span>
                <strong>{selectedNode.data.stateSummary}</strong>
              </div>
              {selectedNode.data.blockedReasons.length > 0 ? (
                <div className="runtime-blocked-reasons" aria-label="Gatekeeper reasons">
                  <div className="runtime-blocked-reasons-header">
                    <AlertCircle size={14} />
                    <strong>Why this node is not runnable</strong>
                  </div>
                  <div className="runtime-reason-list">
                    {selectedNode.data.blockedReasons.map((reason, index) => (
                      <article
                        key={`${selectedNode.id}:${reason.code}:${reason.message}:${index}`}
                        className={`runtime-reason-card reason-${runtimeReasonTone(reason.code)}`}
                      >
                        <div className="runtime-reason-heading">
                          <span className={`state-pill runtime-state-pill ${runtimeReasonTone(reason.code)}`}>
                            {formatReasonCode(reason.code)}
                          </span>
                          <p>{reason.message}</p>
                        </div>
                        <div className="runtime-reason-meta">
                          {reason.missing_ref ? <span>Missing ref: <code>{reason.missing_ref}</code></span> : null}
                          {reason.gate_id ? <span>Gate: <code>{reason.gate_id}</code></span> : null}
                          {reason.assignment_id ? <span>Assignment: <code>{reason.assignment_id}</code></span> : null}
                          {reason.mutation_event_id ? <span>Mutation: <code>{reason.mutation_event_id}</code></span> : null}
                        </div>
                      </article>
                    ))}
                  </div>
                </div>
              ) : null}
              <dl className="runtime-node-inspector-facts">
                <div>
                  <dt>Waits for all</dt>
                  <dd>{selectedNode.data.waitsForAll.length > 0 ? selectedNode.data.waitsForAll.join(', ') : 'none'}</dd>
                </div>
                <div>
                  <dt>Waits for any</dt>
                  <dd>{selectedNode.data.waitsForAny.length > 0 ? selectedNode.data.waitsForAny.join(', ') : 'none'}</dd>
                </div>
                <div>
                  <dt>Emits</dt>
                  <dd>{selectedNode.data.emits.length > 0 ? selectedNode.data.emits.join(', ') : 'none'}</dd>
                </div>
                <div>
                  <dt>Gates</dt>
                  <dd>{selectedNode.data.gateCount}</dd>
                </div>
              </dl>
            </div>
          )}
        </section>
      </section>
      {isLoading ? <p className="empty-state-message">Loading runtime workflow.</p> : null}
    </section>
  );
}

function MutationPanel({
  proposals,
  currentNodeIds,
  ledgerPath,
  isLoading,
  error,
  decisionError,
  isDeciding,
  selectedNodeId,
  onSelectNode,
  onDecision,
}: {
  proposals: MutationProposalInspection[];
  currentNodeIds: string[];
  ledgerPath: string;
  isLoading: boolean;
  error: string | null;
  decisionError: string | null;
  isDeciding: boolean;
  selectedNodeId?: string;
  onSelectNode: (nodeId: string) => void;
  onDecision: (
    proposalEventId: string,
    decision: 'accept' | 'reject',
    reason?: string,
  ) => void;
}) {
  const [rejectionReasons, setRejectionReasons] = useState<Record<string, string>>({});

  return (
    <section className="mutation-panel" aria-label="Runtime workflow mutations" aria-busy={isDeciding}>
      <div className="pane-title">
        <GitBranch size={16} />
        Runtime workflow mutations
        <span className="pane-count">
          {proposals.filter((proposal) => proposal.state === 'pending').length}
        </span>
      </div>
      <code className="mutation-source" title={ledgerPath}>{ledgerPath}</code>
      <div className="mutation-context">
        <p className="mutation-current">
          <span>Runtime workflow now</span>
          {currentNodeIds.join(', ') || 'unavailable'}
        </p>
        <p className="mutation-note">
          This panel reflects the runtime workflow from the ledger. Switch to Planning DAG to edit graph structure.
        </p>
        {isDeciding ? (
          <p className="mutation-sync-note" role="status" aria-live="polite">
            Applying decision and refreshing runtime state.
          </p>
        ) : null}
      </div>
      {isLoading ? <p className="diagnostics-text">Loading mutation proposals.</p> : null}
      {error ? <p className="mutation-error" role="alert">{error}</p> : null}
      {!isLoading && !error && proposals.length === 0 ? (
        <p className="diagnostics-text">No workflow mutations recorded.</p>
      ) : null}
      <div className="mutation-list">
        {proposals.map((proposal) => {
          const rejectionReason = rejectionReasons[proposal.proposal_event_id] ?? '';
          const preview = summarizeWorkflowPreview(currentNodeIds, proposal);
          const clickableNodeIds = proposal.affected_node_ids.filter((nodeId) => currentNodeIds.includes(nodeId));
          return (
            <article className="mutation-item" key={proposal.proposal_event_id}>
              <div className="mutation-heading">
                <div className="mutation-heading-title">
                  <strong>{proposal.proposal_id}</strong>
                  <span className="mutation-heading-subtitle">
                    {proposal.affected_node_ids.length > 0 ? `${proposal.affected_node_ids.length} affected node${proposal.affected_node_ids.length === 1 ? '' : 's'}` : 'No affected nodes'}
                  </span>
                </div>
                <span className={`mutation-state ${proposal.state}`}>{proposal.state}</span>
              </div>
              <p>{proposal.proposal.rationale ?? proposal.proposal.reason ?? 'No rationale recorded.'}</p>
              <dl className="mutation-facts">
                <div>
                  <dt>Affected nodes</dt>
                  <dd className="mutation-node-list">
                    {proposal.affected_node_ids.length > 0 ? (
                      proposal.affected_node_ids.map((nodeId) => {
                        const isCurrent = currentNodeIds.includes(nodeId);
                        const isSelected = nodeId === selectedNodeId;
                        return isCurrent ? (
                          <button
                            key={nodeId}
                            type="button"
                            className={`mutation-node-chip${isSelected ? ' selected' : ''}`}
                            onClick={() => onSelectNode(nodeId)}
                          >
                            {nodeId}
                          </button>
                        ) : (
                          <code key={nodeId} className="mutation-node-chip disabled" title="Not present in the current runtime">
                            {nodeId}
                          </code>
                        );
                      })
                    ) : (
                      <span>none</span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Affected assignments</dt>
                  <dd>
                    {proposal.affected_assignments.length > 0 ? (
                      <div className="mutation-node-links" aria-label={`Affected assignments for ${proposal.proposal_id}`}>
                        {proposal.affected_assignments.map((assignmentId) => (
                          <span key={`${proposal.proposal_event_id}:${assignmentId}`} className="mutation-node-chip mutation-node-chip-static">
                            {assignmentId}
                          </span>
                        ))}
                      </div>
                    ) : (
                      'none'
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Superseded evidence</dt>
                  <dd>
                    {proposal.superseded_assignments.length > 0 ? (
                      <div className="mutation-node-links" aria-label={`Superseded assignments for ${proposal.proposal_id}`}>
                        {proposal.superseded_assignments.map((assignmentId) => (
                          <span key={`${proposal.proposal_event_id}:${assignmentId}`} className="mutation-node-chip mutation-node-chip-static">
                            {assignmentId}
                          </span>
                        ))}
                      </div>
                    ) : (
                      'none'
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Evidence</dt>
                  <dd>{proposal.evidence_refs.join(', ') || 'none'}</dd>
                </div>
                <div>
                  <dt>Changes</dt>
                  <dd>{summarizeMutationChanges(proposal)}</dd>
                </div>
              </dl>
              {clickableNodeIds.length > 0 ? (
                <div className="mutation-node-actions" aria-label={`Affected runtime nodes for ${proposal.proposal_id}`}>
                  {clickableNodeIds.map((nodeId) => (
                    <button
                      key={nodeId}
                      type="button"
                      className={`mutation-node-link${nodeId === selectedNodeId ? ' selected' : ''}`}
                      onClick={() => onSelectNode(nodeId)}
                    >
                      <LayoutList size={12} />
                      <span>{nodeId}</span>
                    </button>
                  ))}
                </div>
              ) : null}
              <div className="mutation-preview" aria-label={`Workflow preview for ${proposal.proposal_id}`}>
                <div className="mutation-preview-card">
                  <span className="mutation-preview-label">Current runtime workflow</span>
                  <strong>{preview.currentNodes}</strong>
                </div>
                <div className="mutation-preview-card">
                  <span className="mutation-preview-label">
                    {proposal.state === 'accepted' ? 'Applied workflow' : 'Proposed workflow'}
                  </span>
                  <strong>{preview.proposedNodes}</strong>
                  <small>{preview.edgeSummary}</small>
                </div>
              </div>
              {proposal.state === 'pending' ? (
                <>
                  <input
                    className="mutation-reason"
                    value={rejectionReason}
                    onChange={(event) =>
                      setRejectionReasons((current) => ({
                        ...current,
                        [proposal.proposal_event_id]: event.target.value,
                      }))
                    }
                    placeholder="Rejection reason"
                    aria-label={`Rejection reason for ${proposal.proposal_id}`}
                  />
                  <div className="mutation-actions">
                    <button
                      type="button"
                      className="mutation-accept"
                      onClick={() => onDecision(proposal.proposal_event_id, 'accept')}
                      disabled={isDeciding}
                    >
                      <CheckCircle2 size={14} /> Accept
                    </button>
                    <button
                      type="button"
                      className="mutation-reject"
                      onClick={() =>
                        onDecision(
                          proposal.proposal_event_id,
                          'reject',
                          rejectionReason.trim(),
                        )
                      }
                      disabled={isDeciding || !rejectionReason.trim()}
                    >
                      <XCircle size={14} /> Reject
                    </button>
                  </div>
                </>
              ) : null}
            </article>
          );
        })}
      </div>
      {decisionError ? <p className="mutation-error" role="alert">{decisionError}</p> : null}
    </section>
  );
}

function summarizeMutationChanges(proposal: MutationProposalInspection): string {
  const changes = proposal.proposal.proposed_changes ?? {};
  const parts = Object.entries(changes)
    .filter(([, operations]) => Array.isArray(operations) && operations.length > 0)
    .map(([operation, operations]) => `${operation}: ${operations.length}`);
  return parts.join(', ') || 'none';
}

type MutationChangeRecord = Record<string, unknown[]>;

function summarizeWorkflowPreview(
  currentNodeIds: string[],
  proposal: MutationProposalInspection,
): { currentNodes: string; proposedNodes: string; edgeSummary: string } {
  const changes = proposal.proposal.proposed_changes as MutationChangeRecord | undefined;
  const addNodes = Array.isArray(changes?.add_nodes) ? changes.add_nodes : [];
  const addEdges = Array.isArray(changes?.add_edges) ? changes.add_edges : [];
  const removeEdges = Array.isArray(changes?.remove_edges) ? changes.remove_edges : [];
  const proposedNodeIds = [
    ...new Set([
      ...currentNodeIds,
      ...addNodes
        .map((entry) => mutationNodeId(entry))
        .filter((value): value is string => Boolean(value)),
    ]),
  ];

  const edgeParts = [
    ...removeEdges
      .map((entry) => mutationEdgeLabel(entry, '-'))
      .filter((value): value is string => Boolean(value)),
    ...addEdges
      .map((entry) => mutationEdgeLabel(entry, '+'))
      .filter((value): value is string => Boolean(value)),
  ];

  return {
    currentNodes: currentNodeIds.join(', ') || 'unavailable',
    proposedNodes: proposedNodeIds.join(', ') || 'unavailable',
    edgeSummary: edgeParts.join(' | ') || 'No edge rewiring',
  };
}

function mutationNodeId(entry: unknown): string | null {
  if (!entry || typeof entry !== 'object') {
    return null;
  }
  const id = (entry as { id?: unknown }).id;
  return typeof id === 'string' && id ? id : null;
}

function mutationEdgeLabel(entry: unknown, prefix: '+' | '-'): string | null {
  if (!entry || typeof entry !== 'object') {
    return null;
  }
  const edge = entry as {
    from_node?: unknown;
    to_node?: unknown;
    event?: unknown;
  };
  if (
    typeof edge.from_node !== 'string'
    || typeof edge.to_node !== 'string'
    || typeof edge.event !== 'string'
  ) {
    return null;
  }
  return `${prefix} ${edge.from_node} -> ${edge.to_node} (${edge.event})`;
}

function splitRuntimeWaitsFor(waitsFor: RuntimeWorkflowWaitsFor): { allOf: string[]; anyOf: string[] } {
  if (Array.isArray(waitsFor)) {
    return { allOf: waitsFor.filter((entry): entry is string => typeof entry === 'string'), anyOf: [] };
  }
  if (!waitsFor || typeof waitsFor !== 'object') {
    return { allOf: [], anyOf: [] };
  }
  return {
    allOf: Array.isArray(waitsFor.all_of) ? waitsFor.all_of.filter((entry): entry is string => typeof entry === 'string') : [],
    anyOf: Array.isArray(waitsFor.any_of) ? waitsFor.any_of.filter((entry): entry is string => typeof entry === 'string') : [],
  };
}

function runtimeNodeDependencyIds(workflow: RuntimeWorkflow, node: RuntimeWorkflowNode): string[] {
  const dependencies = runtimeWorkflowDependencies(workflow, node).map((dependency) => dependency.sourceId);
  return [...new Set(dependencies)];
}

type RuntimeWorkflowEdgeDescriptor = {
  id: string;
  sourceId: string;
  targetId: string;
  eventRef: string;
  branch: 'all' | 'any';
  sourcePortId: string;
  targetPortId: string;
};

type RuntimeElkLayoutNode = DirectedElkLayoutNode;
type RuntimeElkLayoutEdge = DirectedElkLayoutEdge;
type RuntimeElkLayout = DirectedElkLayout;

function runtimeWorkflowEdges(
  descriptors: RuntimeWorkflowEdgeDescriptor[],
  sectionsByEdgeId: Map<string, XYPosition[][]> = new Map(),
  onSelectEdge?: (edge: { source: string; target: string; eventRef: string }) => void,
): Edge<RuntimeFlowEdgeData>[] {
  return descriptors.map((dependency) => ({
    id: dependency.id,
    source: dependency.sourceId,
    sourceHandle: dependency.sourcePortId,
    target: dependency.targetId,
    targetHandle: dependency.targetPortId,
    ariaLabel: `${dependency.sourceId} triggers ${dependency.eventRef} for ${dependency.targetId}`,
    className: dependency.branch === 'any' ? 'flow-edge runtime any' : 'flow-edge runtime',
    data: {
      eventRef: dependency.eventRef,
      sections: sectionsByEdgeId.get(dependency.id) ?? [],
      onSelectEdge,
    },
    focusable: false,
    interactionWidth: 20,
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 16,
      height: 16,
      color: dependency.branch === 'any' ? 'var(--review)' : 'var(--accent)',
    },
    pathOptions: {
      borderRadius: 24,
      offset: 44,
    },
    type: 'runtime-orthogonal',
  }));
}

type PlanningFlowEdgeDescriptor = DirectedFlowEdgeDescriptor;

function planningFlowEdgeDescriptors(
  nodes: TaskNode[],
  edges: Array<{ id: string; source: string; target: string }>,
): PlanningFlowEdgeDescriptor[] {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const validEdges = edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target) && edge.source !== edge.target);
  const sourceCounts = new Map<string, number>();
  const targetCounts = new Map<string, number>();
  for (const edge of validEdges) {
    sourceCounts.set(edge.source, (sourceCounts.get(edge.source) ?? 0) + 1);
    targetCounts.set(edge.target, (targetCounts.get(edge.target) ?? 0) + 1);
  }
  const sourceIndexes = new Map<string, number>();
  const targetIndexes = new Map<string, number>();

  return validEdges.map((edge) => {
    const sourceIndex = sourceIndexes.get(edge.source) ?? 0;
    sourceIndexes.set(edge.source, sourceIndex + 1);
    const targetIndex = targetIndexes.get(edge.target) ?? 0;
    targetIndexes.set(edge.target, targetIndex + 1);
    return {
      id: edge.id,
      sourceId: edge.source,
      targetId: edge.target,
      sourceIndex,
      sourceCount: sourceCounts.get(edge.source) ?? 1,
      targetIndex,
      targetCount: targetCounts.get(edge.target) ?? 1,
    };
  });
}

function buildPlanningElkGraph(nodes: TaskNode[], edgeDescriptors: PlanningFlowEdgeDescriptor[]): any {
  return {
    id: 'root',
    layoutOptions: RUNTIME_ELK_LAYOUT_OPTIONS,
    children: nodes.map((node) => {
      return {
        id: node.id,
        width: PLANNING_NODE_WIDTH,
        height: PLANNING_NODE_HEIGHT,
        layoutOptions: {
          'elk.portConstraints': 'FIXED_SIDE',
        },
        ports: [
          {
            id: `${node.id}:in`,
            width: 0,
            height: 0,
            layoutOptions: {
              'elk.port.side': 'WEST',
              'elk.port.index': '0',
            },
          },
          {
            id: `${node.id}:out`,
            width: 0,
            height: 0,
            layoutOptions: {
              'elk.port.side': 'EAST',
              'elk.port.index': '0',
            },
          },
        ],
      };
    }),
    edges: edgeDescriptors.map((descriptor) => ({
      id: descriptor.id,
      sources: [`${descriptor.sourceId}:out`],
      targets: [`${descriptor.targetId}:in`],
    })),
  };
}

function buildPlanningFlowLayoutFallback(nodes: TaskNode[], edges: Array<{ id: string; source: string; target: string }>): PlanningFlowLayout {
  const edgeDescriptors = planningFlowEdgeDescriptors(nodes, edges);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const dependenciesById = new Map(nodes.map((node) => [node.id, [] as string[]] as const));
  for (const edge of edges) {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) {
      continue;
    }
    dependenciesById.get(edge.target)?.push(edge.source);
  }
  const dependencyView = nodes.map((node) => ({
    id: node.id,
    dependencies: dependenciesById.get(node.id) ?? [],
  }));
  const positions = computeDirectedNodePositions(nodes, dependencyView, PLANNING_LAYOUT_SPACING, {
    levelStagger: PLANNING_LAYOUT_SPACING.rowGap,
  });

  const flowNodes = nodes.map((node) => ({
    id: node.id,
    position: positions.get(node.id) ?? { x: PLANNING_LAYOUT_SPACING.originX, y: PLANNING_LAYOUT_SPACING.originY },
    style: {
      width: PLANNING_NODE_WIDTH,
      height: PLANNING_NODE_HEIGHT,
    },
    data: {
      title: node.title,
      recommendedModel: node.recommended_model,
      reviewGate: node.review_gate,
      nodeState: 'blocked',
      riskLevel: node.risk_level,
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    type: 'dag',
  }));

  const flowEdges = planningFlowEdges(edgeDescriptors, new Map());

  const orderedNodes = flowNodes
    .slice()
    .sort((left, right) => {
      const leftPosition = positions.get(left.id) ?? { x: 0, y: 0 };
      const rightPosition = positions.get(right.id) ?? { x: 0, y: 0 };
      return leftPosition.x - rightPosition.x || leftPosition.y - rightPosition.y || left.id.localeCompare(right.id);
    });

  return {
    nodes: flowNodes,
    edges: flowEdges,
    orderedNodes,
  };
}

async function buildPlanningFlowLayout(nodes: TaskNode[], edges: Array<{ id: string; source: string; target: string }>): Promise<PlanningFlowLayout> {
  const edgeDescriptors = planningFlowEdgeDescriptors(nodes, edges);
  const elkGraph = buildPlanningElkGraph(nodes, edgeDescriptors);
  const laidOut = (await planningElk.layout(elkGraph)) as DirectedElkLayout;
  const layoutNodesById = new Map((laidOut.children ?? []).map((child) => [child.id, child] as const));
  const sectionsByEdgeId = new Map<string, XYPosition[][]>();
  const positions = new Map<string, { x: number; y: number }>();

  for (const node of nodes) {
    const layoutNode = layoutNodesById.get(node.id);
    if (layoutNode) {
      positions.set(node.id, {
        x: layoutNode.x ?? PLANNING_LAYOUT_SPACING.originX,
        y: layoutNode.y ?? PLANNING_LAYOUT_SPACING.originY,
      });
    }
  }

  for (const edge of laidOut.edges ?? []) {
    sectionsByEdgeId.set(
      edge.id,
      (edge.sections ?? []).map((section) => [
        section.startPoint,
        ...(section.bendPoints ?? []),
        section.endPoint,
      ]),
    );
  }

  const flowNodes = nodes.map((node) => ({
    id: node.id,
    position: positions.get(node.id) ?? { x: PLANNING_LAYOUT_SPACING.originX, y: PLANNING_LAYOUT_SPACING.originY },
    style: {
      width: PLANNING_NODE_WIDTH,
      height: PLANNING_NODE_HEIGHT,
    },
    data: {
      title: node.title,
      recommendedModel: node.recommended_model,
      reviewGate: node.review_gate,
      nodeState: 'blocked',
      riskLevel: node.risk_level,
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    type: 'dag',
  }));

  const flowEdges = planningFlowEdges(edgeDescriptors, sectionsByEdgeId);

  const orderedNodes = flowNodes
    .slice()
    .sort((left, right) => {
      const leftPosition = positions.get(left.id) ?? { x: 0, y: 0 };
      const rightPosition = positions.get(right.id) ?? { x: 0, y: 0 };
      return leftPosition.x - rightPosition.x || leftPosition.y - rightPosition.y || left.id.localeCompare(right.id);
    });

  return {
    nodes: flowNodes,
    edges: flowEdges,
    orderedNodes,
  };
}

function planningFlowEdges(
  descriptors: PlanningFlowEdgeDescriptor[],
  sectionsByEdgeId: Map<string, XYPosition[][]> = new Map(),
): Edge<OrthogonalFlowEdgeData>[] {
  return descriptors.map((descriptor) => ({
    id: descriptor.id,
    source: descriptor.sourceId,
    sourceHandle: `${descriptor.sourceId}:out`,
    target: descriptor.targetId,
    targetHandle: `${descriptor.targetId}:in`,
    ariaLabel: `${descriptor.sourceId} dependency for ${descriptor.targetId}`,
    animated: true,
    data: {
      sections: sectionsByEdgeId.get(descriptor.id) ?? [],
      sourceIndex: descriptor.sourceIndex,
      sourceCount: descriptor.sourceCount,
      targetIndex: descriptor.targetIndex,
      targetCount: descriptor.targetCount,
    },
    deletable: true,
    focusable: true,
    interactionWidth: 24,
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 16,
      height: 16,
      color: 'var(--accent)',
    },
    pathOptions: {
      borderRadius: 24,
      offset: 44,
    },
    type: DAG_ORTHOGONAL_EDGE_TYPE,
  }));
}

function runtimeWorkflowEdgeDescriptors(workflow: RuntimeWorkflow): RuntimeWorkflowEdgeDescriptor[] {
  const sourcePortIndexes = new Map<string, number>();
  const targetPortIndexes = new Map<string, number>();

  return workflow.nodes.flatMap((node) =>
    runtimeWorkflowDependencies(workflow, node).map((dependency) => {
      const sourcePortIndex = sourcePortIndexes.get(dependency.sourceId) ?? 0;
      sourcePortIndexes.set(dependency.sourceId, sourcePortIndex + 1);
      const targetPortIndex = targetPortIndexes.get(node.id) ?? 0;
      targetPortIndexes.set(node.id, targetPortIndex + 1);
      return {
        id: `runtime:${dependency.sourceId}:${node.id}:${dependency.eventRef}:${dependency.branch}`,
        sourceId: dependency.sourceId,
        targetId: node.id,
        eventRef: dependency.eventRef,
        branch: dependency.branch,
        sourcePortId: `${dependency.sourceId}:out:${sourcePortIndex}`,
        targetPortId: `${node.id}:in:${targetPortIndex}`,
      };
    }),
  );
}

function runtimeWorkflowDependencies(
  workflow: RuntimeWorkflow,
  node: RuntimeWorkflowNode,
): Array<{ sourceId: string; eventRef: string; branch: 'all' | 'any' }> {
  const waitsFor = splitRuntimeWaitsFor(node.waits_for);
  const eventSources = workflow.nodes.reduce<Map<string, string[]>>((sources, candidate) => {
    for (const eventName of candidate.emits) {
      const current = sources.get(eventName) ?? [];
      current.push(candidate.id);
      sources.set(eventName, current);
    }
    return sources;
  }, new Map());

  const resolveRefs = (refs: string[], branch: 'all' | 'any') =>
    refs.flatMap((eventRef) => {
      const explicitSource = runtimeEventRefSourceId(eventRef);
      if (explicitSource) {
        return workflow.nodes.some((candidate) => candidate.id === explicitSource)
          ? [{ sourceId: explicitSource, eventRef, branch }]
          : [];
      }
      const eventName = runtimeEventRefName(eventRef);
      return (eventSources.get(eventName) ?? []).map((sourceId) => ({ sourceId, eventRef, branch }));
    });

  return [...resolveRefs(waitsFor.allOf, 'all'), ...resolveRefs(waitsFor.anyOf, 'any')];
}

function directedFlowNodePortLayouts(
  nodeIds: string[],
  edgeDescriptors: Array<{
    sourceId: string;
    targetId: string;
    sourcePortId: string;
    targetPortId: string;
  }>,
  nodeHeight: number,
  layoutNodesById?: Map<string, DirectedElkLayoutNode>,
): Map<string, { incomingPorts: FlowNodePort[]; outgoingPorts: FlowNodePort[] }> {
  const nodePorts = new Map<string, { incomingPorts: FlowNodePort[]; outgoingPorts: FlowNodePort[] }>();

  for (const nodeId of nodeIds) {
    const layoutNode = layoutNodesById?.get(nodeId);
    const layoutPortsById = new Map(layoutNode?.ports?.map((port) => [port.id, port] as const) ?? []);
    const incomingEdges = edgeDescriptors.filter((descriptor) => descriptor.targetId === nodeId);
    const outgoingEdges = edgeDescriptors.filter((descriptor) => descriptor.sourceId === nodeId);
    const incomingFallbackYs = directedPortOffsets(incomingEdges.length, nodeHeight);
    const outgoingFallbackYs = directedPortOffsets(outgoingEdges.length, nodeHeight);
    nodePorts.set(nodeId, {
      incomingPorts: incomingEdges.map((descriptor, index) => ({
        id: descriptor.targetPortId,
        y: clampFlowPortOffset(layoutPortsById.get(descriptor.targetPortId)?.y ?? incomingFallbackYs[index] ?? nodeHeight / 2, nodeHeight),
      })),
      outgoingPorts: outgoingEdges.map((descriptor, index) => ({
        id: descriptor.sourcePortId,
        y: clampFlowPortOffset(layoutPortsById.get(descriptor.sourcePortId)?.y ?? outgoingFallbackYs[index] ?? nodeHeight / 2, nodeHeight),
      })),
    });
  }

  return nodePorts;
}

function directedPortOffsets(count: number, nodeHeight: number): number[] {
  if (count <= 0) {
    return [];
  }
  if (count === 1) {
    return [nodeHeight / 2];
  }
  const top = 18;
  const bottom = nodeHeight - 18;
  const step = (bottom - top) / (count - 1);
  return Array.from({ length: count }, (_, index) => top + index * step);
}

function clampFlowPortOffset(offset: number, nodeHeight: number): number {
  return Math.max(12, Math.min(nodeHeight - 12, offset));
}

function directedEdgePath(
  sections: XYPosition[][],
  fallback: {
    sourceX: number;
    sourceY: number;
    sourcePosition: Position;
    targetX: number;
    targetY: number;
    targetPosition: Position;
    sourceIndex?: number;
    sourceCount?: number;
    targetIndex?: number;
    targetCount?: number;
  },
): string {
  if (sections.length > 0 && areEdgeSectionsAnchoredToFallback(sections, fallback)) {
    return sections
      .map((section) => {
        if (section.length === 0) {
          return '';
        }
        const [firstPoint, ...rest] = section;
        return `M ${firstPoint.x} ${firstPoint.y} ${rest.map((point) => `L ${point.x} ${point.y}`).join(' ')}`.trim();
      })
      .filter((segment) => segment.length > 0)
      .join(' ');
  }

  return orthogonalEdgePath(fallback);
}

function areEdgeSectionsAnchoredToFallback(
  sections: XYPosition[][],
  fallback: {
    sourceX: number;
    sourceY: number;
    targetX: number;
    targetY: number;
  },
): boolean {
  const firstSection = sections[0];
  const lastSection = sections[sections.length - 1];
  if (!firstSection || firstSection.length === 0 || !lastSection || lastSection.length === 0) {
    return false;
  }
  const startPoint = firstSection[0];
  const endPoint = lastSection[lastSection.length - 1];
  return (
    Math.abs(startPoint.x - fallback.sourceX) < 1.5 &&
    Math.abs(startPoint.y - fallback.sourceY) < 1.5 &&
    Math.abs(endPoint.x - fallback.targetX) < 1.5 &&
    Math.abs(endPoint.y - fallback.targetY) < 1.5
  );
}

function orthogonalEdgePath(fallback: {
  sourceX: number;
  sourceY: number;
  sourcePosition: Position;
  targetX: number;
  targetY: number;
  targetPosition: Position;
  sourceIndex?: number;
  sourceCount?: number;
  targetIndex?: number;
  targetCount?: number;
}): string {
  const sourceSpread = balanceIndexOffset(fallback.sourceIndex ?? 0, fallback.sourceCount ?? 1, 8);
  const targetSpread = balanceIndexOffset(fallback.targetIndex ?? 0, fallback.targetCount ?? 1, 8);
  const sourceY = fallback.sourceY + sourceSpread;
  const targetY = fallback.targetY + targetSpread;
  const corridorX = (fallback.sourceX + fallback.targetX) / 2;
  return [
    `M ${fallback.sourceX} ${sourceY}`,
    `L ${corridorX} ${sourceY}`,
    `L ${corridorX} ${targetY}`,
    `L ${fallback.targetX} ${targetY}`,
  ].join(' ');
}

function balanceIndexOffset(index: number, count: number, spacing: number): number {
  if (count <= 1) {
    return 0;
  }
  return (index - (count - 1) / 2) * spacing;
}

function buildRuntimeFlowLayoutFallback(
  workflow: RuntimeWorkflow,
  decisions: Record<string, GatekeeperDecision>,
  selectedNodeId: string | undefined,
  onSelectEdge?: (edge: { source: string; target: string; eventRef: string }) => void,
): RuntimeFlowLayout {
  const edgeDescriptors = runtimeWorkflowEdgeDescriptors(workflow);
  const dependencyView = workflow.nodes.map((node) => ({
    id: node.id,
    dependencies: runtimeNodeDependencyIds(workflow, node),
  }));
  const positions = computeDirectedNodePositions(workflow.nodes, dependencyView, RUNTIME_LAYOUT_SPACING, {
    levelStagger: RUNTIME_LAYOUT_SPACING.rowGap,
  });
  const portLayouts = runtimeFlowNodePortLayouts(workflow, edgeDescriptors);
  const terminalEvents = new Set(workflow.terminal_events);
  const gateCounts = workflow.gates.reduce<Map<string, number>>((counts, gate) => {
    counts.set(gate.node_id, (counts.get(gate.node_id) ?? 0) + 1);
    return counts;
  }, new Map());

  const nodes = workflow.nodes.map((node) => {
    const waitsFor = splitRuntimeWaitsFor(node.waits_for);
    const decision = decisions[node.id];
    const stateSummary = summarizeRuntimeNodeState({
      decision,
      waitsForAll: waitsFor.allOf,
      waitsForAny: waitsFor.anyOf,
      emits: node.emits,
      isTerminal: node.emits.some((eventName) => terminalEvents.has(eventName)),
    });
    const gatekeeperTone = runtimeDecisionTone(decision);
    const primaryReason = summarizePrimaryReason(decision?.blocked_reasons ?? []);

    return {
      id: node.id,
      selected: node.id === selectedNodeId,
      position: positions.get(node.id) ?? { x: RUNTIME_LAYOUT_SPACING.originX, y: RUNTIME_LAYOUT_SPACING.originY },
      style: {
        width: RUNTIME_NODE_WIDTH,
        height: RUNTIME_NODE_HEIGHT,
      },
      data: {
        role: node.role,
        gatekeeperState: decision?.state ?? 'unknown',
        gatekeeperStateLabel: formatRuntimeStateLabel(decision?.state),
        gatekeeperTone,
        stateSummary,
        primaryReason,
        blockedReasons: decision?.blocked_reasons ?? [],
        emits: node.emits,
        waitsForAll: waitsFor.allOf,
        waitsForAny: waitsFor.anyOf,
        isTerminal: node.emits.some((eventName) => terminalEvents.has(eventName)),
        gateCount: gateCounts.get(node.id) ?? 0,
        incomingPorts: portLayouts.get(node.id)?.incomingPorts ?? [],
        outgoingPorts: portLayouts.get(node.id)?.outgoingPorts ?? [],
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      type: 'runtime',
    };
  });

  const orderedNodes = nodes
    .slice()
    .sort((left, right) => compareRuntimeNodePositions(left, right, positions));

  return {
    nodes,
    edges: runtimeWorkflowEdges(edgeDescriptors, new Map(), onSelectEdge),
    orderedNodes,
  };
}

async function buildRuntimeFlowLayout(
  workflow: RuntimeWorkflow,
  decisions: Record<string, GatekeeperDecision>,
  selectedNodeId: string | undefined,
  onSelectEdge?: (edge: { source: string; target: string; eventRef: string }) => void,
): Promise<RuntimeFlowLayout> {
  const edgeDescriptors = runtimeWorkflowEdgeDescriptors(workflow);
  const fallbackLayout = buildRuntimeFlowLayoutFallback(workflow, decisions, selectedNodeId, onSelectEdge);
  try {
    return await buildRuntimeFlowLayoutWithElk(workflow, decisions, selectedNodeId, edgeDescriptors, onSelectEdge);
  } catch (error) {
    console.warn('Runtime ELK layout failed, falling back to manual routing.', error);
    return fallbackLayout;
  }
}

async function buildRuntimeFlowLayoutWithElk(
  workflow: RuntimeWorkflow,
  decisions: Record<string, GatekeeperDecision>,
  selectedNodeId: string | undefined,
  edgeDescriptors: RuntimeWorkflowEdgeDescriptor[],
  onSelectEdge?: (edge: { source: string; target: string; eventRef: string }) => void,
): Promise<RuntimeFlowLayout> {
  const elkGraph = buildRuntimeElkGraph(workflow, edgeDescriptors);
  const laidOut = (await runtimeElk.layout(elkGraph)) as RuntimeElkLayout;
  const layoutNodesById = new Map((laidOut.children ?? []).map((child) => [child.id, child] as const));
  const sectionsByEdgeId = new Map<string, XYPosition[][]>();
  const positions = new Map<string, { x: number; y: number }>();
  const portLayouts = runtimeFlowNodePortLayouts(workflow, edgeDescriptors, layoutNodesById);

  for (const node of workflow.nodes) {
    const layoutNode = layoutNodesById.get(node.id);
    if (layoutNode) {
      positions.set(node.id, {
        x: layoutNode.x ?? RUNTIME_LAYOUT_SPACING.originX,
        y: layoutNode.y ?? RUNTIME_LAYOUT_SPACING.originY,
      });
    }
  }

  for (const edge of laidOut.edges ?? []) {
    sectionsByEdgeId.set(
      edge.id,
      (edge.sections ?? []).map((section) => [
        section.startPoint,
        ...(section.bendPoints ?? []),
        section.endPoint,
      ]),
    );
  }

  const terminalEvents = new Set(workflow.terminal_events);
  const gateCounts = workflow.gates.reduce<Map<string, number>>((counts, gate) => {
    counts.set(gate.node_id, (counts.get(gate.node_id) ?? 0) + 1);
    return counts;
  }, new Map());

  const nodes = workflow.nodes.map((node) => {
    const waitsFor = splitRuntimeWaitsFor(node.waits_for);
    const decision = decisions[node.id];
    const stateSummary = summarizeRuntimeNodeState({
      decision,
      waitsForAll: waitsFor.allOf,
      waitsForAny: waitsFor.anyOf,
      emits: node.emits,
      isTerminal: node.emits.some((eventName) => terminalEvents.has(eventName)),
    });
    const gatekeeperTone = runtimeDecisionTone(decision);
    const primaryReason = summarizePrimaryReason(decision?.blocked_reasons ?? []);
    const portLayout = portLayouts.get(node.id) ?? { incomingPorts: [], outgoingPorts: [] };

    return {
      id: node.id,
      selected: node.id === selectedNodeId,
      position: positions.get(node.id) ?? { x: RUNTIME_LAYOUT_SPACING.originX, y: RUNTIME_LAYOUT_SPACING.originY },
      style: {
        width: RUNTIME_NODE_WIDTH,
        height: RUNTIME_NODE_HEIGHT,
      },
      data: {
        role: node.role,
        gatekeeperState: decision?.state ?? 'unknown',
        gatekeeperStateLabel: formatRuntimeStateLabel(decision?.state),
        gatekeeperTone,
        stateSummary,
        primaryReason,
        blockedReasons: decision?.blocked_reasons ?? [],
        emits: node.emits,
        waitsForAll: waitsFor.allOf,
        waitsForAny: waitsFor.anyOf,
        isTerminal: node.emits.some((eventName) => terminalEvents.has(eventName)),
        gateCount: gateCounts.get(node.id) ?? 0,
        incomingPorts: portLayout.incomingPorts,
        outgoingPorts: portLayout.outgoingPorts,
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      type: 'runtime',
    };
  });

  const orderedNodes = nodes
    .slice()
    .sort((left, right) => compareRuntimeNodePositions(left, right, positions));

  return {
    nodes,
    edges: runtimeWorkflowEdges(edgeDescriptors, sectionsByEdgeId, onSelectEdge),
    orderedNodes,
  };
}

function buildRuntimeElkGraph(workflow: RuntimeWorkflow, edgeDescriptors: RuntimeWorkflowEdgeDescriptor[]): any {
  const incomingEdgesByNodeId = new Map<string, RuntimeWorkflowEdgeDescriptor[]>();
  const outgoingEdgesByNodeId = new Map<string, RuntimeWorkflowEdgeDescriptor[]>();
  for (const descriptor of edgeDescriptors) {
    const incomingEdges = incomingEdgesByNodeId.get(descriptor.targetId) ?? [];
    incomingEdges.push(descriptor);
    incomingEdgesByNodeId.set(descriptor.targetId, incomingEdges);
    const outgoingEdges = outgoingEdgesByNodeId.get(descriptor.sourceId) ?? [];
    outgoingEdges.push(descriptor);
    outgoingEdgesByNodeId.set(descriptor.sourceId, outgoingEdges);
  }

  return {
    id: 'root',
    layoutOptions: RUNTIME_ELK_LAYOUT_OPTIONS,
    children: workflow.nodes.map((node) => {
      const incomingEdges = incomingEdgesByNodeId.get(node.id) ?? [];
      const outgoingEdges = outgoingEdgesByNodeId.get(node.id) ?? [];
      return {
        id: node.id,
        width: RUNTIME_NODE_WIDTH,
        height: RUNTIME_NODE_HEIGHT,
        layoutOptions: {
          'elk.portConstraints': 'FIXED_ORDER',
        },
        ports: [
          ...incomingEdges.map((descriptor, index) => ({
            id: descriptor.targetPortId,
            width: 0,
            height: 0,
            layoutOptions: {
              'elk.port.side': 'WEST',
              'elk.port.index': `${index}`,
            },
          })),
          ...outgoingEdges.map((descriptor, index) => ({
            id: descriptor.sourcePortId,
            width: 0,
            height: 0,
            layoutOptions: {
              'elk.port.side': 'EAST',
              'elk.port.index': `${index}`,
            },
          })),
        ],
      };
    }),
    edges: edgeDescriptors.map((descriptor) => ({
      id: descriptor.id,
      sources: [descriptor.sourcePortId],
      targets: [descriptor.targetPortId],
    })),
  };
}

function runtimeFlowNodePortLayouts(
  workflow: RuntimeWorkflow,
  edgeDescriptors: RuntimeWorkflowEdgeDescriptor[],
  layoutNodesById?: Map<string, RuntimeElkLayoutNode>,
): Map<string, { incomingPorts: FlowNodePort[]; outgoingPorts: FlowNodePort[] }> {
  return directedFlowNodePortLayouts(
    workflow.nodes.map((node) => node.id),
    edgeDescriptors,
    RUNTIME_NODE_HEIGHT,
    layoutNodesById,
  );
}

function runtimePortOffsets(count: number): number[] {
  return directedPortOffsets(count, RUNTIME_NODE_HEIGHT);
}

function clampRuntimePortOffset(offset: number): number {
  return clampFlowPortOffset(offset, RUNTIME_NODE_HEIGHT);
}

function runtimeEdgePath(
  sections: XYPosition[][],
  fallback: {
    sourceX: number;
    sourceY: number;
    sourcePosition: Position;
    targetX: number;
    targetY: number;
    targetPosition: Position;
    sourceIndex?: number;
    sourceCount?: number;
    targetIndex?: number;
    targetCount?: number;
  },
): string {
  return directedEdgePath(sections, fallback);
}

function compareRuntimeNodePositions(
  left: Node<RuntimeFlowNodeData>,
  right: Node<RuntimeFlowNodeData>,
  positions: Map<string, { x: number; y: number }>,
): number {
  const leftPosition = positions.get(left.id) ?? { x: 0, y: 0 };
  const rightPosition = positions.get(right.id) ?? { x: 0, y: 0 };
  return (
    leftPosition.x - rightPosition.x ||
    leftPosition.y - rightPosition.y ||
    left.id.localeCompare(right.id)
  );
}

function summarizeRuntimeNodeState(node: {
  decision?: GatekeeperDecision;
  waitsForAll: string[];
  waitsForAny: string[];
  emits: string[];
  isTerminal: boolean;
}): string {
  const stateLabel = formatRuntimeStateLabel(node.decision?.state);
  if (node.decision?.state === 'blocked' && node.decision.blocked_reasons.length > 0) {
    return `${stateLabel} • ${node.decision.blocked_reasons.length} blocker${node.decision.blocked_reasons.length === 1 ? '' : 's'}`;
  }
  if (node.decision?.state === 'needs_review' && node.decision.blocked_reasons.length > 0) {
    return `${stateLabel} • review required`;
  }
  if (node.decision?.state === 'completed') {
    return node.isTerminal ? `${stateLabel} • terminal output emitted` : stateLabel;
  }
  if (node.decision?.state === 'runnable' || node.decision?.state === 'ready') {
    return node.emits.length > 0 ? `${stateLabel} • emits ${node.emits.length}` : stateLabel;
  }
  if (node.decision?.state === 'superseded') {
    return `${stateLabel} • replaced by newer work`;
  }
  const waitParts = [
    node.waitsForAll.length > 0 ? `${node.waitsForAll.length} all` : '',
    node.waitsForAny.length > 0 ? `${node.waitsForAny.length} any` : '',
  ].filter(Boolean);
  const waitSummary = waitParts.length > 0 ? `waits ${waitParts.join(', ')}` : 'ready';
  const emitSummary = node.emits.length > 0 ? `emits ${node.emits.length}` : 'emits none';
  return [waitSummary, emitSummary, node.isTerminal ? 'terminal' : null].filter(Boolean).join(' • ');
}

function formatRuntimeStateLabel(state?: string): string {
  switch (state) {
    case 'runnable':
    case 'ready':
      return 'Runnable';
    case 'blocked':
      return 'Blocked';
    case 'completed':
      return 'Completed';
    case 'needs_review':
      return 'Needs review';
    case 'superseded':
      return 'Superseded';
    default:
      return 'Unknown';
  }
}

function runtimeDecisionTone(
  decision?: GatekeeperDecision,
): 'runnable' | 'blocked' | 'completed' | 'needs_review' | 'superseded' | 'unknown' {
  if (!decision) {
    return 'unknown';
  }
  if (decision.state === 'ready') {
    return 'runnable';
  }
  if (
    decision.state === 'blocked'
    && decision.blocked_reasons.some((reason) => reason.code === 'superseded')
  ) {
    return 'superseded';
  }
  if (
    decision.state === 'needs_review'
    && decision.blocked_reasons.some((reason) => reason.code === 'superseded')
  ) {
    return 'superseded';
  }
  if (
    decision.state === 'runnable'
    || decision.state === 'blocked'
    || decision.state === 'completed'
    || decision.state === 'needs_review'
    || decision.state === 'superseded'
  ) {
    return decision.state;
  }
  return 'unknown';
}

function summarizePrimaryReason(reasons: GatekeeperBlockedReason[]): string | null {
  const reason = reasons[0];
  if (!reason) {
    return null;
  }
  const detail = reason.missing_ref ?? reason.assignment_id ?? reason.gate_id ?? reason.mutation_event_id;
  return detail ? `${formatReasonCode(reason.code)}: ${detail}` : formatReasonCode(reason.code);
}

function formatReasonCode(code: string): string {
  return code.replaceAll('_', ' ');
}

function runtimeReasonTone(code: string): 'blocked' | 'needs_review' | 'superseded' {
  if (code === 'needs_review') {
    return 'needs_review';
  }
  if (code === 'superseded') {
    return 'superseded';
  }
  return 'blocked';
}

function runtimeEventRefSourceId(eventRef: string): string | null {
  const separator = eventRef.indexOf('.');
  return separator > 0 ? eventRef.slice(0, separator) : null;
}

function runtimeEventRefName(eventRef: string): string {
  const separator = eventRef.indexOf('.');
  return separator > 0 ? eventRef.slice(separator + 1) : eventRef;
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
  return computeDirectedNodePositions(nodes, dependencyView, PLANNING_LAYOUT_SPACING);
}

function computeDirectedNodePositions<T extends { id: string }>(
  nodes: T[],
  dependencyView: Array<{ id: string; dependencies: string[] }>,
  spacing: DirectedNodeLayoutSpacing,
  options: DirectedNodeLayoutOptions = {},
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

  const nodesByLevel = new Map<number, T[]>();
  for (const node of nodes) {
    const level = levels.get(node.id) ?? 0;
    const bucket = nodesByLevel.get(level) ?? [];
    bucket.push(node);
    nodesByLevel.set(level, bucket);
  }

  const sortedLevels = [...nodesByLevel.keys()].sort((left, right) => left - right);
  for (const level of sortedLevels) {
    const bucket = nodesByLevel.get(level) ?? [];
    const orderedBucket = bucket
      .slice()
      .sort((left, right) => {
        const leftScore = layoutOrderScore(left.id, level, positions, dependenciesById, order);
        const rightScore = layoutOrderScore(right.id, level, positions, dependenciesById, order);
        return leftScore - rightScore || (order.get(left.id) ?? 0) - (order.get(right.id) ?? 0);
      });
    orderedBucket.forEach((node, row) => {
      positions.set(node.id, {
        x: spacing.originX + level * spacing.columnGap,
        y: spacing.originY + row * spacing.rowGap + Math.max(0, level - 1) * (options.levelStagger ?? 0),
      });
    });
  }

  return positions;
}

function layoutOrderScore(
  nodeId: string,
  level: number,
  positions: Map<string, { x: number; y: number }>,
  dependenciesById: Map<string, string[]>,
  order: Map<string, number>,
): number {
  if (level === 0) {
    return order.get(nodeId) ?? 0;
  }

  const parentYs = (dependenciesById.get(nodeId) ?? [])
    .map((dependencyId) => positions.get(dependencyId)?.y)
    .filter((value): value is number => typeof value === 'number');
  if (parentYs.length === 0) {
    return order.get(nodeId) ?? 0;
  }

  return parentYs.reduce((sum, value) => sum + value, 0) / parentYs.length;
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

function loadMutationWorkbenchPaths(): MutationWorkbenchPaths {
  if (typeof window === 'undefined') {
    return {
      missionPath: deriveMissionPath(DEFAULT_LEDGER_PATH),
      workflowPath: DEFAULT_WORKFLOW_PATH,
      ledgerPath: DEFAULT_LEDGER_PATH,
    };
  }
  const search = new URLSearchParams(window.location.search);
  const storedMissionPath = window.localStorage.getItem('bureauless.missionPath');
  const storedWorkflowPath = window.localStorage.getItem('bureauless.workflowPath');
  const storedLedgerPath = window.localStorage.getItem('bureauless.ledgerPath');
  const ledgerPath = search.get('ledger_path')?.trim() || storedLedgerPath?.trim() || DEFAULT_LEDGER_PATH;
  return {
    missionPath: search.get('mission_path')?.trim() || storedMissionPath?.trim() || deriveMissionPath(ledgerPath),
    workflowPath: search.get('workflow_path')?.trim() || storedWorkflowPath?.trim() || DEFAULT_WORKFLOW_PATH,
    ledgerPath,
  };
}

function deriveMissionPath(ledgerPath: string): string {
  const missionFromLedger = ledgerPath.replace(/\/ledger\.yaml$/, '/mission.yaml');
  return missionFromLedger === ledgerPath ? DEFAULT_MISSION_PATH : missionFromLedger;
}

function normalizeMutationWorkbenchPaths(paths: MutationWorkbenchPaths): MutationWorkbenchPaths {
  const ledgerPath = paths.ledgerPath.trim() || DEFAULT_LEDGER_PATH;
  return {
    missionPath: paths.missionPath.trim() || deriveMissionPath(ledgerPath),
    workflowPath: paths.workflowPath.trim() || DEFAULT_WORKFLOW_PATH,
    ledgerPath,
  };
}

function persistMutationWorkbenchPaths(paths: MutationWorkbenchPaths): void {
  if (typeof window === 'undefined') {
    return;
  }

  const normalized = normalizeMutationWorkbenchPaths(paths);
  window.localStorage.setItem('bureauless.missionPath', normalized.missionPath);
  window.localStorage.setItem('bureauless.workflowPath', normalized.workflowPath);
  window.localStorage.setItem('bureauless.ledgerPath', normalized.ledgerPath);
}

function loadWorkbenchViewMode(): WorkbenchViewMode {
  if (typeof window === 'undefined') {
    return 'planning';
  }

  const search = new URLSearchParams(window.location.search);
  if (search.has('workflow_path') || search.has('ledger_path')) {
    return 'runtime';
  }

  const stored = window.localStorage.getItem(WORKBENCH_VIEW_STORAGE_KEY);
  return stored === 'runtime' ? 'runtime' : 'planning';
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

function persistWorkbenchViewMode(mode: WorkbenchViewMode): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem(WORKBENCH_VIEW_STORAGE_KEY, mode);
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
