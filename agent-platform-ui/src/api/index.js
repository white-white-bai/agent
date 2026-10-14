import { request } from './client'

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

// 护栏：敏感词 + 进程级开关
export const listSensitiveWords = (params) => request('/admin/sensitive-words', { params })
export const createSensitiveWord = (body) => request('/admin/sensitive-words', { method: 'POST', body })
export const deleteSensitiveWord = (id) => request(`/admin/sensitive-words/${id}`, { method: 'DELETE' })
export const getGuardConfig = () => request('/admin/guard/config')

// MCP Server
export const listMcpServers = (params) => request('/admin/mcp-servers', { params })
export const createMcpServer = (body) => request('/admin/mcp-servers', { method: 'POST', body })
export const deleteMcpServer = (uuid) => request(`/admin/mcp-servers/${uuid}`, { method: 'DELETE' })

// 知识库文档
export const listDocuments = (params) => request('/admin/documents', { params })
export const createDocument = (body) => request('/admin/documents', { method: 'POST', body })
export const deleteDocument = (uuid) => request(`/admin/documents/${uuid}`, { method: 'DELETE' })

// 模型 / 检索 provider
export const listProviders = () => request('/admin/providers')

// 监控看板
export const metricsOverview = (params) => request('/admin/metrics/overview', { params })
