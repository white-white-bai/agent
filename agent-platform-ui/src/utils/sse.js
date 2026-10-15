// SSE 事件流解析（纯函数，便于单测）

export function parseSseChunk(buffer) {
  const events = []
  let rest = buffer
  let boundary = rest.indexOf('\n\n')
  while (boundary >= 0) {
    const block = rest.slice(0, boundary)
    rest = rest.slice(boundary + 2)
    const data = block
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trim())
      .join('\n')
    if (data) {
      try {
        events.push(JSON.parse(data))
      } catch {
        // 非 JSON 的数据行直接忽略，不影响后续事件
      }
    }
    boundary = rest.indexOf('\n\n')
  }
  return { events, rest }
}
