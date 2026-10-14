import { describe, expect, it } from 'vitest'

import { barLayout, formatPercent, normalizeSeries, seriesMax } from '@/utils/chart'

describe('normalizeSeries', () => {
  it('accepts the metrics { date, count } shape', () => {
    expect(normalizeSeries([{ date: '2026-10-01', count: 3 }])).toEqual([{ label: '2026-10-01', value: 3 }])
  })

  it('accepts the { label, value } shape', () => {
    expect(normalizeSeries([{ label: 'a', value: 5 }])).toEqual([{ label: 'a', value: 5 }])
  })

  it('coerces missing values to zero and tolerates non-arrays', () => {
    expect(normalizeSeries([{ date: 'd' }])).toEqual([{ label: 'd', value: 0 }])
    expect(normalizeSeries(undefined)).toEqual([])
  })
})

describe('barLayout', () => {
  it('scales the tallest bar to the full height and anchors bars at the baseline', () => {
    const layout = barLayout(
      [
        { label: 'a', value: 10 },
        { label: 'b', value: 5 },
      ],
      { width: 100, height: 100, gap: 0 },
    )
    expect(layout[0]).toMatchObject({ x: 0, width: 50, height: 100, y: 0 })
    expect(layout[1]).toMatchObject({ x: 50, width: 50, height: 50, y: 50 })
  })

  it('produces zero-height bars when the series is all zero', () => {
    const layout = barLayout([{ label: 'a', value: 0 }], { width: 100, height: 100, gap: 0 })
    expect(layout[0].height).toBe(0)
    expect(layout[0].y).toBe(100)
  })

  it('returns an empty layout for an empty series', () => {
    expect(barLayout([])).toEqual([])
  })

  it('leaves a gap between bars', () => {
    const layout = barLayout(
      [
        { label: 'a', value: 1 },
        { label: 'b', value: 1 },
      ],
      { width: 100, height: 10, gap: 10 },
    )
    expect(layout[1].x - (layout[0].x + layout[0].width)).toBe(10)
  })
})

describe('seriesMax', () => {
  it('finds the largest value', () => {
    expect(seriesMax([{ value: 1 }, { value: 9 }, { value: 4 }])).toBe(9)
  })

  it('is zero for an empty series', () => {
    expect(seriesMax([])).toBe(0)
  })
})

describe('formatPercent', () => {
  it('renders one decimal place', () => {
    expect(formatPercent(0.1234)).toBe('12.3%')
    expect(formatPercent(0)).toBe('0.0%')
    expect(formatPercent(1)).toBe('100.0%')
  })

  it('treats null/undefined as zero', () => {
    expect(formatPercent(null)).toBe('0.0%')
    expect(formatPercent(undefined)).toBe('0.0%')
  })
})
