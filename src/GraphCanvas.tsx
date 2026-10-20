import { memo, useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import {
  Background, BackgroundVariant, Controls, Handle, MarkerType, MiniMap, Panel, Position,
  ReactFlow, ReactFlowProvider, getBezierPath,
  type Edge, type EdgeProps, type Node, type NodeProps,
  useEdgesState, useNodesInitialized, useNodesState, useReactFlow,
} from '@xyflow/react'
import { ArrowRight, ChevronRight, CircleDot, LoaderCircle, Sparkles } from 'lucide-react'
import type { Concept, Graph } from './types'

type ConceptData = {
  concept: Concept
  selected: boolean
  onPath: boolean
  hasChildren: boolean
  childCount: number
  collapsed: boolean
  busy: boolean
  onSelect: (concept: Concept) => void
  onToggleCollapse: (id: string) => void
}
type FlowNode = Node<ConceptData, 'concept'>
/** Ask the canvas to unfold a node and bring it and its children into view. */
export type FocusRequest = { nodeId: string; revision: number }

// Must match .concept-card in styles.css. Nodes get these as fixed dimensions so layout and
// viewport fitting never wait on (or race with) DOM measurement.
const CARD_WIDTH = 264
const CARD_HEIGHT = 134
const NODE_X_STEP = CARD_WIDTH + 104
const NODE_Y_STEP = CARD_HEIGHT + 20
const PREVIEW_WIDTH = 272
// Keep fitted nodes clear of the overlay panels (depth/centre at the top, hint at the bottom, zoom controls on the left).
const FIT_PADDING = { top: '56px', bottom: '60px', left: '56px', right: '28px' } as const

// Open the hover preview on whichever side of the card has room inside the canvas.
function placePreview(card: HTMLElement) {
  const canvas = card.closest('.react-flow')?.getBoundingClientRect()
  if (!canvas) return
  const rect = card.getBoundingClientRect()
  card.classList.toggle('preview-left', rect.right + PREVIEW_WIDTH + 16 > canvas.right && rect.left - PREVIEW_WIDTH - 16 > canvas.left)
}

function ConceptCard({ data }: NodeProps<FlowNode>) {
  const { concept, selected, onPath, hasChildren, childCount, collapsed, busy, onSelect, onToggleCollapse } = data
  const previewId = `preview-${concept.id}`
  return <div
    className={`concept-card nopan ${concept.parent_id === null ? 'root-card' : ''} ${selected ? 'is-selected' : ''} ${onPath && !selected ? 'on-path' : ''} ${concept.explored ? 'was-explored' : ''}`}
    role="button"
    aria-label={`Select ${concept.title}`}
    aria-describedby={previewId}
    tabIndex={0}
    onMouseEnter={(event) => placePreview(event.currentTarget)}
    onFocus={(event) => placePreview(event.currentTarget)}
    onKeyDown={(event) => {
      if (event.target !== event.currentTarget) return
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        event.stopPropagation()
        onSelect(concept)
      }
    }}
  >
    <Handle type="target" position={Position.Left} className="flow-handle" />
    <div className="concept-node-top">
      <span className="concept-domain" title={concept.domain}><i />{concept.domain}</span>
      {busy ? <LoaderCircle size={14} className="spin node-pulse" /> : concept.parent_id === null ? <CircleDot size={14} className="root-symbol" /> : concept.explored ? <span className="explored-mark">✓</span> : <Sparkles size={13} className="new-idea" />}
    </div>
    <div className="concept-title">{concept.title}</div>
    <div className="concept-summary">{concept.summary}</div>
    <div className="concept-node-footer">
      <span>{hasChildren ? 'TRAIL CONTINUES' : 'POSSIBLE PATH'}</span>
      {hasChildren
        ? <button className="branch-fold nodrag nopan" onClick={(event) => { event.stopPropagation(); onToggleCollapse(concept.id) }} onKeyDown={(event) => event.stopPropagation()} title={collapsed ? 'Show child concepts' : 'Fold child concepts'}><span>{collapsed ? `SHOW ${childCount}` : 'FOLD'}</span><ChevronRight size={11} className={collapsed ? '' : 'fold-open'} /></button>
        : <ArrowRight size={12} />}
    </div>
    <Handle type="source" position={Position.Right} className="flow-handle" />
    <div id={previewId} className="node-preview" role="tooltip">
      <div className="preview-label">{concept.domain}{concept.explored ? ' · EXPLORED' : ' · UNEXPLORED'}</div>
      <strong>{concept.title}</strong>
      <p>{concept.summary}</p>
      <p className="preview-why">{concept.connection_reason}</p>
      <span>Follow: {concept.exploration_question}</span>
    </div>
  </div>
}

function CurvedEdge(props: EdgeProps) {
  const [path] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
    curvature: 0.38,
  })
  return <path d={path} className={`trail-edge ${props.selected ? 'trail-edge-selected' : ''}`} style={props.style} markerEnd={props.markerEnd} />
}

const nodeTypes = { concept: memo(ConceptCard) }
const edgeTypes = { trail: CurvedEdge }

function positionGraph(
  graph: Graph,
  selectedId: string | null,
  busyNodeId: string | null,
  collapsed: Set<string>,
  onSelect: (concept: Concept) => void,
  onToggleCollapse: (id: string) => void,
): { nodes: FlowNode[]; edges: Edge[] } {
  const children = new Map<string, Concept[]>()
  for (const node of graph.nodes) {
    if (node.parent_id) children.set(node.parent_id, [...(children.get(node.parent_id) ?? []), node])
  }
  for (const list of children.values()) {
    list.sort((a, b) => a.created_at.localeCompare(b.created_at) || a.title.localeCompare(b.title) || a.id.localeCompare(b.id))
  }

  const root = graph.nodes.find((node) => node.parent_id === null)
  if (!root) return { nodes: [], edges: [] }

  const yById = new Map<string, number>()
  const spanById = new Map<string, { first: number; last: number }>()
  let leafCount = 0
  const assignY = (node: Concept): number => {
    const visibleChildren = collapsed.has(node.id) ? [] : children.get(node.id) ?? []
    let first: number
    let last: number
    if (visibleChildren.length) {
      visibleChildren.forEach(assignY)
      first = spanById.get(visibleChildren[0].id)!.first
      last = spanById.get(visibleChildren[visibleChildren.length - 1].id)!.last
    } else {
      first = last = leafCount++ * NODE_Y_STEP
    }
    const y = (first + last) / 2
    yById.set(node.id, y)
    spanById.set(node.id, { first, last })
    return y
  }
  assignY(root)
  const centerY = Math.max(0, (leafCount - 1) * NODE_Y_STEP / 2)

  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]))
  const nodesOnSelectedPath = new Set<string>()
  const edgesOnSelectedPath = new Set<string>()
  let cursor = selectedId ? nodesById.get(selectedId) : undefined
  while (cursor) {
    nodesOnSelectedPath.add(cursor.id)
    const parentId = cursor.parent_id
    const edge = parentId ? graph.edges.find((item) => item.source === parentId && item.target === cursor?.id) : undefined
    if (edge) edgesOnSelectedPath.add(edge.id)
    cursor = parentId ? nodesById.get(parentId) : undefined
  }

  const layout = (node: Concept, depth: number): FlowNode[] => {
    const descendants = collapsed.has(node.id) ? [] : children.get(node.id) ?? []
    const current: FlowNode = {
      id: node.id,
      type: 'concept',
      position: { x: depth * NODE_X_STEP, y: (yById.get(node.id) ?? 0) - centerY },
      width: CARD_WIDTH,
      height: CARD_HEIGHT,
      data: {
        concept: node,
        selected: node.id === selectedId,
        onPath: nodesOnSelectedPath.has(node.id),
        hasChildren: (children.get(node.id)?.length ?? 0) > 0,
        childCount: children.get(node.id)?.length ?? 0,
        collapsed: collapsed.has(node.id),
        busy: node.id === busyNodeId,
        onSelect,
        onToggleCollapse,
      },
      draggable: false,
    }
    return [current, ...descendants.flatMap((child) => layout(child, depth + 1))]
  }

  const nodes = layout(root, 0)
  const visibleIds = new Set(nodes.map((node) => node.id))
  const edges: Edge[] = graph.edges
    .filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
    .map((edge) => {
      const onPath = edgesOnSelectedPath.has(edge.id)
      const stroke = onPath ? '#d97857' : '#858373'
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: 'trail',
        style: { stroke, strokeWidth: onPath ? 2.1 : 1.5, opacity: onPath ? 0.98 : 0.82 },
        markerEnd: { type: MarkerType.ArrowClosed, color: stroke },
        data: { label: edge.relationship_note },
      }
    })
  return { nodes, edges }
}

function Canvas({ graph, selectedId, busyNodeId, focus, onSelect, onExpand }: { graph: Graph; selectedId: string | null; busyNodeId: string | null; focus: FocusRequest | null; onSelect: (concept: Concept) => void; onExpand?: () => void }) {
  const flow = useReactFlow<FlowNode>()
  const nodesInitialized = useNodesInitialized()
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [fitFocus, setFitFocus] = useState<{ nodeId: string; revision: number } | null>(null)
  const fitRevision = useRef(0)
  const [initialFitComplete, setInitialFitComplete] = useState(false)
  const lastAppliedFitRevision = useRef(0)

  const requestFit = useCallback((nodeId: string) => {
    fitRevision.current += 1
    setFitFocus({ nodeId, revision: fitRevision.current })
  }, [])

  const toggleCollapse = useCallback((id: string) => {
    const isCollapsing = !collapsed.has(id)
    if (isCollapsing && selectedId && selectedId !== id) {
      const byId = new Map(graph.nodes.map((node) => [node.id, node]))
      let current = byId.get(selectedId)
      while (current?.parent_id) {
        if (current.parent_id === id) {
          const branch = byId.get(id)
          if (branch) onSelect(branch)
          break
        }
        current = byId.get(current.parent_id)
      }
    }
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
    requestFit(id)
  }, [collapsed, graph.nodes, selectedId, onSelect, requestFit])

  const layout = useMemo(
    () => positionGraph(graph, selectedId, busyNodeId, collapsed, onSelect, toggleCollapse),
    [graph, selectedId, busyNodeId, collapsed, onSelect, toggleCollapse],
  )
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(layout.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(layout.edges)

  useEffect(() => {
    setNodes(layout.nodes)
    setEdges(layout.edges)
  }, [layout, setNodes, setEdges])

  // Every expansion (new or reused children) unfolds the node and brings its children into view.
  useEffect(() => {
    if (!focus) return
    setCollapsed((current) => {
      if (!current.has(focus.nodeId)) return current
      const next = new Set(current)
      next.delete(focus.nodeId)
      return next
    })
    requestFit(focus.nodeId)
  }, [focus, requestFit])

  // Fit a parent together with its visible children. Nodes carry fixed dimensions, so the bounds are
  // known as soon as React Flow has the nodes; nodesInitialized only guards the very first render.
  const fitFamily = useCallback((parentId: string, duration: number) => {
    const ids = new Set(nodes.map((node) => node.id))
    const family = [parentId, ...graph.nodes.filter((node) => node.parent_id === parentId).map((node) => node.id)]
      .filter((id) => ids.has(id))
      .map((id) => ({ id }))
    if (!family.length) return Promise.resolve(false)
    return flow.fitView({ nodes: family, padding: FIT_PADDING, minZoom: 0.45, maxZoom: 1, duration })
  }, [nodes, graph.nodes, flow])

  useEffect(() => {
    if (!nodesInitialized || nodes.length === 0) return
    if (!initialFitComplete) {
      const root = graph.nodes.find((node) => node.parent_id === null)
      if (root) void fitFamily(root.id, 0).then(() => setInitialFitComplete(true))
      return
    }
    if (fitFocus && fitFocus.revision !== lastAppliedFitRevision.current) {
      lastAppliedFitRevision.current = fitFocus.revision
      void fitFamily(fitFocus.nodeId, 380)
    }
  }, [nodesInitialized, nodes, graph.nodes, fitFocus, initialFitComplete, fitFamily])

  const handleNodeClick = useCallback((_event: ReactMouseEvent, node: FlowNode) => onSelect(node.data.concept), [onSelect])
  const miniColor = useCallback((node: Node) => (node.id === selectedId ? '#dc7656' : '#a7a080'), [selectedId])
  const fitWholeTrail = useCallback(() => {
    void flow.fitView({ padding: FIT_PADDING, minZoom: 0.2, maxZoom: 1, duration: 400 })
  }, [flow])
  const selected = graph.nodes.find((node) => node.id === selectedId)
  const selectedHasChildren = !!selected && graph.nodes.some((node) => node.parent_id === selected.id)

  return <ReactFlow
    nodes={nodes}
    edges={edges}
    nodeTypes={nodeTypes}
    edgeTypes={edgeTypes}
    onNodesChange={onNodesChange}
    onEdgesChange={onEdgesChange}
    onNodeClick={handleNodeClick}
    nodesDraggable={false}
    nodesConnectable={false}
    minZoom={0.25}
    maxZoom={1.8}
    proOptions={{ hideAttribution: true }}
    defaultEdgeOptions={{ type: 'trail' }}
  >
    <Background variant={BackgroundVariant.Dots} gap={27} size={1} color="#58584c" />
    <Controls showInteractive={false} position="bottom-left" />
    {graph.nodes.length > 6 && <MiniMap nodeColor={miniColor} maskColor="rgba(20, 21, 19, .73)" className="ronin-minimap" position="bottom-right" style={{ width: 150, height: 96 }} pannable zoomable />}
    <Panel position="top-right"><button className="canvas-fit" onClick={fitWholeTrail}>Center trail</button></Panel>
    <Panel position="top-left"><div className="canvas-depth"><span>DEPTH</span><strong>{graph.metrics.max_depth.toString().padStart(2, '0')}</strong></div></Panel>
    <Panel position="bottom-center" className={onExpand && selected && !selectedHasChildren && busyNodeId !== selected.id ? '' : 'pass-through'}>{onExpand && selected && !selectedHasChildren && busyNodeId !== selected.id
      ? <button className="canvas-expand-hint" onClick={onExpand}>FOLLOW “{selected.title}” <ArrowRight size={12} /></button>
      : <span className="canvas-expand-hint is-hint">HOVER TO PREVIEW · CLICK TO OPEN</span>}</Panel>
  </ReactFlow>
}

export function ExplorerCanvas(props: { graph: Graph; selectedId: string | null; busyNodeId: string | null; focus: FocusRequest | null; onSelect: (concept: Concept) => void; onExpand?: () => void }) {
  return <ReactFlowProvider><Canvas {...props} /></ReactFlowProvider>
}
