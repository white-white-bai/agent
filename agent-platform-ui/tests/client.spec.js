import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  TOKEN_KEY,
  buildUrl,
  getToken,
  request,
  setToken,
  setUnauthorizedHandler,
} from '@/api/client'

function mockFetch({ status = 200, payload = {}, jsonError = false } = {}) {
  const fn = vi.fn(async () => ({
    status,
    ok: status >= 200 && status < 300,
    json: jsonError ? async () => { throw new Error('bad json') } : async () => payload,
  }))
  global.fetch = fn
  return fn
}

beforeEach(() => {
  window.localStorage.clear()
  setUnauthorizedHandler(null)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('buildUrl', () => {
  it('returns the bare path when there are no params', () => {
    expect(buildUrl('/admin/apps')).toBe('/admin/apps')
    expect(buildUrl('/admin/apps', {})).toBe('/admin/apps')
  })

  it('skips empty, null and undefined values', () => {
    expect(buildUrl('/admin/apps', { tenant_code: '', app_uuid: null, days: undefined })).toBe('/admin/apps')
  })

  it('appends defined params as a query string', () => {
    expect(buildUrl('/admin/apps', { tenant_code: 't1', days: 7 })).toBe('/admin/apps?tenant_code=t1&days=7')
  })
})

describe('token storage', () => {
  it('round-trips a token through localStorage', () => {
    expect(getToken()).toBe('')
    setToken('abc')
    expect(getToken()).toBe('abc')
    expect(window.localStorage.getItem(TOKEN_KEY)).toBe('abc')
    setToken('')
    expect(getToken()).toBe('')
  })
})

describe('request', () => {
  it('unwraps the { data } envelope', async () => {
    mockFetch({ payload: { data: { total: 3 } } })
    await expect(request('/admin/metrics/overview')).resolves.toEqual({ total: 3 })
  })

  it('passes through payloads without an envelope', async () => {
    mockFetch({ payload: [1, 2] })
    await expect(request('/admin/apps')).resolves.toEqual([1, 2])
  })

  it('sends the bearer token and JSON body', async () => {
    setToken('tok')
    const fetchMock = mockFetch({ payload: { data: null } })
    await request('/admin/apps', { method: 'POST', body: { app_name: 'a' } })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/admin/apps')
    expect(init.method).toBe('POST')
    expect(init.headers.Authorization).toBe('Bearer tok')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(init.body).toBe('{"app_name":"a"}')
  })

  it('passes FormData through without a JSON content type', async () => {
    const fetchMock = mockFetch({ payload: { data: null } })
    const form = new FormData()
    form.append('file', new Blob(['x']), 'a.txt')
    await request('/admin/documents/upload', { method: 'POST', body: form })
    const [, init] = fetchMock.mock.calls[0]
    expect(init.body).toBe(form)
    expect(init.headers['Content-Type']).toBeUndefined()
  })

  it('omits the authorization header and body when absent', async () => {
    const fetchMock = mockFetch({ payload: { data: [] } })
    await request('/admin/apps', { params: { tenant_code: 't1' } })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/admin/apps?tenant_code=t1')
    expect(init.headers.Authorization).toBeUndefined()
    expect(init.body).toBeUndefined()
  })

  it('turns a string detail into an ApiError', async () => {
    mockFetch({ status: 400, payload: { detail: 'bad request' } })
    await expect(request('/admin/apps')).rejects.toMatchObject({
      name: 'ApiError',
      status: 400,
      detail: 'bad request',
    })
  })

  it('flattens a validation detail array from a 422', async () => {
    mockFetch({ status: 422, payload: { detail: [{ msg: 'field required' }, { msg: 'not an int' }] } })
    const error = await request('/admin/apps').catch((err) => err)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.detail).toBe('field required; not an int')
  })

  it('falls back to HTTP status when the body is unreadable', async () => {
    mockFetch({ status: 500, jsonError: true })
    await expect(request('/admin/apps')).rejects.toMatchObject({ status: 500, detail: 'HTTP 500' })
  })

  it('invokes the unauthorized handler on 401', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    mockFetch({ status: 401, payload: { detail: 'unauthorized' } })
    await expect(request('/admin/me')).rejects.toBeInstanceOf(ApiError)
    expect(handler).toHaveBeenCalledTimes(1)
  })
})
