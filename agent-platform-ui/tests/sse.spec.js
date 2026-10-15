import { describe, expect, it } from 'vitest'

import { parseSseChunk } from '@/utils/sse'

describe('parseSseChunk', () => {
  it('extracts complete events and keeps the unfinished remainder', () => {
    const { events, rest } = parseSseChunk('data: {"type":"token","content":"甲"}\n\ndata: {"type":"to')
    expect(events).toEqual([{ type: 'token', content: '甲' }])
    expect(rest).toBe('data: {"type":"to')
  })

  it('parses several events from one chunk', () => {
    const { events, rest } = parseSseChunk('data: {"a":1}\n\ndata: {"b":2}\n\n')
    expect(events).toEqual([{ a: 1 }, { b: 2 }])
    expect(rest).toBe('')
  })

  it('ignores non-JSON data lines', () => {
    const { events } = parseSseChunk('data: heartbeat\n\ndata: {"ok":true}\n\n')
    expect(events).toEqual([{ ok: true }])
  })

  it('returns no events when there is no boundary yet', () => {
    expect(parseSseChunk('data: {"a"').events).toEqual([])
  })
})
