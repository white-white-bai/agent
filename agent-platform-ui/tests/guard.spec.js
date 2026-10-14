import { describe, expect, it, vi } from 'vitest'

import { FORBIDDEN_PATH, createGuard, menuOf } from '@/router/guard'
import { MENU_PAGES } from '@/router'

function fakeAuth({ can = () => true, profile = null, fail = false } = {}) {
  const auth = {
    profile,
    can: vi.fn(can),
    loadProfile: vi.fn(async () => {
      if (fail) {
        throw new Error('unauthorized')
      }
      auth.profile = { username: 'admin', permissions: ['*'] }
      return auth.profile
    }),
  }
  return auth
}

describe('menuOf', () => {
  it('keeps only pages the principal may see', () => {
    const auth = fakeAuth({ can: (permission) => permission === 'app:read' })
    const pages = [
      { path: '/apps', meta: { permission: 'app:read' } },
      { path: '/accounts', meta: { permission: 'user:read' } },
    ]
    expect(menuOf(pages, auth).map((page) => page.path)).toEqual(['/apps'])
  })

  it('drops hidden pages', () => {
    const auth = fakeAuth()
    expect(menuOf([{ path: '/x', meta: { hidden: true } }], auth)).toEqual([])
  })

  it('returns every visible page for a wildcard principal', () => {
    const auth = fakeAuth({ can: () => true })
    const visible = MENU_PAGES.filter((page) => !(page.meta && page.meta.hidden))
    expect(menuOf(MENU_PAGES, auth)).toHaveLength(visible.length)
  })
})

describe('createGuard', () => {
  it('lets public routes through without a profile', async () => {
    const auth = fakeAuth()
    const guard = createGuard(auth)
    await expect(guard({ meta: { public: true }, fullPath: '/login' })).resolves.toBe(true)
    expect(auth.loadProfile).not.toHaveBeenCalled()
  })

  it('loads the profile before allowing a protected route', async () => {
    const auth = fakeAuth()
    const guard = createGuard(auth)
    await expect(guard({ meta: { permission: 'app:read' }, fullPath: '/apps' })).resolves.toBe(true)
    expect(auth.loadProfile).toHaveBeenCalledTimes(1)
  })

  it('redirects to login with a redirect query when the profile cannot load', async () => {
    const auth = fakeAuth({ fail: true })
    const guard = createGuard(auth)
    await expect(guard({ meta: {}, fullPath: '/metrics' })).resolves.toEqual({
      path: '/login',
      query: { redirect: '/metrics' },
    })
  })

  it('omits the redirect query for the root path', async () => {
    const auth = fakeAuth({ fail: true })
    const guard = createGuard(auth)
    await expect(guard({ meta: {}, fullPath: '/' })).resolves.toEqual({ path: '/login', query: {} })
  })

  it('sends an unauthorised principal to the forbidden page', async () => {
    const auth = fakeAuth({ can: () => false })
    const guard = createGuard(auth)
    await expect(guard({ meta: { permission: 'user:write' }, fullPath: '/accounts' })).resolves.toEqual({
      path: FORBIDDEN_PATH,
    })
  })

  it('does not re-load a profile that is already present', async () => {
    const auth = fakeAuth({ profile: { username: 'admin', permissions: ['app:read'] } })
    const guard = createGuard(auth)
    await expect(guard({ meta: { permission: 'app:read' }, fullPath: '/apps' })).resolves.toBe(true)
    expect(auth.loadProfile).not.toHaveBeenCalled()
  })
})
