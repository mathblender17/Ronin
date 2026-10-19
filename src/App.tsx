import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Archive, ArrowDownRight, ArrowLeft, ArrowRight, BookOpen, ChevronDown,
  Compass, ExternalLink, GitBranch, LoaderCircle, Menu, MoreHorizontal,
  Network, Plus, Search, Sparkles, Trash2, X,
} from 'lucide-react'
import { api } from './api'
import { ArchiveView, RecapView } from './views'
import { ExplorerCanvas, type FocusRequest } from './GraphCanvas'
import type { Concept, Graph, RabbitHoleSummary } from './types'

type Page = 'start' | 'explore' | 'archive' | 'recap'
const EXAMPLES = ['Why do humans seek power?', 'How did maps change the way we think?', 'What makes a memory feel real?']

export default function App() {
  const [page, setPage] = useState<Page>('start')
  const [graph, setGraph] = useState<Graph | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [holes, setHoles] = useState<RabbitHoleSummary[]>([])
  const [question, setQuestion] = useState('')
  const [direction, setDirection] = useState('')
  const [busy, setBusy] = useState(false)
  const [busyNodeId, setBusyNodeId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [aiConfigured, setAiConfigured] = useState(true)
  const [mobileNav, setMobileNav] = useState(false)
  const [mobileDetail, setMobileDetail] = useState(false)
  const [search, setSearch] = useState('')
  const [expandFocus, setExpandFocus] = useState<FocusRequest | null>(null)

  const selected = graph?.nodes.find((node) => node.id === selectedId) ?? null
  const children = useMemo(() => graph?.nodes.filter((node) => node.parent_id === selected?.id) ?? [], [graph, selected?.id])
  const parentById = useMemo(() => new Map((graph?.nodes ?? []).map((node) => [node.id, node])), [graph])

  const refreshArchive = useCallback(async () => {
    try { setHoles(await api.list()) } catch (err) { setError(err instanceof Error ? err.message : 'Could not load the archive.') }
  }, [])

  useEffect(() => {
    refreshArchive()
    api.health().then((data) => setAiConfigured(data.ai_configured)).catch(() => setAiConfigured(false))
  }, [refreshArchive])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n') {
        event.preventDefault()
        newHole()
      } else if (event.key === 'Escape') {
        setMobileNav(false)
        setMobileDetail(false)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const openHole = useCallback(async (id: string) => {
    setError('')
    setBusy(true)
    try {
      const loaded = await api.get(id)
      setGraph(loaded)
      setSelectedId((current) => loaded.nodes.some((node) => node.id === current) ? current : loaded.nodes[0]?.id ?? null)
      setPage('explore')
      setMobileNav(false)
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not open this rabbit hole.') }
    finally { setBusy(false) }
  }, [])

  const newHole = () => {
    setGraph(null)
    setSelectedId(null)
    setQuestion('')
    setError('')
    setDirection('')
    setPage('start')
    setMobileNav(false)
  }

  const createHole = async (value = question) => {
    const clean = value.trim()
    if (!clean) { setError('Give your curiosity a starting point.'); return }
    setBusy(true)
    setError('')
    try {
      const created = await api.create(clean)
      setGraph(created)
      setSelectedId(created.nodes[0]?.id ?? null)
      setPage('explore')
      setQuestion('')
      await refreshArchive()
    } catch (err) { setError(err instanceof Error ? err.message : 'The exploration could not start. Please retry.') }
    finally { setBusy(false) }
  }

  const selectNode = useCallback(async (node: Concept) => {
    setSelectedId(node.id)
    setMobileDetail(true)
    setDirection('')
    if (!graph || node.explored) return
    try {
      const updated = await api.visit(graph.id, node.id)
      setGraph(updated)
      await refreshArchive()
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not save this visit.') }
  }, [graph, refreshArchive])

  const expandSelected = useCallback(async (followup?: string) => {
    if (!graph || !selected || busyNodeId) return
    setBusyNodeId(selected.id)
    setError('')
    try {
      await api.expand(graph.id, selected.id, followup?.trim() || undefined)
      const updated = await api.get(graph.id)
      setGraph(updated)
      setSelectedId(selected.id)
      setExpandFocus((current) => ({ nodeId: selected.id, revision: (current?.revision ?? 0) + 1 }))
      setDirection('')
      await refreshArchive()
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not open this path. Your graph is saved; retry when ready.') }
    finally { setBusyNodeId(null) }
  }, [graph, selected, busyNodeId, refreshArchive])

  const deleteHole = async (hole: RabbitHoleSummary) => {
    if (!window.confirm(`Delete “${hole.title}” and its entire exploration graph? This cannot be undone.`)) return
    try {
      await api.remove(hole.id)
      if (graph?.id === hole.id) newHole()
      await refreshArchive()
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not delete this rabbit hole.') }
  }

  const breadcrumb = useMemo(() => {
    if (!selected) return []
    const path: Concept[] = []
    let node: Concept | undefined = selected
    while (node) {
      path.unshift(node)
      node = node.parent_id ? parentById.get(node.parent_id) : undefined
    }
    return path
  }, [selected, parentById])

  const filteredHoles = holes.filter((hole) => `${hole.title} ${hole.question}`.toLowerCase().includes(search.toLowerCase()))

  return (
    <div className={`app-shell ${mobileNav ? 'nav-open' : ''} ${mobileDetail ? 'detail-open' : ''}`}>
      <button className="mobile-scrim" aria-label="Close navigation" onClick={() => { setMobileNav(false); setMobileDetail(false) }} />
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand-mark"><span /></div>
          <div><div className="brand-name">ronin<span>.</span></div><div className="brand-caption">THE QUESTION IS A MAP</div></div>
          <button className="icon-button mobile-close" onClick={() => setMobileNav(false)} aria-label="Close menu"><X size={17} /></button>
        </div>

        <button className="new-hole-button" onClick={newHole}><Plus size={16} strokeWidth={2.2} /><span>New rabbit hole</span><kbd>Ctrl N</kbd></button>

        <nav className="side-nav" aria-label="Main navigation">
          <button className={page === 'archive' ? 'nav-item active' : 'nav-item'} onClick={() => { setPage('archive'); setMobileNav(false) }}><Archive size={16} /><span>Archive</span><span className="nav-count">{holes.length}</span></button>
          {graph && <button className={page === 'recap' ? 'nav-item active' : 'nav-item'} onClick={() => { setPage('recap'); setMobileNav(false) }}><BookOpen size={16} /><span>Field notes</span></button>}
        </nav>

        <div className="side-section-head"><span>RECENT TRAILS</span><button className="icon-button tiny" onClick={() => setPage('archive')} aria-label="See all trails"><MoreHorizontal size={17} /></button></div>
        {holes.length > 4 && <label className="sidebar-search"><Search size={14} /><input placeholder="Find a trail" value={search} onChange={(event) => setSearch(event.target.value)} /></label>}
        <div className="recent-list">
          {filteredHoles.slice(0, 12).map((hole) => <div className={`recent-row ${graph?.id === hole.id && page === 'explore' ? 'current' : ''}`} key={hole.id}>
            <button className="recent-open" onClick={() => openHole(hole.id)} title={hole.question}>
              <span className="recent-dot" /><span className="recent-text">{hole.title}</span>
            </button>
            <button className="recent-delete" onClick={() => deleteHole(hole)} aria-label={`Delete ${hole.title}`} title="Delete trail"><Trash2 size={13} /></button>
          </div>)}
          {!holes.length && <div className="sidebar-empty">Your trails will gather here.</div>}
        </div>

        <div className="sidebar-footer"><span className="status-dot" /><span>{aiConfigured ? 'SAVED ON THIS DEVICE' : 'ADD GEMINI KEY TO BEGIN'}</span><span className="footer-mark" /></div>
      </aside>

      <main className="main-column">
        <header className="topbar">
          <div className="topbar-left"><button className="icon-button menu-toggle" onClick={() => setMobileNav(true)} aria-label="Open navigation"><Menu size={19} /></button>
            <span className="topbar-label">{page === 'archive' ? 'YOUR ARCHIVE' : page === 'recap' ? 'FIELD NOTES' : page === 'explore' ? 'EXPLORING' : 'A SPACE FOR CURIOSITY'}</span>
          </div>
          <div className="topbar-right">{page === 'explore' && graph && <><span className="saved-indicator"><span /> SAVED LOCALLY</span><button className="topbar-action" onClick={() => setPage('recap')}><BookOpen size={14} /> Recap</button></>}</div>
        </header>

        {error && <div className="error-banner" role="alert"><span>{error}</span><button className="icon-button tiny" onClick={() => setError('')} aria-label="Dismiss"><X size={15} /></button></div>}

        {page === 'start' && <section className="welcome-screen">
          <div className="welcome-orbit orbit-a" /><div className="welcome-orbit orbit-b" />
          <div className="welcome-copy"><div className="eyebrow"><span className="eyebrow-line" /> A CURIOSITY ENGINE <span className="eyebrow-line" /></div>
            <h1>Every question<br />leads <em>somewhere.</em></h1>
            <p className="welcome-subtitle">Start with a question. Follow your curiosity.<br />Never lose the trail.</p>
            <form className="question-composer" onSubmit={(event) => { event.preventDefault(); createHole() }}>
              <label htmlFor="starting-question">WHAT'S ON YOUR MIND?</label>
              <textarea id="starting-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Why do humans seek power?" maxLength={500} rows={2} disabled={busy} />
              <div className="composer-bottom"><span>{question.length}/500</span><button type="submit" disabled={busy || !aiConfigured}>{busy ? <><LoaderCircle className="spin" size={16} /> Opening trail</> : <>Begin exploring <ArrowRight size={16} /></>}</button></div>
            </form>
            {!aiConfigured && <p className="setup-inline">Connect Gemini to start a live exploration. Add <code>GEMINI_API_KEY</code> to <code>.env</code> and restart the API.</p>}
            <div className="example-questions"><span>OR TRY</span>{EXAMPLES.map((example) => <button key={example} onClick={() => { setQuestion(example); createHole(example) }} disabled={busy || !aiConfigured}>{example}<ArrowDownRight size={13} /></button>)}</div>
          </div>
          <div className="welcome-footer"><span>IDEAS ARE TERRITORY</span><span className="footer-coordinates">A MAP WITH NO FIXED ROUTE</span></div>
        </section>}

        {page === 'explore' && graph && <>
          <div className="graph-heading"><div><div className="graph-kicker"><Compass size={13} /> YOUR OPEN QUESTION</div><h1>{graph.question}</h1>{graph.metrics.first_level_branches < 5 && <p className="graph-incomplete">This trail was saved with {graph.metrics.first_level_branches} of 5 first paths by an earlier version of Ronin.</p>}</div><button className="graph-menu" onClick={() => setPage('recap')}><span>{graph.metrics.first_level_branches} first paths · {graph.metrics.node_count} concepts</span><ChevronDown size={15} /></button></div>
          <div className="canvas-shell"><ExplorerCanvas key={graph.id} graph={graph} selectedId={selectedId} busyNodeId={busyNodeId} focus={expandFocus} onSelect={selectNode} onExpand={expandSelected} /></div>
          <div className="canvas-legend"><span><i className="legend-root" /> STARTING QUESTION</span><span><i className="legend-branch" /> A PATH TO FOLLOW</span><span className="legend-hint"><Network size={13} /> Drag to wander · scroll to zoom</span></div>
          {busy && <div className="loading-cover"><div className="loading-mark"><LoaderCircle className="spin" size={24} /></div><span>Reopening your trail…</span></div>}
        </>}

        {page === 'archive' && <ArchiveView holes={filteredHoles} onOpen={openHole} onDelete={deleteHole} onNew={newHole} />}
        {page === 'recap' && graph && <RecapView graph={graph} onBack={() => setPage('explore')} />}
      </main>

      {page === 'explore' && graph && <>
        <button className="detail-scrim" aria-label="Close details" onClick={() => setMobileDetail(false)} />
        <aside className="detail-panel">
          <div className="detail-topline"><span>FIELD GUIDE</span><button className="icon-button detail-close" onClick={() => setMobileDetail(false)} aria-label="Close details"><X size={17} /></button><button className="detail-back" onClick={() => setPage('archive')}><ArrowLeft size={13} /> Archive</button></div>
          {selected ? <>
            <div className="detail-domain"><span className="domain-orbit" />{selected.domain.toUpperCase()}</div>
            <h2>{selected.title}</h2>
            <p className="detail-summary">{selected.summary}</p>
            <section className="detail-section"><div className="section-label"><span>THE CONNECTION</span><span className="section-rule" /></div><p>{selected.connection_reason}</p></section>
            <section className="detail-section next-question"><div className="section-label"><span>KEEP ASKING</span><Sparkles size={13} /></div><p>{selected.exploration_question}</p></section>
            <section className="detail-section path-section"><div className="section-label"><span>YOUR TRAIL</span><span className="section-rule" /></div><div className="breadcrumb-path">{breadcrumb.map((item, index) => <span key={item.id} className={index === breadcrumb.length - 1 ? 'crumb current-crumb' : 'crumb'}>{index > 0 && <ArrowRight size={10} />}{item.title}</span>)}</div></section>
            <section className="detail-section sources-section"><div className="section-label"><span>SOURCES ON THIS CONCEPT</span><span className="source-count">{selected.sources.length}</span></div>
              {selected.sources.length ? selected.sources.map((source) => <a className="source-link" href={source.url} target="_blank" rel="noreferrer" key={source.id}><span><strong>{source.publisher || source.title}</strong>{source.title !== source.publisher && <small>{source.title}</small>}{source.citation_text && <small className="citation">“{source.citation_text}”</small>}</span><ExternalLink size={13} /></a>)
                : selected.parent_id === null
                  ? <p className="no-sources is-root">Ronin searches for sources on each branch, not on the starting question.{graph.metrics.unique_sources ? ` ${graph.metrics.unique_sources} unique ${graph.metrics.unique_sources === 1 ? 'source is' : 'sources are'} linked across ${graph.metrics.sourced_nodes} ${graph.metrics.sourced_nodes === 1 ? 'branch' : 'branches'} of this map.` : ''}</p>
                  : <p className="no-sources">Search grounding returned no citation clearly tied to this concept, so none is shown.{graph.metrics.unique_sources ? ` ${graph.metrics.sourced_nodes} other ${graph.metrics.sourced_nodes === 1 ? 'concept has' : 'concepts have'} sources.` : ''}</p>}
            </section>
            <div className="detail-actions">
              <button className="explore-button" onClick={() => expandSelected()} disabled={busyNodeId === selected.id}>{busyNodeId === selected.id ? <><LoaderCircle className="spin" size={15} /> Following the thread…</> : <>{children.length ? 'Open these trails' : 'Explore further'} <ArrowRight size={15} /></>}</button>
              <div className="followup-composer"><label htmlFor="followup">OR POINT TOWARD SOMETHING</label><div className="followup-input"><input id="followup" placeholder="e.g. through ancient history" value={direction} onChange={(event) => setDirection(event.target.value)} maxLength={500} onKeyDown={(event) => { if (event.key === 'Enter' && direction.trim()) expandSelected(direction) }} /><button title="Explore this direction" onClick={() => expandSelected(direction)} disabled={!direction.trim() || !!busyNodeId} aria-label="Explore follow-up direction"><ArrowRight size={16} /></button></div></div>
              {children.length > 0 && <div className="child-count-note"><GitBranch size={13} /> {children.length} saved {children.length === 1 ? 'path' : 'paths'} branch from here</div>}
            </div>
          </> : <div className="detail-empty"><Sparkles size={18} /><p>Choose a concept on the map to see where it leads.</p></div>}
          <div className="detail-footnote"><span>RONIN FIELD GUIDE</span><span>01 — 26</span></div>
        </aside>
      </>}
    </div>
  )
}
