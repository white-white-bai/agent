import { defineStore } from 'pinia'

import { fetchMe, login as loginRequest } from '@/api'
import { getToken, setToken } from '@/api/client'

export const WILDCARD = '*'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getToken(),
    profile: null,
  }),
  getters: {
    authenticated: (state) => Boolean(state.token),
    permissions: (state) => (state.profile ? state.profile.permissions || [] : []),
    roleCode: (state) => (state.profile ? state.profile.role_code : ''),
    displayName: (state) => {
      if (!state.profile) {
        return ''
      }
      return state.profile.username || '匿名'
    },
  },
  actions: {
    can(permission) {
      if (!permission) {
        return true
      }
      const permissions = this.permissions
      return permissions.includes(WILDCARD) || permissions.includes(permission)
    },
    async login(username, password) {
      const data = await loginRequest(username, password)
      setToken(data.token)
      this.token = data.token
      await this.loadProfile()
      return data
    },
    async loadProfile() {
      try {
        this.profile = await fetchMe()
      } catch (error) {
        this.logout()
        throw error
      }
      return this.profile
    },
    logout() {
      setToken('')
      this.token = ''
      this.profile = null
    },
  },
})
