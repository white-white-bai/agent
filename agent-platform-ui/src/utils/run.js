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
