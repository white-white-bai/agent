import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const store = vi.hoisted(() => ({ token: '' }))

vi.mock('@/api/client', () => ({
  getToken: () => store.token,
  setToken: (token) => {
    store.token = token || ''
  },
}))

vi.mock('@/api', () => ({
  fetchMe: vi.fn(),
  login: vi.fn(),
}))

import { fetchMe, login as loginRequest } from '@/api'
import { WILDCARD, useAuthStore } from '@/stores/auth'

beforeEach(() => {
  store.token = ''
  fetchMe.mockReset()
  loginRequest.mockReset()
  setActivePinia(createPinia())
})

describe('auth store defaults', () => {
  it('starts anonymous', () => {
    const auth = useAuthStore()
    expect(auth.authenticated).toBe(false)
    expect(auth.permissions).toEqual([])
    expect(auth.roleCode).toBe('')
    expect(auth.displayName).toBe('')
  })

  it('exposes WILDCARD as *', () => {
    expect(WILDCARD).toBe('*')
  })
})

describe('can()', () => {
  it('allows any permission when the principal holds the wildcard', () => {
    const auth = useAuthStore()
    auth.profile = { username: 'admin', permissions: ['*'] }
    expect(auth.can('graph:write')).toBe(true)
    expect(auth.can('settings:delete')).toBe(true)
  })

  it('matches an explicit permission only', () => {
    const auth = useAuthStore()
    auth.profile = { username: 'editor', permissions: ['app:read', 'graph:write'] }
    expect(auth.can('graph:write')).toBe(true)
    expect(auth.can('user:write')).toBe(false)
  })

  it('treats a falsy permission as unrestricted', () => {
    const auth = useAuthStore()
    expect(auth.can('')).toBe(true)
    expect(auth.can(undefined)).toBe(true)
  })
})

describe('displayName', () => {
  it('prefers the username and falls back to 匿名', () => {
    const auth = useAuthStore()
    auth.profile = { username: 'alice', permissions: [] }
    expect(auth.displayName).toBe('alice')
    auth.profile = { permissions: [] }
    expect(auth.displayName).toBe('匿名')
  })
})

describe('login', () => {
  it('stores the token and then loads the profile', async () => {
    loginRequest.mockResolvedValue({ token: 'tok' })
    fetchMe.mockResolvedValue({ username: 'admin', role_code: 'admin', permissions: ['*'] })
    const auth = useAuthStore()
    await auth.login('admin', 'secret')
    expect(loginRequest).toHaveBeenCalledWith('admin', 'secret')
    expect(store.token).toBe('tok')
    expect(auth.token).toBe('tok')
    expect(auth.authenticated).toBe(true)
    expect(auth.roleCode).toBe('admin')
    expect(auth.can('anything')).toBe(true)
  })
})

describe('loadProfile', () => {
  it('logs out when the profile cannot be fetched', async () => {
    store.token = 'tok'
    fetchMe.mockRejectedValue(new Error('401'))
    const auth = useAuthStore()
    await expect(auth.loadProfile()).rejects.toThrow('401')
    expect(auth.token).toBe('')
    expect(store.token).toBe('')
    expect(auth.profile).toBeNull()
  })
})

describe('logout', () => {
  it('clears the token and profile', () => {
    store.token = 'tok'
    const auth = useAuthStore()
    auth.profile = { username: 'admin', permissions: ['*'] }
    auth.logout()
    expect(auth.token).toBe('')
    expect(auth.profile).toBeNull()
    expect(auth.authenticated).toBe(false)
    expect(store.token).toBe('')
  })
})
