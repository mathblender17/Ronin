import { useEffect, useMemo, useRef, useState } from 'react'
import { Download, RotateCcw, Shuffle } from 'lucide-react'
import { api } from './api'
import { CARD_HEIGHT, CARD_WIDTH, downloadLeapCard, drawLeapCard, loadCardFonts } from './leapCard'
import type { Graph, LeapCandidate } from './types'

// Flip to false if the leap evaluation misses its bar: the editor then always starts from the node picker.
const RANKING_ENABLED = true

type Draft = LeapCandidate & { hidden: string[] }

function eligibleNodes(graph: Graph) {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]))
  const depth = (id: string | null): number => {
    let d = -1
    for (let current = id; current; current = byId.get(current)?.parent_id ?? null) d += 1
    return d
  }
  return graph.nodes.filter((node) => node.explored && depth(node.id) >= 2)
}

export function LeapEditor({ graph }: { graph: Graph }) {
  const eligible = useMemo(() => eligibleNodes(graph), [graph])
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [error, setError] = useState('')
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [active, setActive] = useState(0)
  const [picking, setPicking] = useState(false)
  const [lastRequest, setLastRequest] = useState<string | undefined>(undefined)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const draft = picking ? undefined : drafts[active]

  async function load(nodeId?: string) {
    setStatus('loading')
    setLastRequest(nodeId)
    try {
      const result = RANKING_ENABLED || nodeId ? await api.leaps(graph.id, nodeId) : { ranked: false, candidates: [] }
      setDrafts(result.candidates.map((candidate) => ({ ...candidate, hidden: [] })))
      setActive(0)
      setPicking(result.candidates.length === 0)
      setStatus('ready')
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Ronin could not find a leap. Please retry.')
      setStatus('error')
    }
  }

  useEffect(() => {
    const ctx = canvasRef.current?.getContext('2d')
    if (!ctx || !draft) return
    const card = toCard(draft)
    drawLeapCard(ctx, card)
    let current = true
    loadCardFonts().then(() => { if (current) drawLeapCard(ctx, card) })
    return () => { current = false }
  }, [draft, graph.question])

  function toCard(item: Draft) {
    return {
      question: graph.question, end: item.path[item.path.length - 1], hook: item.hook, reframe: item.reframe,
      waypoints: item.waypoints.filter((title) => !item.hidden.includes(title)), hops: item.hops, domains: item.domains,
    }
  }

  function update(patch: Partial<Draft>) {
    setDrafts((items) => items.map((item, index) => index === active ? { ...item, ...patch } : item))
  }

  if (!eligible.length) {
    return <section className="leap-editor">
      <button className="leap-find" disabled>Find my leap</button>
      <p className="leap-note">Go one layer deeper to find a leap.</p>
    </section>
  }

  if (status === 'idle') {
    return <section className="leap-editor">
      <button className="leap-find" onClick={() => load()}><Shuffle size={14} /> Find my leap</button>
      <p className="leap-note">Ronin looks for the farthest coherent jump from your question to a concept you opened.</p>
    </section>
  }

  return <section className="leap-editor" aria-busy={status === 'loading'}>
    <div className="leap-tabs" role="tablist">
      {drafts.map((item, index) => <button key={item.node_id} role="tab" aria-selected={!picking && index === active} onClick={() => { setPicking(false); setActive(index) }}>Leap {index + 1}</button>)}
      <button role="tab" aria-selected={picking} onClick={() => setPicking(true)}>Pick a node instead</button>
    </div>

    {status === 'loading' && <p className="leap-note">Looking for your leap…</p>}
    {status === 'error' && <p className="leap-error" role="alert">{error} <button onClick={() => load(lastRequest)}><RotateCcw size={12} /> Retry</button></p>}

    {status === 'ready' && picking && <ul className="leap-picker">
      {eligible.map((node) => <li key={node.id}><button onClick={() => load(node.id)}>{node.title}</button></li>)}
    </ul>}

    {status === 'ready' && draft && <div className="leap-body">
      <div className="leap-fields">
        <label>Hook<textarea value={draft.hook} rows={2} onChange={(event) => update({ hook: event.target.value })} /></label>
        <label>Reframe <span>interpretation</span><textarea value={draft.reframe} rows={3} onChange={(event) => update({ reframe: event.target.value })} /></label>
        <fieldset>
          <legend>Waypoints</legend>
          {draft.waypoints.map((title) => <label className="leap-check" key={title}>
            <input type="checkbox" checked={!draft.hidden.includes(title)} onChange={(event) => update({ hidden: event.target.checked ? draft.hidden.filter((item) => item !== title) : [...draft.hidden, title] })} />
            {title}
          </label>)}
        </fieldset>
        <button className="leap-find" onClick={() => downloadLeapCard(toCard(draft)).catch((exc) => { setError(exc.message); setStatus('error') })}><Download size={14} /> Download PNG</button>
      </div>
      <canvas ref={canvasRef} className="leap-preview" width={CARD_WIDTH} height={CARD_HEIGHT} aria-label="Leap card preview" />
    </div>}
  </section>
}
