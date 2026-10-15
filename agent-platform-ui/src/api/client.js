import { parseSseChunk } from '@/utils/sse'

export const TOKEN_KEY = 'ap_admin_token'

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

let unauthorizedHandler = null

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler
}

export function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setToken(token) {
  try {
    if (token) {
      window.localStorage.setItem(TOKEN_KEY, token)
    } else {
      window.localStorage.removeItem(TOKEN_KEY)
    }
  } catch {
    /* 隐私模式下 localStorage 不可用，降级为内存态 */
  }
}

export function buildUrl(path, params) {
  const query = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      query.append(key, String(value))
    }
  })
  const suffix = query.toString()
  return suffix ? `${path}?${suffix}` : path
}

function detailOf(payload, status) {
  const detail = payload && payload.detail
  if (typeof detail === 'string' && detail) {
    return detail
  }
  if (Array.isArray(detail) && detail.length) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join('; ')
  }
  if (payload && typeof payload.msg === 'string' && payload.msg) {
    return payload.msg
  }
  return `HTTP ${status}`
}

export async function request(path, { method = 'GET', body, params } = {}) {
  const headers = {}
  const token = getToken()
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const isForm = body instanceof FormData
  if (body !== undefined && !isForm) {
    headers['Content-Type'] = 'application/json'
  }
  const response = await fetch(buildUrl(path, params), {
    method,
    headers,
    body: body === undefined || isForm ? body : JSON.stringify(body),
  })
  if (response.status === 401 && unauthorizedHandler) {
    unauthorizedHandler()
  }
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(response.status, detailOf(payload, response.status))
  }
  return payload && typeof payload === 'object' && 'data' in payload ? payload.data : payload
}

// SSE 流式请求：逐条把事件回调出去（图运行用）
export async function streamRequest(path, body, onEvent, { signal } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  const response = await fetch(path, { method: 'POST', headers, body: JSON.stringify(body || {}), signal })
  if (response.status === 401 && unauthorizedHandler) {
    unauthorizedHandler()
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new ApiError(response.status, detailOf(payload, response.status))
  }
  if (!response.body) {
    return
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) {
      break
    }
    buffer += decoder.decode(value, { stream: true })
    const parsed = parseSseChunk(buffer)
    buffer = parsed.rest
    parsed.events.forEach((event) => onEvent(event))
  }
  const tail = parseSseChunk(`${buffer}\n\n`)
  tail.events.forEach((event) => onEvent(event))
}
