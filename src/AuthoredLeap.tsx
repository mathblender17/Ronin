import { useEffect, useRef, useState } from 'react'
import { Download } from 'lucide-react'
import { CARD_HEIGHT, CARD_WIDTH, downloadLeapCard, drawLeapCard, loadCardFonts, type LeapCardData } from './leapCard'
import type { Concept, Graph } from './types'

// The approved Leap of an authored story, straight from the story file: no AI call, so it works on the read-only site.
export function authoredLeap(graph: Graph): LeapCardData | null {
  const leap = graph.nodes.find((node) => node.stage === 'leap')
  if (!leap) return null
  const byId = new Map(graph.nodes.map((node) => [node.id, node]))
  const chain: Concept[] = []
  for (let current: Concept | undefined = leap; current; current = current.parent_id ? byId.get(current.parent_id) : undefined) chain.unshift(current)
  const descent = chain.filter((node) => node.stage === 'descent')
  const sources = new Set(graph.nodes.flatMap((node) => node.sources.map((source) => source.url)))
  return {
    question: graph.title, end: leap.title, hook: graph.question, reframe: leap.connection_reason,
    waypoints: descent.slice(0, 3).map((node) => node.title), hops: chain.length - 1, domains: 0,
    footer: `${descent.length + 2} discoveries · ${sources.size} sources`,
  }
}

export function AuthoredLeap({ card }: { card: LeapCardData }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const ctx = canvasRef.current?.getContext('2d')
    if (!ctx) return
    drawLeapCard(ctx, card)
    let current = true
    loadCardFonts().then(() => { if (current) drawLeapCard(ctx, card) })
    return () => { current = false }
  }, [card])

  return <section className="leap-editor authored-leap">
    <div className="leap-body">
      <div className="leap-fields">
        <p className="leap-note">The Leap: the connection this rabbit hole was built to reveal.</p>
        <button className="leap-find" onClick={() => downloadLeapCard(card).catch((exc) => setError(exc.message))}><Download size={14} /> Download PNG</button>
        {error && <p className="leap-error" role="alert">{error}</p>}
      </div>
      <canvas ref={canvasRef} className="leap-preview" width={CARD_WIDTH} height={CARD_HEIGHT} aria-label="Leap card preview" />
    </div>
  </section>
}
