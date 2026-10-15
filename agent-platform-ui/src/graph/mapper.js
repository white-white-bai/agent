import { toRaw } from 'vue'

import { classifierPorts, conditionPorts, nodeMeta } from './nodeMeta'

export const SCHEMA_VERSION = '1.0'
export const NODE_WIDTH = 176
export const NODE_HEIGHT = 46
export const DEFAULT_PORT = 'out'
export const INPUT_PORT = 'in'

export const PORT_GROUPS = {
  in: {
    position: 'absolute',
    attrs: { circle: { r: 4, magnet: 'passive', stroke: '#909399', fill: '#ffffff' } },
  },
  out: {
    position: 'absolute',
    attrs: { circle: { r: 4, magnet: true, stroke: '#409eff', fill: '#ffffff' } },
  },
}

export function nextNodeId(type, existingIds = []) {
  const taken = new Set(existingIds)
  let index = 1
  while (taken.has(`${type}_${index}`)) {
    index += 1
  }
  return `${type}_${index}`
}

export function portItems(node) {
  let outputs = [DEFAULT_PORT]
  if (node.type === 'condition') {
    outputs = conditionPorts(node.config)
  } else if (node.type === 'question-classifier') {
    outputs = classifierPorts(node.config)
  }
  const items = [{ id: INPUT_PORT, group: 'in', args: { x: 0, y: NODE_HEIGHT / 2 } }]
  outputs.forEach((id, index) => {
    items.push({ id, group: 'out', args: { x: NODE_WIDTH, y: (NODE_HEIGHT * (index + 1)) / (outputs.length + 1) } })
  })
  return items
}

export function nodeCell(node) {
  const meta = nodeMeta(node.type)
  const title = node.title || meta.label
  return {
    id: node.id,
    shape: 'rect',
    x: (node.position && node.position.x) || 0,
    y: (node.position && node.position.y) || 0,
    width: NODE_WIDTH,
    height: NODE_HEIGHT,
    label: title,
    attrs: {
      body: { stroke: meta.color, strokeWidth: 1.5, fill: '#ffffff', rx: 6, ry: 6 },
      label: { fill: '#303133', fontSize: 13 },
    },
    // node 可能来自 Vue 响应式对象（图定义存在 ref 里），structuredClone 不接受代理，故先 toRaw
    data: { type: node.type, title: node.title || '', config: structuredClone(toRaw(node.config) || {}) },
    ports: { groups: structuredClone(PORT_GROUPS), items: portItems(node) },
  }
}

// Dify 导出会把普通边的 sourceHandle 写成 source/target，这里兜底归一，避免挂到不存在的端口
export function normalizeHandle(value) {
  const handle = value || ''
  return handle === 'source' || handle === 'target' ? '' : handle
}

export function toCells(definition = {}) {
  const nodes = (definition.nodes || []).map(nodeCell)
  const edges = (definition.edges || []).map((edge, index) => {
    const handle = normalizeHandle(edge.source_handle)
    return {
      id: edge.id || `edge-${index}-${edge.source}-${handle}-${edge.target}`,
      source: { cell: edge.source, port: handle || DEFAULT_PORT },
      target: { cell: edge.target },
      labels: handle ? [{ attrs: { label: { text: handle, fontSize: 11 } } }] : [],
      attrs: { line: { stroke: '#a8abb2', strokeWidth: 1.5, targetMarker: { name: 'block', size: 7 } } },
    }
  })
  return { nodes, edges }
}

export function readGraph(graph) {
  const nodes = graph.getNodes().map((cell) => {
    const data = cell.getData() || {}
    const position = cell.getPosition()
    return {
      id: cell.id,
      type: data.type,
      title: data.title || '',
      position: { x: position.x, y: position.y },
      config: data.config || {},
    }
  })
  const edges = graph.getEdges().map((cell) => {
    const source = cell.getSource() || {}
    const target = cell.getTarget() || {}
    const port = source.port
    return {
      id: cell.id,
      source: source.cell,
      target: target.cell,
      source_handle: port && port !== DEFAULT_PORT ? port : '',
    }
  })
  return { nodes, edges }
}

export function toDefinition(cells, base = {}) {
  return {
    schema_version: base.schema_version || SCHEMA_VERSION,
    app_id: base.app_id || '',
    name: base.name || '',
    inputs: base.inputs || [],
    global_variables: base.global_variables || {},
    nodes: (cells.nodes || []).map((node) => ({
      id: node.id,
      type: node.type,
      title: node.title || '',
      position: {
        x: Math.round((node.position && node.position.x) || 0),
        y: Math.round((node.position && node.position.y) || 0),
      },
      config: node.config || {},
    })),
    edges: (cells.edges || []).map((edge) => ({
      id: edge.id || '',
      source: edge.source,
      target: edge.target,
      source_handle: edge.source_handle || '',
    })),
  }
}
