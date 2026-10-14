import { describe, expect, it } from 'vitest'

import {
  DEFAULT_PORT,
  INPUT_PORT,
  NODE_HEIGHT,
  NODE_WIDTH,
  SCHEMA_VERSION,
  nextNodeId,
  nodeCell,
  portItems,
  readGraph,
  toCells,
  toDefinition,
} from '@/graph/mapper'

function fakeGraph(nodes, edges = []) {
  return {
    getNodes: () => nodes,
    getEdges: () => edges,
  }
}

function fakeNode(id, data, position = { x: 0, y: 0 }) {
  return { id, getData: () => data, getPosition: () => position }
}

function fakeEdge(id, source, target) {
  return { id, getSource: () => source, getTarget: () => target }
}

describe('nextNodeId', () => {
  it('starts numbering at one', () => {
    expect(nextNodeId('llm')).toBe('llm_1')
    expect(nextNodeId('llm', [])).toBe('llm_1')
  })

  it('skips taken ids', () => {
    expect(nextNodeId('llm', ['llm_1', 'llm_2'])).toBe('llm_3')
    expect(nextNodeId('llm', ['llm_1', 'llm_3'])).toBe('llm_2')
  })

  it('namespaces by node type', () => {
    expect(nextNodeId('knowledge', ['llm_1'])).toBe('knowledge_1')
  })
})

describe('portItems', () => {
  it('emits a single output port for a regular node', () => {
    expect(portItems({ type: 'llm', config: {} })).toEqual([
      { id: INPUT_PORT, group: 'in', args: { x: 0, y: NODE_HEIGHT / 2 } },
      { id: DEFAULT_PORT, group: 'out', args: { x: NODE_WIDTH, y: NODE_HEIGHT / 2 } },
    ])
  })

  it('spreads condition ports evenly down the node edge', () => {
    const items = portItems({
      type: 'condition',
      config: { branches: [{ id: 'a' }, { id: 'b' }], fallback_id: 'else' },
    })
    const outs = items.filter((item) => item.group === 'out')
    expect(outs.map((item) => item.id)).toEqual(['a', 'b', 'else'])
    expect(outs.map((item) => item.args.y)).toEqual([
      (NODE_HEIGHT * 1) / 4,
      (NODE_HEIGHT * 2) / 4,
      (NODE_HEIGHT * 3) / 4,
    ])
    outs.forEach((item) => expect(item.args.x).toBe(NODE_WIDTH))
  })
})

describe('nodeCell', () => {
  it('maps a node onto an X6 rect with a deep-copied config', () => {
    const node = { id: 'llm_1', type: 'llm', title: '', position: { x: 5, y: 6 }, config: { model: 'x' } }
    const cell = nodeCell(node)
    expect(cell).toMatchObject({
      id: 'llm_1',
      shape: 'rect',
      x: 5,
      y: 6,
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      label: 'LLM',
      data: { type: 'llm', title: '', config: { model: 'x' } },
    })
    expect(cell.attrs.body.stroke).toBe('#409eff')
    cell.data.config.model = 'mutated'
    expect(node.config.model).toBe('x')
  })

  it('keeps an explicit title', () => {
    expect(nodeCell({ id: 'n', type: 'answer', title: '输出', config: {} }).label).toBe('输出')
  })
})

describe('toCells', () => {
  const definition = {
    nodes: [
      { id: 'start_1', type: 'start', position: { x: 0, y: 0 }, config: {} },
      { id: 'condition_1', type: 'condition', position: { x: 100, y: 0 }, config: { branches: [{ id: 'yes' }], fallback_id: 'no' } },
    ],
    edges: [
      { id: 'e1', source: 'start_1', target: 'condition_1', source_handle: '' },
      { id: 'e2', source: 'condition_1', target: 'end_1', source_handle: 'yes' },
    ],
  }

  it('converts nodes and labels branch edges with their handle', () => {
    const { nodes, edges } = toCells(definition)
    expect(nodes).toHaveLength(2)
    expect(edges[0].source).toEqual({ cell: 'start_1', port: DEFAULT_PORT })
    expect(edges[0].labels).toEqual([])
    expect(edges[1].source).toEqual({ cell: 'condition_1', port: 'yes' })
    expect(edges[1].labels).toEqual([{ attrs: { label: { text: 'yes', fontSize: 11 } } }])
  })

  it('synthesises an id when an edge has none', () => {
    const { edges } = toCells({ nodes: [], edges: [{ source: 'a', target: 'b' }] })
    expect(edges[0].id).toBe('edge-0-a--b')
  })

  it('tolerates an empty or missing definition', () => {
    expect(toCells()).toEqual({ nodes: [], edges: [] })
  })
})

describe('readGraph', () => {
  it('reads nodes and edges back out of the canvas', () => {
    const graph = fakeGraph(
      [fakeNode('llm_1', { type: 'llm', title: '模型', config: { model: 'x' } }, { x: 10, y: 20 })],
      [fakeEdge('e1', { cell: 'llm_1', port: 'out' }, { cell: 'end_1', port: 'in' })],
    )
    expect(readGraph(graph)).toEqual({
      nodes: [{ id: 'llm_1', type: 'llm', title: '模型', position: { x: 10, y: 20 }, config: { model: 'x' } }],
      edges: [{ id: 'e1', source: 'llm_1', target: 'end_1', source_handle: '' }],
    })
  })

  it('preserves a non-default source handle', () => {
    const graph = fakeGraph([], [fakeEdge('e2', { cell: 'condition_1', port: 'yes' }, { cell: 'end_1' })])
    expect(readGraph(graph).edges[0].source_handle).toBe('yes')
  })

  it('handles nodes with no data payload', () => {
    const graph = fakeGraph([fakeNode('x', null)])
    expect(readGraph(graph).nodes[0]).toMatchObject({ id: 'x', title: '', config: {} })
  })
})

describe('toDefinition', () => {
  it('emits backend-shaped snake_case keys and rounds positions', () => {
    const definition = toDefinition(
      {
        nodes: [{ id: 'a', type: 'llm', title: 't', position: { x: 10.4, y: 20.6 }, config: { model: 'm' } }],
        edges: [{ id: 'e', source: 'a', target: 'b', source_handle: 'yes' }],
      },
      { app_id: 'app-1', name: 'demo', inputs: [{ name: 'query' }], global_variables: { k: 1 }, schema_version: '1.0' },
    )
    expect(definition).toEqual({
      schema_version: '1.0',
      app_id: 'app-1',
      name: 'demo',
      inputs: [{ name: 'query' }],
      global_variables: { k: 1 },
      nodes: [{ id: 'a', type: 'llm', title: 't', position: { x: 10, y: 21 }, config: { model: 'm' } }],
      edges: [{ id: 'e', source: 'a', target: 'b', source_handle: 'yes' }],
    })
  })

  it('defaults the schema version and empty collections', () => {
    expect(toDefinition({})).toEqual({
      schema_version: SCHEMA_VERSION,
      app_id: '',
      name: '',
      inputs: [],
      global_variables: {},
      nodes: [],
      edges: [],
    })
  })
})

describe('round trip', () => {
  it('definition -> cells -> graph -> definition is lossless', () => {
    const original = {
      schema_version: '1.0',
      app_id: 'app-1',
      name: 'demo',
      inputs: [],
      global_variables: {},
      nodes: [
        { id: 'start_1', type: 'start', title: '', position: { x: 0, y: 0 }, config: {} },
        { id: 'condition_1', type: 'condition', title: '分支', position: { x: 220, y: 0 }, config: { branches: [{ id: 'yes', expression: 'true' }], fallback_id: 'no' } },
      ],
      edges: [
        { id: 'e1', source: 'start_1', target: 'condition_1', source_handle: '' },
        { id: 'e2', source: 'condition_1', target: 'start_1', source_handle: 'yes' },
      ],
    }
    const cells = toCells(original)
    const graph = fakeGraph(
      cells.nodes.map((cell) => fakeNode(cell.id, cell.data, { x: cell.x, y: cell.y })),
      cells.edges.map((edge) => fakeEdge(edge.id, edge.source, edge.target)),
    )
    const restored = toDefinition(readGraph(graph), original)
    expect(restored).toEqual(original)
  })
})
