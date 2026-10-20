import { describe, expect, it } from 'vitest'

import { buildResumePayload, buildRunInputs, formatRunOutput, mergeRunInputs, summarizeInterrupt } from '@/utils/run'

describe('buildRunInputs', () => {
  it('seeds declared inputs and blanks missing defaults', () => {
    expect(buildRunInputs([{ name: 'query' }, { name: 'role', default: '政务' }])).toEqual({ query: '', role: '政务' })
  })

  it('ignores entries without a name', () => {
    expect(buildRunInputs([{ default: 'x' }])).toEqual({})
  })

  it('tolerates a missing schema', () => {
    expect(buildRunInputs()).toEqual({})
  })
})

describe('mergeRunInputs', () => {
  it('lets extras override declared inputs', () => {
    const merged = mergeRunInputs({ query: 'a' }, [{ name: 'query', value: 'b' }, { name: 'x', value: '1' }])
    expect(merged).toEqual({ query: 'b', x: '1' })
  })
})

describe('formatRunOutput', () => {
  it('passes strings through and pretty-prints objects', () => {
    expect(formatRunOutput('hi')).toBe('hi')
    expect(formatRunOutput({ a: 1 })).toBe('{\n  "a": 1\n}')
  })

  it('renders empty for nullish values', () => {
    expect(formatRunOutput(null)).toBe('')
    expect(formatRunOutput(undefined)).toBe('')
  })
})

describe('summarizeInterrupt', () => {
  it('reads the pending interrupt value and id', () => {
    const summary = summarizeInterrupt({
      interrupts: [
        {
          id: 'i1',
          value: { node: 'approval2', question: '确认？', options: ['approve', 'reject'], payload: { amount: 1 } },
        },
      ],
    })
    expect(summary).toMatchObject({ id: 'i1', node: 'approval2', question: '确认？', payload: { amount: 1 } })
  })

  it('falls back to defaults for an empty event', () => {
    expect(summarizeInterrupt()).toMatchObject({ id: '', question: '请确认是否继续执行' })
  })
})

describe('buildResumePayload', () => {
  it('builds an interrupt-id keyed payload', () => {
    const event = { interrupts: [{ id: 'i1', value: { node: 'approval2' } }] }
    expect(buildResumePayload(event, { action: 'reject', payload: { reason: 'no' } })).toEqual({
      interrupt_id: 'i1',
      action: 'reject',
      payload: { reason: 'no' },
    })
  })
})
