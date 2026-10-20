import { memo, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent } from 'react'
import {
  Background, BackgroundVariant, Controls, Handle, MarkerType, MiniMap, Panel, Position,
  ReactFlow, ReactFlowProvider, getBezierPath, useStore, useStoreApi,
  type Edge, type EdgeProps, type Node, type NodeProps,
  useEdgesState, useNodesInitialized, useNodesState, useReactFlow,
} from '@xyflow/react'
import { ArrowRight, ChevronRight, CircleDot, LoaderCircle, Sparkles } from 'lucide-react'
import type { Concept, Graph } from './types'

type ConceptData = {
  concept: Concept
  selected: boolean
  onPath: boolean
  labelled: boolean
  /** Concepts below this one that are not drawn; they are counted on the node instead. */
  hidden: number
  hasChildren: boolean
  collapsed: boolean
  busy: boolean
  onSelect: (concept: Concept) => void
  onToggleCollapse: (id: string) => void
}
// 'concept' renders a full card; 'marker' renders a point with an optional title and hidden-branch count.
type FlowNode = Node<ConceptData, 'concept' | 'marker'>
/** Ask the canvas to unfold a node and bring it and its children into view. */
export type FocusRequest = { nodeId: string; revision: number }
/** Constellation shows the routes taken as markers; Deep Dive gives the focus and its children full cards. */
export type ExplorerView = 'constellation' | 'deep'

// Must match .concept-card in styles.css. Nodes get these as fixed dimensions so layout and
// viewport fitting never wait on (or race with) DOM measurement.
const CARD_WIDTH = 264
const CARD_HEIGHT = 134
const NODE_X_STEP = CARD_WIDTH + 104
const NODE_Y_STEP = CARD_HEIGHT + 20
// A marker's layout box is its dot. The visible hit area and label are sized in screen pixels in CSS (see --zoom).
const MARKER_BOX = 18
const PREVIEW_WIDTH = 272
// Overlay panels sit at the top (depth, view switch), bottom (hint, zoom controls) and left (zoom controls).
// A few extra pixels keep fitted cards clear of the panels' edges.
const FIT_INSET = { top: 64, bottom: 68, left: 60, right: 28 } as const
// The minimap sits in the bottom-right corner once a trail has more than six concepts.
const MINIMAP_RESERVE = 180
// Below this zoom the card text is too small to read, so Deep Dive keeps the focus at this zoom instead of fitting the family.
const READABLE_ZOOM = 0.65
// Markers scale with their own CSS, so the overview can zoom further out than cards can.
// The deepest trail with its deepest explored route is about 2,960 world px wide, which fits the 780 px usable width at about 0.26.
const CONSTELLATION_MIN_ZOOM = 0.25

// Open the hover preview on whichever side of the card has room inside the canvas.
function placePreview(card: HTMLElement) {
  const canvas = card.closest('.react-flow')?.getBoundingClientRect()
  if (!canvas) return
  const rect = card.getBoundingClientRect()
  card.classList.toggle('preview-left', rect.right + PREVIEW_WIDTH + 16 > canvas.right && rect.left - PREVIEW_WIDTH - 16 > canvas.left)
}

function ConceptCard({ data }: NodeProps<FlowNode>) {
  const { concept, selected, onPath, hidden, hasChildren, collapsed, busy, onSelect, onToggleCollapse } = data
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
      <span>{hidden > 0 ? `+${hidden} BEYOND` : hasChildren ? 'TRAIL CONTINUES' : 'POSSIBLE PATH'}</span>
      {hasChildren
        ? <button className="branch-fold nodrag nopan" onClick={(event) => { event.stopPropagation(); onToggleCollapse(concept.id) }} onKeyDown={(event) => event.stopPropagation()} title={collapsed ? 'Show child concepts' : 'Fold child concepts'}><span>{collapsed ? 'SHOW' : 'FOLD'}</span><ChevronRight size={11} className={collapsed ? '' : 'fold-open'} /></button>
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

// A point on the map. Its hit area and text are sized in screen pixels by reading the live zoom, so they stay usable when zoomed out.
// Clicks reach onSelect through React Flow's onNodeClick, and the native button gives keyboard access.
function ConceptMarker({ data }: NodeProps<FlowNode>) {
  const { concept, selected, onPath, labelled, hidden } = data
  const zoom = useStore((state) => state.transform[2])
  return <>
    <Handle type="target" position={Position.Left} className="flow-handle" />
    <button
      type="button"
      className={`concept-marker nopan ${labelled ? 'is-labelled' : ''} ${onPath ? 'on-path' : ''} ${selected ? 'is-selected' : ''} ${concept.explored ? 'was-explored' : ''}`}
      style={{ '--zoom': zoom, '--column': NODE_X_STEP } as CSSProperties}
      aria-label={`${selected ? 'Selected, ' : 'Select '}${concept.title}${hidden > 0 ? `, ${hidden} more beyond` : ''}`}
      title={concept.title}
    >
      <span className="marker-hit"><span className="marker-dot" /></span>
      <span className="marker-label">{concept.title}</span>
      {hidden > 0 && <span className="marker-count">+{hidden}</span>}
    </button>
    <Handle type="source" position={Position.Right} className="flow-handle" />
  </>
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

const nodeTypes = { concept: memo(ConceptCard), marker: memo(ConceptMarker) }
const edgeTypes = { trail: CurvedEdge }

// View and collapse decide what is drawn; the graph data itself is never changed.
function positionGraph(
  graph: Graph,
  selectedId: string | null,
  busyNodeId: string | null,
  collapsed: Set<string>,
  view: ExplorerView,
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
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]))

  // A route is a concept plus its ancestors. The focus route offers its direct children; each explored route
  // (Constellation only) is drawn as a chain, with its siblings counted on each node instead of drawn.
  const routeFrom = (id: string | null, into: Set<string>) => {
    let cursor = id ? nodesById.get(id) : undefined
    while (cursor) {
      into.add(cursor.id)
      cursor = cursor.parent_id ? nodesById.get(cursor.parent_id) : undefined
    }
  }
  const onPathIds = new Set<string>()
  routeFrom(selectedId, onPathIds)
  const routeIds = new Set(onPathIds)
  if (view === 'constellation') {
    for (const node of graph.nodes) if (node.explored) routeFrom(node.id, routeIds)
  }
  const offered = new Set(routeIds)
  for (const id of onPathIds) for (const child of children.get(id) ?? []) offered.add(child.id)

  const shownChildren = (id: string): Concept[] => collapsed.has(id) ? [] : (children.get(id) ?? []).filter((child) => offered.has(child.id))
  const totalBelow = (id: string): number => (children.get(id) ?? []).reduce((sum, child) => sum + 1 + totalBelow(child.id), 0)
  const shownBelow = (id: string): number => shownChildren(id).reduce((sum, child) => sum + 1 + shownBelow(child.id), 0)

  const yById = new Map<string, number>()
  const spanById = new Map<string, { first: number; last: number }>()
  let leafCount = 0
  const assignY = (node: Concept): number => {
    const visibleChildren = shownChildren(node.id)
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

  const edgesOnSelectedPath = new Set<string>()
  let cursor = selectedId ? nodesById.get(selectedId) : undefined
  while (cursor?.parent_id) {
    const parentId = cursor.parent_id
    const edge = graph.edges.find((item) => item.source === parentId && item.target === cursor?.id)
    if (edge) edgesOnSelectedPath.add(edge.id)
    cursor = nodesById.get(parentId)
  }

  const layout = (node: Concept, depth: number): FlowNode[] => {
    const descendants = shownChildren(node.id)
    // Deep Dive: the focus and its immediate children are cards. Constellation is all markers, so its text stays readable at any zoom.
    const isCard = view === 'deep' && (node.id === selectedId || node.parent_id === selectedId)
    const onPath = onPathIds.has(node.id)
    // Titles are shown for the route being followed and for the starting question. Explored routes are marked by their dots,
    // and their titles appear on hover, so labels never collide when the map is zoomed out.
    const labelled = onPath || node.parent_id === null
    const hidden = totalBelow(node.id) - shownBelow(node.id)
    const top = (yById.get(node.id) ?? 0) - centerY
    const data: ConceptData = {
      concept: node,
      selected: node.id === selectedId,
      onPath,
      labelled,
      hidden,
      hasChildren: (children.get(node.id)?.length ?? 0) > 0,
      collapsed: collapsed.has(node.id),
      busy: node.id === busyNodeId,
      onSelect,
      onToggleCollapse,
    }
    const current: FlowNode = isCard ? {
      id: node.id,
      type: 'concept',
      position: { x: depth * NODE_X_STEP, y: top },
      width: CARD_WIDTH,
      height: CARD_HEIGHT,
      data,
      draggable: false,
    } : {
      id: node.id,
      type: 'marker',
      position: {
        x: depth * NODE_X_STEP + (CARD_WIDTH - MARKER_BOX) / 2,
        y: top + (CARD_HEIGHT - MARKER_BOX) / 2,
      },
      width: MARKER_BOX,
      height: MARKER_BOX,
      data,
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
  const store = useStoreApi()
  const nodesInitialized = useNodesInitialized()
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [fitFocus, setFitFocus] = useState<{ nodeId: string; revision: number } | null>(null)
  const fitRevision = useRef(0)
  const [initialFitComplete, setInitialFitComplete] = useState(false)
  const lastAppliedFitRevision = useRef(0)
  const [view, setView] = useState<ExplorerView>('deep')
  const lastFocusId = useRef<string | null>(selectedId)
  // Switching to Constellation must fit the whole trail, but only after the new layout has been applied.
  const fitWholeOnNextLayout = useRef(false)
  // Deep Dive family framing reserves room for the minimap once a trail has more than six concepts.
  const familyRightInset = FIT_INSET.right + (graph.nodes.length > 6 ? MINIMAP_RESERVE : 0)
  const familyPadding = useMemo(() => ({
    top: `${FIT_INSET.top}px` as const,
    bottom: `${FIT_INSET.bottom}px` as const,
    left: `${FIT_INSET.left}px` as const,
    right: `${familyRightInset}px` as const,
  }), [familyRightInset])

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
    () => positionGraph(graph, selectedId, busyNodeId, collapsed, view, onSelect, toggleCollapse),
    [graph, selectedId, busyNodeId, collapsed, view, onSelect, toggleCollapse],
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

  // Frame a focus and the children drawn beneath it, inside the area the overlays leave free.
  // If the family cannot fit at a readable zoom, keep the focus centred at that zoom instead of shrinking everything.
  // Reads the store at call time, so it always sees the layout React Flow has applied.
  const frameFamily = useCallback((focusId: string, duration: number) => {
    const byId = new Map(flow.getNodes().map((node) => [node.id, node]))
    const focusNode = byId.get(focusId)
    if (!focusNode) return
    const family = [focusNode, ...graph.nodes
      .filter((node) => node.parent_id === focusId)
      .map((node) => byId.get(node.id))
      .filter((node): node is FlowNode => !!node)]
    const left = Math.min(...family.map((node) => node.position.x))
    const top = Math.min(...family.map((node) => node.position.y))
    const right = Math.max(...family.map((node) => node.position.x + (node.width ?? CARD_WIDTH)))
    const bottom = Math.max(...family.map((node) => node.position.y + (node.height ?? CARD_HEIGHT)))
    const { width, height } = store.getState()
    const fitZoom = Math.min(
      (width - FIT_INSET.left - familyRightInset) / (right - left),
      (height - FIT_INSET.top - FIT_INSET.bottom) / (bottom - top),
    )
    if (fitZoom >= READABLE_ZOOM) {
      void flow.fitView({ nodes: family.map((node) => ({ id: node.id })), padding: familyPadding, minZoom: READABLE_ZOOM, maxZoom: 1, duration })
    } else {
      void flow.setCenter(focusNode.position.x + (focusNode.width ?? CARD_WIDTH) / 2, focusNode.position.y + (focusNode.height ?? CARD_HEIGHT) / 2, { zoom: READABLE_ZOOM, duration })
    }
  }, [flow, store, graph.nodes, familyRightInset, familyPadding])

  // Whole-trail framing, computed directly from node positions. Constellation needs the trail to stay on screen even when
  // it is wider than the minimum zoom allows, and React Flow's fitView centred such a trail past its left edge.
  const frameTrail = useCallback((duration: number) => {
    const current = flow.getNodes()
    if (!current.length) return
    const left = Math.min(...current.map((node) => node.position.x))
    const top = Math.min(...current.map((node) => node.position.y))
    const right = Math.max(...current.map((node) => node.position.x + (node.width ?? CARD_WIDTH)))
    const bottom = Math.max(...current.map((node) => node.position.y + (node.height ?? CARD_HEIGHT)))
    const { width, height } = store.getState()
    const usableWidth = width - FIT_INSET.left - FIT_INSET.right
    const usableHeight = height - FIT_INSET.top - FIT_INSET.bottom
    const zoom = Math.min(1, Math.max(CONSTELLATION_MIN_ZOOM, Math.min(usableWidth / (right - left), usableHeight / (bottom - top))))
    void flow.setViewport({
      x: FIT_INSET.left + (usableWidth - (right - left) * zoom) / 2 - left * zoom,
      y: FIT_INSET.top + (usableHeight - (bottom - top) * zoom) / 2 - top * zoom,
      zoom,
    }, { duration })
  }, [flow, store])

  useEffect(() => {
    if (!nodesInitialized || nodes.length === 0) return
    if (!initialFitComplete) {
      const root = graph.nodes.find((node) => node.parent_id === null)
      if (root) {
        // Wait a frame so React Flow's store holds the nodes before measuring the viewport.
        requestAnimationFrame(() => {
          frameFamily(root.id, 0)
          setInitialFitComplete(true)
        })
      }
      return
    }
    if (fitWholeOnNextLayout.current) {
      // The new layout reaches React Flow's store one frame after this effect runs; fitting now would frame the old layout.
      fitWholeOnNextLayout.current = false
      requestAnimationFrame(() => frameTrail(400))
      return
    }
    if (fitFocus && fitFocus.revision !== lastAppliedFitRevision.current) {
      lastAppliedFitRevision.current = fitFocus.revision
      const focusId = fitFocus.nodeId
      // Same timing as the whole-trail fit: wait a frame so React Flow's store holds the new nodes.
      requestAnimationFrame(() => {
        if (view === 'deep') frameFamily(focusId, 380)
        else frameTrail(380)
      })
    }
  }, [nodesInitialized, nodes, graph.nodes, fitFocus, initialFitComplete, frameFamily, frameTrail, flow, view])

  // In Deep Dive, choosing a different concept moves the camera to its family. Constellation keeps its framing.
  useEffect(() => {
    const previous = lastFocusId.current
    lastFocusId.current = selectedId
    if (!initialFitComplete || view !== 'deep' || !selectedId || selectedId === previous) return
    requestFit(selectedId)
  }, [selectedId, view, initialFitComplete, requestFit])

  const handleNodeClick = useCallback((_event: ReactMouseEvent, node: FlowNode) => onSelect(node.data.concept), [onSelect])
  const miniColor = useCallback((node: Node) => (node.id === selectedId ? '#dc7656' : '#a7a080'), [selectedId])
  const fitWholeTrail = useCallback(() => {
    frameTrail(400)
  }, [frameTrail])
  const changeView = useCallback((next: ExplorerView) => {
    if (next === view) return
    setView(next)
    if (next === 'deep') {
      if (selectedId) requestFit(selectedId)
    } else {
      fitWholeOnNextLayout.current = true
    }
  }, [view, selectedId, requestFit])
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
    nodesFocusable={false}
    minZoom={0.25}
    maxZoom={1.8}
    proOptions={{ hideAttribution: true }}
    defaultEdgeOptions={{ type: 'trail' }}
  >
    <Background variant={BackgroundVariant.Dots} gap={27} size={1} color="#58584c" />
    <Controls showInteractive={false} position="bottom-left" />
    {graph.nodes.length > 6 && <MiniMap nodeColor={miniColor} maskColor="rgba(20, 21, 19, .73)" className="ronin-minimap" position="bottom-right" style={{ width: 150, height: 96 }} pannable zoomable />}
    <Panel position="top-center"><div className="view-switch" role="group" aria-label="Map view">
      <button type="button" className={view === 'constellation' ? 'is-active' : ''} aria-pressed={view === 'constellation'} onClick={() => changeView('constellation')}>Constellation</button>
      <button type="button" className={view === 'deep' ? 'is-active' : ''} aria-pressed={view === 'deep'} onClick={() => changeView('deep')}>Deep dive</button>
    </div></Panel>
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
