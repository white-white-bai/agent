import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/client', () => ({ request: vi.fn(async () => ({ ok: true })) }))

import { request } from '@/api/client'
import * as api from '@/api'

beforeEach(() => {
  request.mockClear()
})

describe('api endpoint map', () => {
  const cases = [
    ['login', () => api.login('u', 'p'), '/admin/login', { method: 'POST', body: { username: 'u', password: 'p' } }],
    ['fetchMe', () => api.fetchMe(), '/admin/me', undefined],
    ['listUsers', () => api.listUsers(), '/admin/users', undefined],
    ['createUser', () => api.createUser({ username: 'u' }), '/admin/users', { method: 'POST', body: { username: 'u' } }],
    ['updateUser', () => api.updateUser('x', { role_code: 'editor' }), '/admin/users/x', { method: 'PUT', body: { role_code: 'editor' } }],
    ['deleteUser', () => api.deleteUser('x'), '/admin/users/x', { method: 'DELETE' }],
    ['listRoles', () => api.listRoles(), '/admin/roles', undefined],
    ['createRole', () => api.createRole({ code: 'c' }), '/admin/roles', { method: 'POST', body: { code: 'c' } }],
    ['deleteRole', () => api.deleteRole('c'), '/admin/roles/c', { method: 'DELETE' }],
    ['listApps', () => api.listApps({ tenant_code: 't' }), '/admin/apps', { params: { tenant_code: 't' } }],
    ['getApp', () => api.getApp('u'), '/admin/apps/u', undefined],
    ['createApp', () => api.createApp({ app_id: 'a' }), '/admin/apps', { method: 'POST', body: { app_id: 'a' } }],
    ['updateApp', () => api.updateApp('u', { app_name: 'n' }), '/admin/apps/u', { method: 'PUT', body: { app_name: 'n' } }],
    ['deleteApp', () => api.deleteApp('u'), '/admin/apps/u', { method: 'DELETE' }],
    ['getGraph', () => api.getGraph('u'), '/admin/apps/u/graph', undefined],
    ['saveGraphDraft', () => api.saveGraphDraft('u', { nodes: [] }), '/admin/apps/u/graph/draft', { method: 'PUT', body: { definition: { nodes: [] } } }],
    ['publishGraph', () => api.publishGraph('u', { note: 'n' }), '/admin/apps/u/graph/publish', { method: 'POST', body: { note: 'n' } }],
    ['publishGraph default body', () => api.publishGraph('u'), '/admin/apps/u/graph/publish', { method: 'POST', body: {} }],
    ['listGraphVersions', () => api.listGraphVersions('u'), '/admin/apps/u/graph/versions', undefined],
    ['rollbackGraph', () => api.rollbackGraph('u', 2), '/admin/apps/u/graph/rollback', { method: 'POST', body: { version: 2 } }],
    ['importGraph', () => api.importGraph('u', { content: 'x' }), '/admin/apps/u/graph/import', { method: 'POST', body: { content: 'x' } }],
    ['importGraphFile', () => api.importGraphFile('u', 'fd'), '/admin/apps/u/graph/import/file', { method: 'POST', body: 'fd' }],
    ['listSensitiveWords', () => api.listSensitiveWords({ tenant_code: 't' }), '/admin/sensitive-words', { params: { tenant_code: 't' } }],
    ['createSensitiveWord', () => api.createSensitiveWord({ word: 'w' }), '/admin/sensitive-words', { method: 'POST', body: { word: 'w' } }],
    ['deleteSensitiveWord', () => api.deleteSensitiveWord(3), '/admin/sensitive-words/3', { method: 'DELETE' }],
    ['getGuardConfig', () => api.getGuardConfig(), '/admin/guard/config', undefined],
    ['listMcpServers', () => api.listMcpServers({ tenant_code: 't' }), '/admin/mcp-servers', { params: { tenant_code: 't' } }],
    ['createMcpServer', () => api.createMcpServer({ name: 's' }), '/admin/mcp-servers', { method: 'POST', body: { name: 's' } }],
    ['deleteMcpServer', () => api.deleteMcpServer('u'), '/admin/mcp-servers/u', { method: 'DELETE' }],
    ['listDocuments', () => api.listDocuments({ dataset_id: 'd' }), '/admin/documents', { params: { dataset_id: 'd' } }],
    ['createDocument', () => api.createDocument({ content: 'c' }), '/admin/documents', { method: 'POST', body: { content: 'c' } }],
    ['deleteDocument', () => api.deleteDocument('u'), '/admin/documents/u', { method: 'DELETE' }],
    ['uploadDocument', () => api.uploadDocument('fd'), '/admin/documents/upload', { method: 'POST', body: 'fd' }],
    ['listProviders', () => api.listProviders(), '/admin/providers', undefined],
    ['metricsOverview', () => api.metricsOverview({ days: 7 }), '/admin/metrics/overview', { params: { days: 7 } }],
  ]

  it.each(cases)('%s calls request correctly', async (_name, call, path, options) => {
    await call()
    if (options === undefined) {
      expect(request).toHaveBeenCalledWith(path)
    } else {
      expect(request).toHaveBeenCalledWith(path, options)
    }
  })
})
