export type Source = {
  id: string
  title: string
  url: string
  publisher: string
  citation_text: string
  medium?: string | null
  creator?: string | null
  published?: string | null
}

export type Concept = {
  id: string
  parent_id: string | null
  title: string
  summary: string
  connection_reason: string
  exploration_question: string
  domain: string
  explored: boolean
  created_at: string
  sources: Source[]
  stage?: string | null
  evidence?: string | null
}

export type Metrics = {
  node_count: number
  max_depth: number
  first_level_branches: number
  explored_nodes: number
  unique_sources: number
  sourced_nodes: number
  domain_count: number
  deepest_path: string[]
  most_explored_branch: string | null
  domains: string[]
}

export type GraphEdge = {
  id: string
  source: string
  target: string
  relationship_note: string
}

export type Graph = {
  id: string
  title: string
  question: string
  created_at: string
  updated_at: string
  slug?: string | null
  territory?: string | null
  published_at?: string | null
  nodes: Concept[]
  edges: GraphEdge[]
  metrics: Metrics
}

export type RabbitHoleSummary = Omit<Graph, 'nodes' | 'edges' | 'metrics'> & {
  node_count: number
  max_depth: number
  first_level_branches: number
}

export type LeapCandidate = {
  node_id: string
  path: string[]
  waypoints: string[]
  hook: string
  reframe: string
  score: number | null
  hops: number
  domains: number
}

export type Leaps = { ranked: boolean; candidates: LeapCandidate[] }
