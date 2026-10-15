import { describe, expect, it } from 'vitest'

import { buildRunInputs, formatRunOutput, mergeRunInputs } from '@/utils/run'

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
