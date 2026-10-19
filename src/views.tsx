import { ArrowLeft, ArrowRight, Compass, GitBranch, Layers3, Printer, Sparkles, Trash2 } from 'lucide-react'
import type { Graph, RabbitHoleSummary } from './types'

const dateLabel = (value: string) => new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value))

function MapPreview({ branches }: { branches: number }) {
  const dots = Math.min(Math.max(branches, 1), 6)
  return <div className="map-preview" aria-label={`${branches} first layer branches`}>
    <span className="mini-root" />
    <span className="mini-trunk" />
    <span className="mini-branch mini-branch-a" />
    <span className="mini-branch mini-branch-b" />
    <span className="mini-branch mini-branch-c" />
    {Array.from({ length: dots }, (_, index) => <i className={`mini-dot mini-dot-${index + 1}`} key={index} />)}
    <span className="mini-distant" />
  </div>
}

export function ArchiveView({ holes, onOpen, onDelete, onNew }: {
  holes: RabbitHoleSummary[]
  onOpen: (id: string) => void
  onDelete: (hole: RabbitHoleSummary) => void
  onNew: () => void
}) {
  return <section className="archive-view">
    <div className="archive-intro"><div><div className="eyebrow archive-eyebrow"><span className="eyebrow-line" /> THE FIELD JOURNAL</div><h1>Trails you’ve<br /><em>already taken.</em></h1><p>Every rabbit hole, held open for whenever curiosity circles back.</p></div><button className="archive-new-button" onClick={onNew}><span>Start a new trail</span><ArrowRight size={16} /></button></div>
    <div className="archive-meta"><span>{holes.length.toString().padStart(2, '0')} {holes.length === 1 ? 'EXPLORATION' : 'EXPLORATIONS'}</span><span>STORED ON THIS DEVICE</span></div>
    {holes.length ? <div className="archive-grid">{holes.map((hole, index) => <article className="archive-card" key={hole.id} style={{ animationDelay: `${index * 35}ms` }}>
      <button className="archive-card-main" onClick={() => onOpen(hole.id)}>
        <div className="archive-card-top"><span className="archive-index">TRAIL {String(holes.length - index).padStart(2, '0')}</span><span className="archive-date">{dateLabel(hole.updated_at)}</span></div>
        <MapPreview branches={hole.first_level_branches} />
        <h2>{hole.title}</h2>
        <div className="archive-card-stats"><span><Layers3 size={13} /> {hole.node_count} concepts</span><span><GitBranch size={13} /> {hole.max_depth} deep</span><span>{hole.first_level_branches} first paths</span></div>
        <div className="archive-open-hint">RETURN TO THIS TRAIL <ArrowRight size={13} /></div>
      </button>
      <button className="archive-delete" onClick={() => onDelete(hole)} aria-label={`Delete ${hole.title}`} title="Delete exploration"><Trash2 size={15} /></button>
    </article>)}</div> : <div className="archive-empty"><div className="empty-map"><span /><i /><i /><i /></div><h2>No trails yet.</h2><p>Start with a question. The places you visit will be waiting here.</p><button onClick={onNew}>Begin your first exploration <ArrowRight size={15} /></button></div>}
    <div className="archive-footer"><span>KEEP THE THREAD, NOT JUST THE ANSWER.</span><span>RONIN · YOUR PRIVATE FIELD JOURNAL</span></div>
  </section>
}

export function RecapView({ graph, onBack }: { graph: Graph; onBack: () => void }) {
  const { metrics } = graph
  const stats = [
    { label: 'CONCEPTS MAPPED', value: metrics.node_count.toString().padStart(2, '0'), icon: <Layers3 size={15} /> },
    { label: 'DEEPEST POINT', value: `${metrics.max_depth} layers`, icon: <ArrowRight size={15} /> },
    { label: 'FIRST PATHS', value: metrics.first_level_branches.toString().padStart(2, '0'), icon: <GitBranch size={15} /> },
    { label: 'CONCEPTS VISITED', value: metrics.explored_nodes.toString().padStart(2, '0'), icon: <Compass size={15} /> },
    { label: `UNIQUE SOURCES · ON ${metrics.sourced_nodes} ${metrics.sourced_nodes === 1 ? 'CONCEPT' : 'CONCEPTS'}`, value: metrics.unique_sources.toString().padStart(2, '0'), icon: <Sparkles size={15} /> },
    { label: 'SUBJECT AREAS', value: metrics.domain_count.toString().padStart(2, '0'), icon: <Layers3 size={15} /> },
  ]
  return <section className="recap-view">
    <div className="recap-toolbar"><button className="back-to-map" onClick={onBack}><ArrowLeft size={15} /> Back to map</button><button className="print-button" onClick={() => window.print()}><Printer size={15} /> Save recap as PDF</button></div>
    <div className="recap-paper print-page">
      <div className="recap-masthead"><span>RONIN · FIELD NOTE Nº 01</span><span>AN EXPLORATION</span></div>
      <div className="eyebrow recap-eyebrow"><span className="eyebrow-line" /> YOUR QUESTION, FOLLOWED</div>
      <h1>{graph.question}</h1>
      <p className="recap-lede">A small map of where your curiosity wandered. Every measure below comes from the trail you actually made.</p>
      <div className="recap-stats">{stats.map((item) => <div className="recap-stat" key={item.label}><div className="recap-stat-label">{item.icon}{item.label}</div><strong>{item.value}</strong></div>)}</div>
      <div className="recap-trails">
        <div className="recap-trail-block"><div className="recap-section-title">THE DEEPEST TRAIL <span /></div><div className="deepest-path">{metrics.deepest_path.map((title, index) => <div className="deepest-step" key={`${title}-${index}`}><span className="step-number">{String(index + 1).padStart(2, '0')}</span><span>{title}</span>{index < metrics.deepest_path.length - 1 && <ArrowRight size={13} />}</div>)}</div></div>
        <div className="recap-trail-block branch-highlight"><div className="recap-section-title">MOST EXPLORED BRANCH <span /></div><strong>{metrics.most_explored_branch || 'The trail is just beginning.'}</strong><p>This path held the most visited concepts in this exploration.</p></div>
      </div>
      <div className="recap-domains"><div className="recap-section-title">SUBJECTS CROSSED <span /></div><div className="domain-list">{metrics.domains.length ? metrics.domains.map((domain) => <span key={domain}>{domain}</span>) : <span className="domain-empty">A subject will appear as your map grows.</span>}</div></div>
      <div className="recap-foot"><div className="recap-mark" /><div><span>START WITH A QUESTION.</span><span>FOLLOW YOUR CURIOSITY.</span></div><small>{dateLabel(graph.updated_at)}</small></div>
    </div>
    <div className="recap-export-hint"><span>This recap reflects the saved graph at the time it was opened.</span><button onClick={onBack}>Continue exploring <ArrowRight size={14} /></button></div>
  </section>
}
