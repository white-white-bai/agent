import { request, streamRequest, uploadRequest } from './client'

// 账号
export const login = (username, password) => request('/admin/login', { method: 'POST', body: { username, password } })
export const fetchMe = () => request('/admin/me')
export const listUsers = () => request('/admin/users')
export const createUser = (body) => request('/admin/users', { method: 'POST', body })
export const updateUser = (uuid, body) => request(`/admin/users/${uuid}`, { method: 'PUT', body })
export const deleteUser = (uuid) => request(`/admin/users/${uuid}`, { method: 'DELETE' })
export const listRoles = () => request('/admin/roles')
export const createRole = (body) => request('/admin/roles', { method: 'POST', body })
export const deleteRole = (code) => request(`/admin/roles/${code}`, { method: 'DELETE' })

// 应用注册表
export const listApps = (params) => request('/admin/apps', { params })
export const getApp = (uuid) => request(`/admin/apps/${uuid}`)
export const createApp = (body) => request('/admin/apps', { method: 'POST', body })
export const updateApp = (uuid, body) => request(`/admin/apps/${uuid}`, { method: 'PUT', body })
export const deleteApp = (uuid) => request(`/admin/apps/${uuid}`, { method: 'DELETE' })

// 图：草稿 / 发布 / 版本 / 回滚 / 导入
export const getGraph = (uuid) => request(`/admin/apps/${uuid}/graph`)
export const saveGraphDraft = (uuid, definition) =>
  request(`/admin/apps/${uuid}/graph/draft`, { method: 'PUT', body: { definition } })
export const publishGraph = (uuid, body = {}) => request(`/admin/apps/${uuid}/graph/publish`, { method: 'POST', body })
export const listGraphVersions = (uuid) => request(`/admin/apps/${uuid}/graph/versions`)
export const rollbackGraph = (uuid, version) =>
  request(`/admin/apps/${uuid}/graph/rollback`, { method: 'POST', body: { version } })
export const importGraph = (uuid, body) => request(`/admin/apps/${uuid}/graph/import`, { method: 'POST', body })
export const importGraphFile = (uuid, formData) =>
  request(`/admin/apps/${uuid}/graph/import/file`, { method: 'POST', body: formData })
export const runNode = (uuid, body) => request(`/admin/apps/${uuid}/graph/run-node`, { method: 'POST', body })
export const runGraphStream = (uuid, body, onEvent, options) =>
  streamRequest(`/admin/apps/${uuid}/graph/run`, body, onEvent, options)
export const listGraphOptions = (params) => request('/admin/graphs', { params })

// HITL 运行记录
export const listRuns = (params) => request('/admin/runs', { params })
export const getRun = (threadId) => request(`/admin/runs/${threadId}`)
export const resumeRun = (threadId, body, onEvent, options) =>
  streamRequest(`/admin/runs/${threadId}/resume`, body, onEvent, options)

// 护栏：敏感词 + 进程级开关
export const listSensitiveWords = (params) => request('/admin/sensitive-words', { params })
export const createSensitiveWord = (body) => request('/admin/sensitive-words', { method: 'POST', body })
export const deleteSensitiveWord = (id) => request(`/admin/sensitive-words/${id}`, { method: 'DELETE' })
export const getGuardConfig = () => request('/admin/guard/config')

// MCP Server
export const listMcpServers = (params) => request('/admin/mcp-servers', { params })
export const createMcpServer = (body) => request('/admin/mcp-servers', { method: 'POST', body })
export const deleteMcpServer = (uuid) => request(`/admin/mcp-servers/${uuid}`, { method: 'DELETE' })

// 知识库：知识库（数据集）/ 文档 / 分段 / 召回测试
export const listDatasets = (params) => request('/admin/datasets', { params })
export const createDataset = (body) => request('/admin/datasets', { method: 'POST', body })
export const getDataset = (uuid) => request(`/admin/datasets/${uuid}`)
export const updateDataset = (uuid, body) => request(`/admin/datasets/${uuid}`, { method: 'PUT', body })
export const deleteDataset = (uuid) => request(`/admin/datasets/${uuid}`, { method: 'DELETE' })
export const listDatasetDocuments = (uuid, params) => request(`/admin/datasets/${uuid}/documents`, { params })
export const createDatasetDocument = (uuid, body) =>
  request(`/admin/datasets/${uuid}/documents`, { method: 'POST', body })
export const uploadDatasetDocument = (uuid, formData, onProgress) =>
  uploadRequest(`/admin/datasets/${uuid}/documents/upload`, formData, { onProgress })
export const deleteDocument = (uuid) => request(`/admin/documents/${uuid}`, { method: 'DELETE' })
export const reindexDocument = (uuid) => request(`/admin/documents/${uuid}/reindex`, { method: 'POST' })
export const listSegments = (uuid, params) => request(`/admin/documents/${uuid}/segments`, { params })
export const updateSegment = (uuid, body) => request(`/admin/segments/${uuid}`, { method: 'PUT', body })
export const deleteSegment = (uuid) => request(`/admin/segments/${uuid}`, { method: 'DELETE' })
export const retrieveDataset = (uuid, body) => request(`/admin/datasets/${uuid}/retrieve`, { method: 'POST', body })
export const previewChunks = (formData) => request('/admin/knowledge/preview', { method: 'POST', body: formData })

// 智能体
export const listAgents = (params) => request('/admin/agents', { params })
export const createAgent = (body) => request('/admin/agents', { method: 'POST', body })
export const updateAgent = (uuid, body) => request(`/admin/agents/${uuid}`, { method: 'PUT', body })
export const deleteAgent = (uuid) => request(`/admin/agents/${uuid}`, { method: 'DELETE' })

// 工具声明
export const listTools = (params) => request('/admin/tools', { params })
export const createTool = (body) => request('/admin/tools', { method: 'POST', body })
export const updateTool = (uuid, body) => request(`/admin/tools/${uuid}`, { method: 'PUT', body })
export const deleteTool = (uuid) => request(`/admin/tools/${uuid}`, { method: 'DELETE' })
export const testTool = (uuid, body) => request(`/admin/tools/${uuid}/test`, { method: 'POST', body })

// 提示词模板
export const listPrompts = (params) => request('/admin/prompts', { params })
export const createPrompt = (body) => request('/admin/prompts', { method: 'POST', body })
export const updatePrompt = (uuid, body) => request(`/admin/prompts/${uuid}`, { method: 'PUT', body })
export const deletePrompt = (uuid) => request(`/admin/prompts/${uuid}`, { method: 'DELETE' })

// 图模板
export const listGraphTemplates = () => request('/admin/graph/templates')
export const getGraphTemplate = (key) => request(`/admin/graph/templates/${key}`)

// 模型 / 检索 provider
export const listProviders = () => request('/admin/providers')
export const getRetrievalConfig = () => request('/admin/retrieval/config')

// 用户级长期记忆
export const getMemoryConfig = () => request('/admin/memory/config')
export const listUserMemories = (params) => request('/admin/user-memories', { params })
export const listMemoryUsers = (params) => request('/admin/user-memories/users', { params })
export const createUserMemory = (body) => request('/admin/user-memories', { method: 'POST', body })
export const updateUserMemory = (uuid, body) => request(`/admin/user-memories/${uuid}`, { method: 'PUT', body })
export const deleteUserMemory = (uuid) => request(`/admin/user-memories/${uuid}`, { method: 'DELETE' })
export const recallUserMemory = (body) => request('/admin/user-memories/recall', { method: 'POST', body })
export const purgeUserMemories = (body) => request('/admin/user-memories/purge', { method: 'POST', body })

// 监控看板
export const metricsOverview = (params) => request('/admin/metrics/overview', { params })
