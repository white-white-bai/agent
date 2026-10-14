import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn() } }))

import { ElMessage } from 'element-plus'
import { useTable } from '@/composables/useTable'

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

beforeEach(() => {
  ElMessage.error.mockClear()
})

describe('useTable', () => {
  it('loads immediately and exposes rows for an array payload', async () => {
    const loader = vi.fn(async () => [{ id: 1 }])
    const table = useTable(loader)
    expect(table.loading.value).toBe(true)
    await flush()
    expect(loader).toHaveBeenCalledTimes(1)
    expect(table.loading.value).toBe(false)
    expect(table.error.value).toBe('')
    expect(table.rows.value).toEqual([{ id: 1 }])
  })

  it('keeps a non-array payload in data while rows stays empty', async () => {
    const table = useTable(async () => ({ total: 1 }))
    await flush()
    expect(table.data.value).toEqual({ total: 1 })
    expect(table.rows.value).toEqual([])
  })

  it('forwards params to the loader on reload', async () => {
    const loader = vi.fn(async () => [])
    const table = useTable(loader)
    await flush()
    await table.reload({ tenant_code: 't1' })
    expect(loader).toHaveBeenLastCalledWith({ tenant_code: 't1' })
    expect(loader).toHaveBeenCalledTimes(2)
  })

  it('captures the error message and notifies the user', async () => {
    const loader = vi.fn(async () => {
      throw new Error('boom')
    })
    const table = useTable(loader)
    await flush()
    expect(table.error.value).toBe('boom')
    expect(table.data.value).toBeNull()
    expect(table.rows.value).toEqual([])
    expect(table.loading.value).toBe(false)
    expect(ElMessage.error).toHaveBeenCalledWith('boom')
  })

  it('falls back to a generic message for a non-Error rejection', async () => {
    const table = useTable(async () => {
      throw {}
    })
    await flush()
    expect(table.error.value).toBe('加载失败')
  })

  it('skips the initial load when immediate is false', async () => {
    const loader = vi.fn(async () => [])
    const table = useTable(loader, { immediate: false })
    expect(loader).not.toHaveBeenCalled()
    expect(table.loading.value).toBe(false)
    await table.reload()
    expect(loader).toHaveBeenCalledTimes(1)
  })

  it('returns the loaded payload from reload', async () => {
    const table = useTable(async () => [{ id: 7 }], { immediate: false })
    await expect(table.reload()).resolves.toEqual([{ id: 7 }])
  })
})
