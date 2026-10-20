import type { Graph, RabbitHoleSummary } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new Error('Ronin could not reach its local API. Start the backend and try again.')
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const message = typeof payload?.detail === 'string' ? payload.detail : `The request failed (${response.status}). Please try again.`
    throw new Error(message)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string; ai_configured: boolean; read_only: boolean }>('/api/health'),
  list: () => request<RabbitHoleSummary[]>('/api/rabbit-holes'),
  create: (question: string) => request<Graph>('/api/rabbit-holes', { method: 'POST', body: JSON.stringify({ question }) }),
  get: (id: string) => request<Graph>(`/api/rabbit-holes/${id}`),
  visit: (id: string, nodeId: string) => request<Graph>(`/api/rabbit-holes/${id}/nodes/${nodeId}/visit`, { method: 'POST' }),
  expand: (id: string, nodeId: string, direction?: string) => request<{ node_ids: string[]; reused: boolean }>(
    `/api/rabbit-holes/${id}/nodes/${nodeId}/expand`,
    { method: 'POST', body: JSON.stringify(direction ? { direction } : {}) },
  ),
  remove: (id: string) => request<void>(`/api/rabbit-holes/${id}`, { method: 'DELETE' }),
}
