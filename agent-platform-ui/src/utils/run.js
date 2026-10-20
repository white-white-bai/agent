// 运行对话框的纯逻辑（便于单测）

export function buildRunInputs(schema = []) {
  const values = {}
  schema.forEach((item) => {
    if (!item || !item.name) {
      return
    }
    values[item.name] = item.default === null || item.default === undefined ? '' : item.default
  })
  return values
}

export function mergeRunInputs(values = {}, extras = []) {
  const inputs = { ...values }
  extras.forEach((item) => {
    if (item && item.name) {
      inputs[item.name] = item.value
    }
  })
  return inputs
}

export function formatRunOutput(value) {
  if (value === null || value === undefined || value === '') {
    return ''
  }
  if (typeof value === 'string') {
    return value
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function summarizeInterrupt(event = {}) {
  const pending = (event.interrupts || [])[0] || {}
  const value = pending.value || event.value || {}
  return {
    id: pending.id || event.interrupt_id || '',
    node: value.node || event.node || '',
    title: value.title || value.node || '',
    question: value.question || '请确认是否继续执行',
    options: value.options || ['approve', 'reject'],
    payload: value.payload || {},
  }
}

export function buildResumePayload(event = {}, { action = 'approve', payload = {} } = {}) {
  const summary = summarizeInterrupt(event)
  return {
    interrupt_id: summary.id,
    action,
    payload,
  }
}
