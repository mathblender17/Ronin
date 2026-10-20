export type Source = {
  id: string
  title: string
  url: string
  publisher: string
  citation_text: string
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
  nodes: Concept[]
  edges: GraphEdge[]
  metrics: Metrics
}

export type RabbitHoleSummary = Omit<Graph, 'nodes' | 'edges' | 'metrics'> & {
  node_count: number
  max_depth: number
  first_level_branches: number
}
