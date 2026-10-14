export function normalizeSeries(series) {
  const list = Array.isArray(series) ? series : []
  return list.map((item) => ({
    label: String((item && (item.date || item.label)) || ''),
    value: Number((item && (item.count ?? item.value)) || 0),
  }))
}

export function barLayout(items, { width = 640, height = 160, gap = 8 } = {}) {
  const count = items.length
  const barWidth = count ? Math.max(2, (width - gap * (count - 1)) / count) : 0
  const max = items.reduce((acc, item) => Math.max(acc, item.value), 0)
  return items.map((item, index) => {
    const barHeight = max ? Math.round((item.value / max) * height) : 0
    return {
      label: item.label,
      value: item.value,
      x: Math.round(index * (barWidth + gap)),
      y: height - barHeight,
      width: Math.round(barWidth),
      height: barHeight,
    }
  })
}

export function seriesMax(items) {
  return items.reduce((acc, item) => Math.max(acc, item.value), 0)
}

export function formatPercent(rate) {
  return `${(Number(rate || 0) * 100).toFixed(1)}%`
}
