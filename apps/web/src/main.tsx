import '@xyflow/react/dist/style.css';
import './styles.css';

import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { Background, Controls, ReactFlow, type Edge, type Node } from '@xyflow/react';
import { CheckCircle2, GitBranch, Moon, RefreshCcw, Sun, Workflow } from 'lucide-react';
import { StrictMode, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';

import { fetchDag, fetchPrompt, fetchRuns, fetchState, type NodeState, type TaskNode } from './api/client';
import { type ThemeMode, useThemeMode } from './theme/theme';

const queryClient = new QueryClient();

function App() {
  return (
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <Workbench />
      </QueryClientProvider>
    </StrictMode>
  );
}

function Workbench() {
  const dag = useQuery({ queryKey: ['dag'], queryFn: fetchDag });
  const state = useQuery({ queryKey: ['state'], queryFn: fetchState });
  const runs = useQuery({ queryKey: ['runs'], queryFn: fetchRuns });
  const [selectedId, setSelectedId] = useState('baseline-inventory');
  const { mode, setMode } = useThemeMode();

  const selectedNode = dag.data?.nodes.find((node) => node.id === selectedId) ?? dag.data?.nodes[0];
  const flowNodes = useMemo<Node[]>(() => {
    const nodes = dag.data?.nodes ?? [];
    return nodes.map((node, index) => {
      const column = node.dependencies.length === 0 ? 0 : node.id === 'integration-review' ? 2 : 1;
      const row = column === 1 ? index - 1 : 0;
      const nodeState = state.data?.states[node.id] ?? 'blocked';
      return {
        id: node.id,
        position: { x: 80 + column * 300, y: 120 + row * 150 },
        data: {
          label: (
            <div className={`flow-node ${nodeState} risk-${node.risk_level}`}>
              <strong>{node.title}</strong>
              <span>{node.recommended_model}</span>
              <small>{node.review_gate}</small>
            </div>
          ),
        },
        type: 'default',
      };
    });
  }, [dag.data, state.data]);

  const flowEdges = useMemo<Edge[]>(
    () =>
      (dag.data?.edges ?? []).map((edge) => ({
        ...edge,
        animated: true,
        className: 'flow-edge',
      })),
    [dag.data],
  );

  return (
    <div className="app-shell">
      <Toolbar mode={mode} setMode={setMode} refetch={() => void Promise.all([dag.refetch(), state.refetch(), runs.refetch()])} />
      <main className="workspace">
        <aside className="sidebar">
          <div className="pane-title"><Workflow size={16} /> DAG</div>
          <div className="file-pill">examples/optimization_dag.yaml</div>
          <div className="filter-row">
            <span>ready</span>
            <span>blocked</span>
            <span>needs review</span>
          </div>
          <nav className="node-list">
            {(dag.data?.nodes ?? []).map((node) => (
              <button
                key={node.id}
                className={node.id === selectedNode?.id ? 'node-item selected' : 'node-item'}
                onClick={() => setSelectedId(node.id)}
              >
                <span>{node.title}</span>
                <small className={state.data?.states[node.id] ?? 'blocked'}>{state.data?.states[node.id] ?? 'blocked'}</small>
              </button>
            ))}
          </nav>
        </aside>
        <section className="graph-pane">
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            fitView
            onNodeClick={(_, node) => setSelectedId(node.id)}
          >
            <Background gap={18} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </section>
        <Inspector node={selectedNode} state={selectedNode ? state.data?.states[selectedNode.id] : undefined} />
      </main>
      <RunTimeline runs={runs.data?.runs ?? []} />
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

function Inspector({ node, state }: { node?: TaskNode; state?: NodeState }) {
  const prompt = useQuery({
    queryKey: ['prompt', node?.id],
    queryFn: () => fetchPrompt(node?.id ?? ''),
    enabled: Boolean(node?.id),
  });

  if (!node) {
    return <aside className="inspector">No node selected</aside>;
  }

  return (
    <aside className="inspector">
      <div className="pane-title">Node Inspector</div>
      <h2>{node.id}</h2>
      <div className="badge-row">
        <span className={`badge risk-${node.risk_level}`}>risk: {node.risk_level}</span>
        <span className="badge">{node.recommended_model}</span>
        <span className="badge">{node.review_gate}</span>
        <span className={`badge ${state ?? 'blocked'}`}>{state ?? 'blocked'}</span>
      </div>
      <section>
        <h3>Goal</h3>
        <p>{node.goal}</p>
      </section>
      <DetailList title="Acceptance Criteria" items={node.acceptance_criteria} />
      <DetailList title="Target Files" items={node.target_files} />
      <DetailList title="Do Not" items={node.do_not} />
      <section>
        <h3>Prompt Preview</h3>
        <pre>{prompt.data?.prompt ?? 'Loading prompt...'}</pre>
      </section>
    </aside>
  );
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

function RunTimeline({ runs }: { runs: Array<Record<string, unknown>> }) {
  return (
    <footer className="timeline">
      <div className="pane-title">Runs</div>
      {runs.length === 0 ? (
        <span className="empty">No run records yet.</span>
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

createRoot(document.getElementById('root')!).render(<App />);
