export const FORBIDDEN_PATH = '/403'

export function menuOf(pages, auth) {
  return pages.filter((page) => !(page.meta && page.meta.hidden) && auth.can(page.meta && page.meta.permission))
}

export function createGuard(auth) {
  return async function guard(to) {
    if (to.meta && to.meta.public) {
      return true
    }
    if (!auth.profile) {
      try {
        await auth.loadProfile()
      } catch {
        const query = to.fullPath && to.fullPath !== '/' ? { redirect: to.fullPath } : {}
        return { path: '/login', query }
      }
    }
    const permission = to.meta && to.meta.permission
    if (permission && !auth.can(permission)) {
      return { path: FORBIDDEN_PATH }
    }
    return true
  }
}
