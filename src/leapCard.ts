export const CARD_WIDTH = 1080
export const CARD_HEIGHT = 1350

export type LeapCardData = { question: string; end: string; waypoints: string[]; hook: string; reframe: string; hops: number; domains: number; footer?: string }

// Canvas cannot read CSS variables cheaply, so these mirror --bg, --paper, --rust and --muted in styles.css.
const BG = '#191a17'
const PAPER = '#d9cfba'
const RUST = '#d87555'
const MUTED = '#9b998c'
const SERIF = 'Fraunces, Georgia, serif'
const SANS = "'DM Sans', 'Segoe UI', sans-serif"
const MONO = "'DM Mono', Consolas, monospace"
const PAD = 96

export function wrapLines(ctx: CanvasRenderingContext2D, text: string, maxWidth: number, maxLines: number): string[] {
  const lines: string[] = []
  let line = ''
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const next = line ? `${line} ${word}` : word
    if (ctx.measureText(next).width <= maxWidth) {
      line = next
      continue
    }
    if (line) lines.push(line)
    line = ''
    // A word wider than the card (Japanese has no spaces, URLs have none either) breaks between characters.
    for (const char of word) {
      if (line && ctx.measureText(line + char).width > maxWidth) {
        lines.push(line)
        line = char
      } else line += char
    }
  }
  if (line) lines.push(line)
  if (lines.length <= maxLines) return lines
  const kept = lines.slice(0, maxLines)
  let last = kept[maxLines - 1]
  while (last && ctx.measureText(`${last}…`).width > maxWidth) last = last.slice(0, -1).trimEnd()
  kept[maxLines - 1] = `${last}…`
  return kept
}

function block(ctx: CanvasRenderingContext2D, text: string, font: string, color: string, y: number, lineHeight: number, maxLines: number, x = PAD): number {
  ctx.font = font
  ctx.fillStyle = color
  for (const line of wrapLines(ctx, text, CARD_WIDTH - x - PAD, maxLines)) {
    ctx.fillText(line, x, y)
    y += lineHeight
  }
  return y
}

export function drawLeapCard(ctx: CanvasRenderingContext2D, card: LeapCardData): void {
  ctx.fillStyle = BG
  ctx.fillRect(0, 0, CARD_WIDTH, CARD_HEIGHT)
  ctx.textBaseline = 'alphabetic'

  block(ctx, 'RONIN · A LEAP', `500 26px ${MONO}`, RUST, 120, 0, 1)
  ctx.fillStyle = '#393a32'
  ctx.fillRect(PAD, 144, CARD_WIDTH - PAD * 2, 2)

  block(ctx, 'STARTED WITH:', `500 22px ${MONO}`, MUTED, 200, 0, 1)
  let y = block(ctx, card.question, `400 34px ${SANS}`, PAPER, 246, 44, 2)
  y = block(ctx, card.hook, `600 72px ${SERIF}`, PAPER, y + 64, 84, 3)
  block(ctx, 'ENDED AT:', `500 22px ${MONO}`, MUTED, y + 28, 0, 1)
  y = block(ctx, card.end, `500 44px ${SERIF}`, RUST, y + 78, 54, 2)

  const chain = [card.question, ...card.waypoints, card.end]
  const top = y + 24
  ctx.fillStyle = RUST
  ctx.fillRect(PAD + 7, top, 2, (chain.length - 1) * 44)
  chain.forEach((title, index) => {
    const rowY = top + index * 44
    ctx.fillStyle = index === 0 || index === chain.length - 1 ? RUST : PAPER
    ctx.beginPath()
    ctx.arc(PAD + 8, rowY, 8, 0, Math.PI * 2)
    ctx.fill()
    block(ctx, title, `400 26px ${SANS}`, index === chain.length - 1 ? PAPER : MUTED, rowY + 9, 0, 1, PAD + 40)
  })
  y = top + (chain.length - 1) * 44 + 64

  block(ctx, 'INTERPRETATION', `500 22px ${MONO}`, MUTED, y, 0, 1)
  block(ctx, card.reframe, `italic 400 30px ${SANS}`, PAPER, y + 44, 40, 3)

  ctx.fillStyle = '#393a32'
  ctx.fillRect(PAD, CARD_HEIGHT - 110, CARD_WIDTH - PAD * 2, 2)
  block(ctx, card.footer ?? `${card.hops} hops · ${card.domains} subjects crossed`, `400 24px ${MONO}`, MUTED, CARD_HEIGHT - 64, 0, 1)
  ctx.font = `500 32px ${SERIF}`
  ctx.fillStyle = PAPER
  ctx.textAlign = 'right'
  ctx.fillText('Ronin', CARD_WIDTH - PAD, CARD_HEIGHT - 62)
  ctx.textAlign = 'left'
}

// document.fonts.ready only waits for fonts the page already uses, so request every face the card draws with.
export function loadCardFonts(): Promise<unknown> {
  return Promise.all([`600 72px ${SERIF}`, `500 44px ${SERIF}`, `400 34px ${SANS}`, `italic 400 30px ${SANS}`, `500 26px ${MONO}`]
    .map((font) => document.fonts.load(font))).catch(() => undefined)
}

export async function downloadLeapCard(card: LeapCardData): Promise<void> {
  await loadCardFonts()
  const canvas = document.createElement('canvas')
  canvas.width = CARD_WIDTH
  canvas.height = CARD_HEIGHT
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('This browser cannot draw the card.')
  drawLeapCard(ctx, card)
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
  if (!blob) throw new Error('The card image could not be created.')
  const slug = card.end.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'trail'
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `ronin-leap-${slug}.png`
  link.click()
  setTimeout(() => URL.revokeObjectURL(link.href), 1000)
}
