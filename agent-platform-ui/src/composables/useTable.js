import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

export function useTable(loader, options = {}) {
  const { immediate = true } = options
  const data = ref(null)
  const loading = ref(false)
  const error = ref('')
  const rows = computed(() => (Array.isArray(data.value) ? data.value : []))

  async function reload(params) {
    loading.value = true
    error.value = ''
    try {
      data.value = await loader(params)
    } catch (err) {
      error.value = (err && err.message) || '加载失败'
      data.value = null
      ElMessage.error(error.value)
    } finally {
      loading.value = false
    }
    return data.value
  }

  if (immediate) {
    reload()
  }

  return { data, rows, loading, error, reload }
}
