import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api', () => ({
  login: vi.fn(async () => ({ token: 'tok' })),
  fetchMe: vi.fn(async () => ({ username: 'admin', role_code: 'admin', permissions: ['*'] })),
  listUsers: vi.fn(async () => []),
  createUser: vi.fn(async () => ({})),
  updateUser: vi.fn(async () => ({})),
  deleteUser: vi.fn(async () => ({})),
  listRoles: vi.fn(async () => []),
  createRole: vi.fn(async () => ({})),
  deleteRole: vi.fn(async () => ({})),
  listApps: vi.fn(async () => []),
  getApp: vi.fn(async () => ({})),
  createApp: vi.fn(async () => ({})),
  updateApp: vi.fn(async () => ({})),
  deleteApp: vi.fn(async () => ({})),
  listGraphVersions: vi.fn(async () => []),
  publishGraph: vi.fn(async () => ({ version: 1 })),
  saveGraphDraft: vi.fn(async () => ({})),
  rollbackGraph: vi.fn(async () => ({})),
  importGraph: vi.fn(async () => ({})),
  listSensitiveWords: vi.fn(async () => []),
  createSensitiveWord: vi.fn(async () => ({})),
  deleteSensitiveWord: vi.fn(async () => ({})),
  getGuardConfig: vi.fn(async () => ({})),
  listMcpServers: vi.fn(async () => []),
  createMcpServer: vi.fn(async () => ({})),
  deleteMcpServer: vi.fn(async () => ({})),
  listDocuments: vi.fn(async () => []),
  createDocument: vi.fn(async () => ({})),
  deleteDocument: vi.fn(async () => ({})),
  listProviders: vi.fn(async () => ({ llm: [], retriever: [], embedding: {}, observability: {} })),
  metricsOverview: vi.fn(async () => ({})),
}))

import * as api from '@/api'
import { useAuthStore } from '@/stores/auth'
import AdminLayout from '@/layouts/AdminLayout.vue'
import LoginView from '@/views/LoginView.vue'
import ForbiddenView from '@/views/ForbiddenView.vue'
import AppsView from '@/views/AppsView.vue'
import ProvidersView from '@/views/ProvidersView.vue'
import McpServersView from '@/views/McpServersView.vue'
import KnowledgeView from '@/views/KnowledgeView.vue'
import GuardsView from '@/views/GuardsView.vue'
import AccountsView from '@/views/AccountsView.vue'
import MetricsView from '@/views/MetricsView.vue'

const flush = () => flushPromises()

async function mountView(component, { path = '/apps', profile } = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', name: 'login', component: { template: '<div />' } },
      { path: '/apps', component },
      { path: '/:pathMatch(.*)*', component },
    ],
  })
  await router.push(path)
  await router.isReady()
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore(pinia)
  auth.profile = profile || { username: 'admin', role_code: 'admin', permissions: ['*'] }
  const wrapper = mount(component, { global: { plugins: [pinia, router] } })
  await flush()
  return { wrapper, auth, router, pinia }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('LoginView', () => {
  it('submits credentials and redirects to /apps', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/login', component: LoginView },
        { path: '/apps', component: { template: '<div />' } },
      ],
    })
    await router.push('/login')
    await router.isReady()
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore(pinia)
    const wrapper = mount(LoginView, { global: { plugins: [pinia, router] } })

    const inputs = wrapper.findAllComponents({ name: 'ElInput' })
    inputs[0].vm.$emit('update:modelValue', 'admin')
    inputs[1].vm.$emit('update:modelValue', 'secret')
    await wrapper.find('.login__submit').trigger('click')
    await flush()

    expect(api.login).toHaveBeenCalledWith('admin', 'secret')
    expect(api.fetchMe).toHaveBeenCalled()
    expect(auth.authenticated).toBe(true)
    expect(router.currentRoute.value.path).toBe('/apps')
  })

  it('honours a redirect query', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/login', component: LoginView },
        { path: '/metrics', component: { template: '<div />' } },
      ],
    })
    await router.push('/login?redirect=/metrics')
    await router.isReady()
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore(pinia)
    const wrapper = mount(LoginView, { global: { plugins: [pinia, router] } })
    const inputs = wrapper.findAllComponents({ name: 'ElInput' })
    inputs[0].vm.$emit('update:modelValue', 'admin')
    inputs[1].vm.$emit('update:modelValue', 'secret')
    await wrapper.find('.login__submit').trigger('click')
    await flush()
    expect(router.currentRoute.value.path).toBe('/metrics')
  })

  it('does not call the API without credentials', async () => {
    const { wrapper } = await mountView(LoginView, { path: '/login' })
    await wrapper.find('.login__submit').trigger('click')
    await flush()
    expect(api.login).not.toHaveBeenCalled()
  })
})

describe('ForbiddenView', () => {
  it('renders a 403 result and links back to the app list', async () => {
    const { wrapper } = await mountView(ForbiddenView)
    expect(wrapper.text()).toContain('403')
  })
})

describe('AdminLayout', () => {
  it('renders the menu entries allowed by the principal and the role badge', async () => {
    const { wrapper, auth } = await mountView(AdminLayout)
    expect(wrapper.text()).toContain('agent 中台')
    expect(wrapper.text()).toContain('应用注册')
    expect(wrapper.text()).toContain('监控看板')
    expect(wrapper.text()).toContain('admin')
    expect(auth.can('app:read')).toBe(true)
  })

  it('hides menu entries the principal cannot read', async () => {
    const { wrapper } = await mountView(AdminLayout, { profile: { username: 'v', permissions: ['app:read'] } })
    expect(wrapper.text()).toContain('应用注册')
    expect(wrapper.text()).not.toContain('账号与角色')
  })
})

describe('AppsView', () => {
  it('loads apps on mount and shows the create action for writers', async () => {
    const { wrapper } = await mountView(AppsView)
    expect(api.listApps).toHaveBeenCalled()
    expect(wrapper.text()).toContain('新增应用')
    expect(wrapper.text()).toContain('应用名称')
  })

  it('re-runs the query when the tenant filter changes', async () => {
    const { wrapper } = await mountView(AppsView)
    await wrapper.findComponent({ name: 'ElInput' }).vm.$emit('update:modelValue', 't1')
    await wrapper.findAll('button')[0].trigger('click')
    await flush()
    expect(api.listApps).toHaveBeenLastCalledWith({ tenant_code: 't1' })
  })
})

describe('ProvidersView', () => {
  it('renders the provider tables from the config payload', async () => {
    api.listProviders.mockResolvedValueOnce({
      llm: [{ name: 'deepseek', label: 'DeepSeek', configured: true, detail: 'https://api.deepseek.com/v1' }],
      retriever: [{ name: 'builtin', label: '内置', configured: true, detail: '' }],
      embedding: { name: 'hash', configured: true, detail: 'dim=256' },
      observability: { name: 'langfuse', configured: false, detail: '' },
    })
    const { wrapper } = await mountView(ProvidersView)
    expect(api.listProviders).toHaveBeenCalled()
    expect(wrapper.text()).toContain('大模型 provider')
    expect(wrapper.text()).toContain('检索 provider')
    expect(wrapper.text()).toContain('deepseek')
    expect(wrapper.text()).toContain('已配置')
  })
})

describe('McpServersView', () => {
  it('lists servers', async () => {
    const { wrapper } = await mountView(McpServersView)
    expect(api.listMcpServers).toHaveBeenCalled()
    expect(wrapper.text()).toContain('MCP')
  })
})

describe('KnowledgeView', () => {
  it('lists documents', async () => {
    const { wrapper } = await mountView(KnowledgeView)
    expect(api.listDocuments).toHaveBeenCalled()
    expect(wrapper.text()).toContain('新增文档')
  })
})

describe('GuardsView', () => {
  it('renders the process-level switches and the reply fallback', async () => {
    api.getGuardConfig.mockResolvedValueOnce({
      enabled: true,
      sensitive_enabled: false,
      quota_enabled: true,
      rate_enabled: false,
      round_enabled: true,
      daily_token_quota: 100000,
      rate_per_minute: 60,
      max_rounds: 10,
      default_reply: '抱歉，我无法回答该问题。',
    })
    const { wrapper } = await mountView(GuardsView)
    expect(api.getGuardConfig).toHaveBeenCalled()
    expect(api.listSensitiveWords).toHaveBeenCalled()
    expect(wrapper.text()).toContain('护栏总开关')
    expect(wrapper.text()).toContain('100000')
    expect(wrapper.text()).toContain('抱歉，我无法回答该问题。')
    expect(wrapper.text()).toContain('双跑期与 Java 侧保持一致')
  })
})

describe('AccountsView', () => {
  it('loads users and roles and offers the create dialogs to writers', async () => {
    const { wrapper } = await mountView(AccountsView)
    expect(api.listUsers).toHaveBeenCalled()
    expect(api.listRoles).toHaveBeenCalled()
    expect(wrapper.text()).toContain('账号')
    expect(wrapper.text()).toContain('角色')
    expect(wrapper.text()).toContain('新增账号')
    expect(wrapper.text()).toContain('新增角色')
  })

  it('hides write actions from readers', async () => {
    const { wrapper } = await mountView(AccountsView, { profile: { username: 'v', permissions: ['app:read'] } })
    expect(wrapper.text()).not.toContain('新增账号')
  })
})

describe('MetricsView', () => {
  it('renders the six summary cards and three trend charts', async () => {
    api.metricsOverview.mockResolvedValueOnce({
      range: { days: 7, start: '2026-10-01', end: '2026-10-07' },
      conversations: { total: 12, series: [{ date: '2026-10-01', count: 2 }] },
      messages: { total: 30, user: 15, assistant: 15 },
      satisfaction: { like: 4, dislike: 1, rate: 0.8 },
      tokens: { total: 900, series: [{ date: '2026-10-01', count: 100 }] },
      errors: { total: 1, rate: 0.01, series: [{ date: '2026-10-01', count: 1 }] },
    })
    const { wrapper } = await mountView(MetricsView)
    expect(api.metricsOverview).toHaveBeenCalled()
    expect(wrapper.text()).toContain('会话数')
    expect(wrapper.text()).toContain('Token 总量')
    expect(wrapper.text()).toContain('异常率')
    expect(wrapper.text()).toContain('80.0%')
    expect(wrapper.text()).toContain('2026-10-01 ~ 2026-10-07')
    expect(wrapper.findAllComponents({ name: 'BarChart' })).toHaveLength(3)
  })
})
