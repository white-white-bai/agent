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
  listDatasets: vi.fn(async () => []),
  createDataset: vi.fn(async () => ({})),
  getDataset: vi.fn(async () => ({})),
  updateDataset: vi.fn(async () => ({})),
  deleteDataset: vi.fn(async () => ({})),
  listDatasetDocuments: vi.fn(async () => ({ items: [], total: 0 })),
  createDatasetDocument: vi.fn(async () => ({})),
  uploadDatasetDocument: vi.fn(async () => ({ ingest: 'sync', chunk_count: 1 })),
  deleteDocument: vi.fn(async () => ({})),
  reindexDocument: vi.fn(async () => ({ ingest: 'sync' })),
  listSegments: vi.fn(async () => ({ items: [], total: 0 })),
  updateSegment: vi.fn(async () => ({})),
  deleteSegment: vi.fn(async () => ({})),
  retrieveDataset: vi.fn(async () => ({ hits: [] })),
  previewChunks: vi.fn(async () => ({ chunks: [], total: 0 })),
  listProviders: vi.fn(async () => ({ llm: [], retriever: [], embedding: {}, observability: {} })),
  getRetrievalConfig: vi.fn(async () => null),
  listAgents: vi.fn(async () => []),
  createAgent: vi.fn(async () => ({})),
  updateAgent: vi.fn(async () => ({})),
  deleteAgent: vi.fn(async () => ({})),
  listTools: vi.fn(async () => []),
  createTool: vi.fn(async () => ({})),
  updateTool: vi.fn(async () => ({})),
  deleteTool: vi.fn(async () => ({})),
  testTool: vi.fn(async () => ({ result: {} })),
  listPrompts: vi.fn(async () => []),
  createPrompt: vi.fn(async () => ({})),
  updatePrompt: vi.fn(async () => ({})),
  deletePrompt: vi.fn(async () => ({})),
  listGraphTemplates: vi.fn(async () => []),
  getGraphTemplate: vi.fn(async () => ({ definition: {} })),
  listGraphOptions: vi.fn(async () => ({ apps: [], templates: [] })),
  listRuns: vi.fn(async () => []),
  getRun: vi.fn(async () => ({})),
  resumeRun: vi.fn(async () => ({})),
  cancelRun: vi.fn(async () => ({})),
  getMemoryConfig: vi.fn(async () => ({ enabled: false, write_enabled: false, recall_enabled: false })),
  listUserMemories: vi.fn(async () => ({ items: [], total: 0 })),
  aggregateUserMemories: vi.fn(async () => ({ user_key: 'u1', apps: [], total: 0 })),
  exportUserMemories: vi.fn(async () => ({ user_key: 'u1', items: [], total: 0 })),
  migrateUserMemories: vi.fn(async () => ({ upserted: 0, deleted: 0 })),
  importUserMemories: vi.fn(async () => ({ imported: 0, skipped: 0 })),
  listMemoryUsers: vi.fn(async () => []),
  createUserMemory: vi.fn(async () => ({})),
  updateUserMemory: vi.fn(async () => ({})),
  deleteUserMemory: vi.fn(async () => ({})),
  recallUserMemory: vi.fn(async () => ({ hits: [] })),
  purgeUserMemories: vi.fn(async () => ({ deleted: 0 })),
  rebuildUserMemoryEmbeddings: vi.fn(async () => ({ updated: 0 })),
  metricsOverview: vi.fn(async () => ({})),
  getAgentApp: vi.fn(async () => ({ status: 'draft', definition: {} })),
  saveAgentAppDraft: vi.fn(async () => ({})),
  publishAgentApp: vi.fn(async () => ({ version: 1 })),
  listAgentAppVersions: vi.fn(async () => []),
  rollbackAgentApp: vi.fn(async () => ({})),
  runAgentStream: vi.fn(async () => ({})),
  resumeAgent: vi.fn(async () => ({})),
  clearAgentMemory: vi.fn(async () => ({ cleared: true })),
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
import AgentsView from '@/views/AgentsView.vue'
import ToolsView from '@/views/ToolsView.vue'
import PromptsView from '@/views/PromptsView.vue'
import MemoryView from '@/views/MemoryView.vue'
import RunsView from '@/views/RunsView.vue'
import AgentConfigView from '@/views/AgentConfigView.vue'

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
  it('loads knowledge bases on mount and offers the create action', async () => {
    const { wrapper } = await mountView(KnowledgeView)
    expect(api.listDatasets).toHaveBeenCalled()
    expect(wrapper.text()).toContain('新建')
  })

  it('loads documents when a knowledge base is selected', async () => {
    api.listDatasets.mockResolvedValueOnce([{ uuid: 'ds1', name: '政务知识库', document_count: 2 }])
    const { wrapper } = await mountView(KnowledgeView)
    await flush()
    expect(wrapper.text()).toContain('政务知识库')
    await wrapper.find('.datasets__item').trigger('click')
    await flush()
    expect(api.listDatasetDocuments).toHaveBeenCalledWith('ds1', { page: 1, size: 50 })
  })

  it('opens the create wizard when the panel emits create', async () => {
    const { wrapper } = await mountView(KnowledgeView)
    const wizard = wrapper.findComponent({ name: 'KnowledgeWizard' })
    expect(wizard.props('visible')).toBe(false)
    wrapper.findComponent({ name: 'DatasetPanel' }).vm.$emit('create')
    await flush()
    expect(wrapper.findComponent({ name: 'KnowledgeWizard' }).props('visible')).toBe(true)
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

describe('AgentsView', () => {
  it('lists agent definitions with mode and role', async () => {
    api.listAgents.mockResolvedValueOnce([
      { uuid: 'a1', code: 'gov.intent', label: '意图识别', role: 'intent', mode: 'react', cot: true, pipeline: [] },
    ])
    const { wrapper } = await mountView(AgentsView)
    expect(api.listAgents).toHaveBeenCalled()
    expect(wrapper.text()).toContain('gov.intent')
    expect(wrapper.text()).toContain('react')
    expect(wrapper.text()).toContain('意图识别')
  })
})

describe('ToolsView', () => {
  it('lists declared tools with parameter count', async () => {
    api.listTools.mockResolvedValueOnce([
      {
        uuid: 't1',
        name: 'gov.business.query',
        label: '政务业务查询',
        kind: 'http',
        http_path: '/tools/gov.business.query',
        params: [{ name: 'keyword', type: 'string', required: true }],
        fallback: { enabled: false },
      },
    ])
    const { wrapper } = await mountView(ToolsView)
    expect(api.listTools).toHaveBeenCalled()
    expect(wrapper.text()).toContain('gov.business.query')
    expect(wrapper.text()).toContain('1 个')
  })
})

describe('PromptsView', () => {
  it('lists few-shot templates with example counts', async () => {
    api.listPrompts.mockResolvedValueOnce([
      { uuid: 'p1', code: 'fewshot.gov_intent', label: '政务意图识别', examples: [{ input: 'i', output: 'o' }] },
    ])
    const { wrapper } = await mountView(PromptsView)
    expect(api.listPrompts).toHaveBeenCalled()
    expect(wrapper.text()).toContain('fewshot.gov_intent')
    expect(wrapper.text()).toContain('政务意图识别')
  })
})

describe('MemoryView', () => {
  it('renders the read-only config and memory rows', async () => {
    api.getMemoryConfig.mockResolvedValueOnce({
      enabled: true,
      write_enabled: true,
      recall_enabled: true,
      scope: 'app',
      top_k: 5,
      max_per_user: 200,
    })
    api.listMemoryUsers.mockResolvedValueOnce([{ user_key: 'u1', count: 1 }])
    api.listUserMemories.mockResolvedValueOnce({
      items: [
        {
          uuid: 'm1',
          user_key: 'u1',
          app_uuid: 'a1',
          kind: 'preference',
          content: '喜欢简洁回答',
          importance: 0.8,
          hit_count: 0,
          updated_at: '2026-10-20',
        },
      ],
      total: 1,
    })

    const { wrapper } = await mountView(MemoryView)

    expect(api.listUserMemories).toHaveBeenCalled()
    expect(wrapper.text()).toContain('喜欢简洁回答')
    expect(wrapper.text()).toContain('新增记忆')
    expect(wrapper.text()).toContain('跨应用汇总')
    expect(wrapper.text()).toContain('导出')
    expect(wrapper.text()).toContain('导入')
    expect(wrapper.text()).toContain('批量迁移')
    expect(wrapper.text()).toContain('总闸')
  })
})

describe('RunsView', () => {
  it('lists interrupted runs and offers approval for writers', async () => {
    api.listRuns.mockResolvedValueOnce([
      {
        uuid: 'r1',
        thread_id: 'thread-1',
        status: 'interrupted',
        app_uuid: 'a1',
        created_by: 'admin',
        created_at: '2026-10-20',
      },
    ])

    const { wrapper } = await mountView(RunsView)

    expect(api.listRuns).toHaveBeenCalled()
    expect(wrapper.text()).toContain('thread-1')
    expect(wrapper.text()).toContain('interrupted')
    expect(wrapper.text()).toContain('审批/恢复')
  })
})

describe('AgentConfigView', () => {
  it('loads the agent config and offers save/publish to writers', async () => {
    api.getAgentApp.mockResolvedValueOnce({
      status: 'draft',
      definition: { name: '问答', instructions: 'hi', tools: [{ name: 'gov.lookup' }] },
    })
    const { wrapper } = await mountView(AgentConfigView, { path: '/apps/app-1/agent' })
    expect(api.getAgentApp).toHaveBeenCalled()
    expect(api.getApp).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Agent 配置')
    expect(wrapper.text()).toContain('保存草稿')
    expect(wrapper.text()).toContain('发布')
    expect(wrapper.text()).toContain('调试对话')
  })
})
