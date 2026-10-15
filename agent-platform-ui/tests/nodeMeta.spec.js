import { describe, expect, it } from 'vitest'

import { NODE_TYPES, conditionPorts, createNode, defaultConfig, nodeMeta } from '@/graph/nodeMeta'

const EXPECTED_TYPES = ['start', 'end', 'llm', 'knowledge', 'condition', 'code', 'tool', 'aggregate', 'answer', 'parameter-extractor', 'template-transform', 'http-request', 'question-classifier', 'variable-assigner', 'list-operator']

describe('NODE_TYPES catalogue', () => {
  it('mirrors the backend NodeType enum', () => {
    expect(NODE_TYPES.map((meta) => meta.type)).toEqual(EXPECTED_TYPES)
  })

  it('gives every node a label, colour, summary and a defaults factory', () => {
    NODE_TYPES.forEach((meta) => {
      expect(typeof meta.label).toBe('string')
      expect(meta.label.length).toBeGreaterThan(0)
      expect(meta.color).toMatch(/^#[0-9a-f]{6}$/i)
      expect(typeof meta.summary).toBe('string')
      expect(typeof meta.defaults).toBe('function')
    })
  })

  it('only references known field kinds', () => {
    const kinds = new Set(['text', 'textarea', 'number', 'select', 'model-select', 'boolean', 'keyvalue', 'stringlist', 'rows'])
    NODE_TYPES.forEach((meta) => {
      meta.fields.forEach((field) => {
        expect(kinds.has(field.kind)).toBe(true)
      })
    })
  })

  it('declares a start node with no config fields', () => {
    expect(nodeMeta('start').fields).toEqual([])
    expect(defaultConfig('start')).toEqual({})
  })
})

describe('nodeMeta', () => {
  it('resolves a known type', () => {
    expect(nodeMeta('llm').label).toBe('LLM')
  })

  it('falls back to a neutral descriptor for an unknown type', () => {
    const meta = nodeMeta('mystery')
    expect(meta).toMatchObject({ type: 'mystery', label: 'mystery', fields: [] })
    expect(meta.defaults()).toEqual({})
  })
})

describe('defaultConfig', () => {
  it('returns an independent deep copy each call', () => {
    const first = defaultConfig('condition')
    const second = defaultConfig('condition')
    expect(first).toEqual(second)
    expect(first).not.toBe(second)
    first.branches.push({ id: 'branch_2', expression: 'false' })
    expect(second.branches).toHaveLength(1)
  })

  it('seeds the llm node with an empty provider (falls back to the first configured model)', () => {
    expect(defaultConfig('llm')).toMatchObject({ provider: '', temperature: 0.7, output_var: 'text' })
  })
})

describe('createNode', () => {
  it('builds a node with a derived title, position and default config', () => {
    const node = createNode('knowledge', 'knowledge_1', { x: 12, y: 34 })
    expect(node).toMatchObject({ id: 'knowledge_1', type: 'knowledge', title: '知识检索', position: { x: 12, y: 34 } })
    expect(node.config).toEqual(defaultConfig('knowledge'))
  })

  it('defaults the position to the origin', () => {
    expect(createNode('end', 'end_1').position).toEqual({ x: 0, y: 0 })
  })
})

describe('conditionPorts', () => {
  it('lists branch ids followed by the fallback', () => {
    expect(conditionPorts({ branches: [{ id: 'a' }, { id: 'b' }], fallback_id: 'else' })).toEqual(['a', 'b', 'else'])
  })

  it('does not duplicate a fallback that is also a branch', () => {
    expect(conditionPorts({ branches: [{ id: 'a' }], fallback_id: 'a' })).toEqual(['a'])
  })

  it('drops branches without an id and tolerates an empty config', () => {
    expect(conditionPorts({ branches: [{ expression: 'x' }, { id: 'b' }] })).toEqual(['b'])
    expect(conditionPorts(null)).toEqual([])
  })
})
