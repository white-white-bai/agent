import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/client', () => ({
  request: vi.fn(async () => ({ ok: true })),
  uploadRequest: vi.fn(async () => ({ ok: true })),
  streamRequest: vi.fn(async () => ({ ok: true })),
}))

import { request, streamRequest, uploadRequest } from '@/api/client'
import * as api from '@/api'

beforeEach(() => {
  request.mockClear()
  uploadRequest.mockClear()
  streamRequest.mockClear()
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
    ['listDatasets', () => api.listDatasets({ tenant_code: 't' }), '/admin/datasets', { params: { tenant_code: 't' } }],
    ['createDataset', () => api.createDataset({ name: 'n' }), '/admin/datasets', { method: 'POST', body: { name: 'n' } }],
    ['getDataset', () => api.getDataset('u'), '/admin/datasets/u', undefined],
    ['updateDataset', () => api.updateDataset('u', { name: 'n' }), '/admin/datasets/u', { method: 'PUT', body: { name: 'n' } }],
    ['deleteDataset', () => api.deleteDataset('u'), '/admin/datasets/u', { method: 'DELETE' }],
    ['listDatasetDocuments', () => api.listDatasetDocuments('u', { page: 1 }), '/admin/datasets/u/documents', { params: { page: 1 } }],
    ['createDatasetDocument', () => api.createDatasetDocument('u', { content: 'c' }), '/admin/datasets/u/documents', { method: 'POST', body: { content: 'c' } }],
    ['deleteDocument', () => api.deleteDocument('u'), '/admin/documents/u', { method: 'DELETE' }],
    ['reindexDocument', () => api.reindexDocument('u'), '/admin/documents/u/reindex', { method: 'POST' }],
    ['listSegments', () => api.listSegments('u', { page: 1 }), '/admin/documents/u/segments', { params: { page: 1 } }],
    ['updateSegment', () => api.updateSegment('s', { enabled: 0 }), '/admin/segments/s', { method: 'PUT', body: { enabled: 0 } }],
    ['deleteSegment', () => api.deleteSegment('s'), '/admin/segments/s', { method: 'DELETE' }],
    ['retrieveDataset', () => api.retrieveDataset('u', { query: 'q' }), '/admin/datasets/u/retrieve', { method: 'POST', body: { query: 'q' } }],
    ['previewChunks', () => api.previewChunks('fd'), '/admin/knowledge/preview', { method: 'POST', body: 'fd' }],
    ['listProviders', () => api.listProviders(), '/admin/providers', undefined],
    ['listGraphOptions', () => api.listGraphOptions({ tenant_code: 't' }), '/admin/graphs', { params: { tenant_code: 't' } }],
    ['listRuns', () => api.listRuns({ status: 'interrupted' }), '/admin/runs', { params: { status: 'interrupted' } }],
    ['getRun', () => api.getRun('t1'), '/admin/runs/t1', undefined],
    ['getMemoryConfig', () => api.getMemoryConfig(), '/admin/memory/config', undefined],
    ['listUserMemories', () => api.listUserMemories({ user_key: 'u' }), '/admin/user-memories', { params: { user_key: 'u' } }],
    ['listMemoryUsers', () => api.listMemoryUsers({ tenant_code: 't' }), '/admin/user-memories/users', { params: { tenant_code: 't' } }],
    ['createUserMemory', () => api.createUserMemory({ content: 'c' }), '/admin/user-memories', { method: 'POST', body: { content: 'c' } }],
    ['updateUserMemory', () => api.updateUserMemory('m1', { content: 'c' }), '/admin/user-memories/m1', { method: 'PUT', body: { content: 'c' } }],
    ['deleteUserMemory', () => api.deleteUserMemory('m1'), '/admin/user-memories/m1', { method: 'DELETE' }],
    ['recallUserMemory', () => api.recallUserMemory({ query: 'q' }), '/admin/user-memories/recall', { method: 'POST', body: { query: 'q' } }],
    ['purgeUserMemories', () => api.purgeUserMemories({ user_key: 'u' }), '/admin/user-memories/purge', { method: 'POST', body: { user_key: 'u' } }],
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

  it('uploadDatasetDocument posts FormData through uploadRequest with a progress callback', async () => {
    const onProgress = () => {}
    await api.uploadDatasetDocument('u', 'fd', onProgress)
    expect(uploadRequest).toHaveBeenCalledWith('/admin/datasets/u/documents/upload', 'fd', { onProgress })
  })

  it('resumeRun streams through streamRequest', async () => {
    const onEvent = () => {}
    const options = { signal: null }
    await api.resumeRun('t1', { action: 'approve' }, onEvent, options)
    expect(streamRequest).toHaveBeenCalledWith('/admin/runs/t1/resume', { action: 'approve' }, onEvent, options)
  })
})
