import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
// React Flow positions nodes, edges and handles with its own stylesheet; without it every node
// falls back into normal document flow, which hides most of the graph and breaks pointer events.
import '@xyflow/react/dist/style.css'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><App /></React.StrictMode>,
)
