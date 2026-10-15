<script setup>
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { createTool, deleteTool, listTools, testTool, updateTool } from '@/api'
import { useTable } from '@/composables/useTable'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const filters = reactive({ tenant_code: '' })
const { rows, loading, reload } = useTable(() => listTools({ tenant_code: filters.tenant_code }))

const dialogVisible = ref(false)
const saving = ref(false)
const editingUuid = ref('')
const form = reactive({
  name: '',
  label: '',
  category: '',
  server: '',
  kind: 'http',
  http_method: 'POST',
  http_path: '',
  params: '[]',
  retry_attempts: null,
  retry_backoff_seconds: null,
  fallback: '{}',
})

const testVisible = ref(false)
const testing = ref(false)
const testTarget = ref(null)
const testArgs = ref('{}')
const testResult = ref('')

function openCreate() {
  editingUuid.value = ''
  Object.assign(form, {
    name: '', label: '', category: '', server: '', kind: 'http', http_method: 'POST',
    http_path: '', params: '[]', retry_attempts: null, retry_backoff_seconds: null, fallback: '{}',
  })
  dialogVisible.value = true
}

function openEdit(row) {
  editingUuid.value = row.uuid
  Object.assign(form, {
    name: row.name,
    label: row.label,
    category: row.category,
    server: row.server,
    kind: row.kind,
    http_method: row.http_method,
    http_path: row.http_path,
    params: JSON.stringify(row.params || [], null, 2),
    retry_attempts: row.retry_attempts,
    retry_backoff_seconds: row.retry_backoff_seconds,
    fallback: JSON.stringify(row.fallback || {}, null, 2),
  })
  dialogVisible.value = true
}

async function submit() {
  if (!form.name) {
    ElMessage.warning('请填写工具名')
    return
  }
  let params = []
  let fallback = {}
  try {
    params = form.params ? JSON.parse(form.params) : []
    fallback = form.fallback ? JSON.parse(form.fallback) : {}
  } catch {
    ElMessage.warning('参数 schema / 兜底策略须为合法 JSON')
    return
  }
  const payload = {
    name: form.name,
    label: form.label,
    category: form.category,
    server: form.server,
    kind: form.kind,
    http_method: form.http_method,
    http_path: form.http_path,
    params,
    retry_attempts: form.retry_attempts,
    retry_backoff_seconds: form.retry_backoff_seconds,
    fallback,
  }
  saving.value = true
  try {
    if (editingUuid.value) {
      await updateTool(editingUuid.value, payload)
    } else {
      await createTool(payload)
    }
    dialogVisible.value = false
    ElMessage.success('已保存')
    await reload()
  } catch (error) {
    ElMessage.error(error.message || '保存失败')
  } finally {
    saving.value = false
  }
}

function openTest(row) {
  testTarget.value = row
  const sample = {}
  ;(row.params || []).forEach((item) => {
    if (item.required) {
      sample[item.name] = item.type === 'number' ? 1 : item.type === 'object' ? {} : ''
    }
  })
  testArgs.value = JSON.stringify(sample, null, 2)
  testResult.value = ''
  testVisible.value = true
}

async function runTest() {
  let args = {}
  try {
    args = testArgs.value ? JSON.parse(testArgs.value) : {}
  } catch {
    ElMessage.warning('参数须为合法 JSON')
    return
  }
  testing.value = true
  testResult.value = ''
  try {
    const data = await testTool(testTarget.value.uuid, { args })
    testResult.value = JSON.stringify(data && data.result, null, 2)
    ElMessage.success('调用成功')
  } catch (error) {
    testResult.value = error.message || '调用失败'
    ElMessage.error(error.message || '调用失败')
  } finally {
    testing.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确认删除工具「${row.label || row.name}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteTool(row.uuid)
    ElMessage.success('已删除')
    await reload()
  } catch (error) {
    ElMessage.error(error.message || '删除失败')
  }
}
</script>

<template>
  <div>
    <div class="toolbar">
      <el-input v-model="filters.tenant_code" placeholder="租户编码" class="toolbar__input" @keyup.enter="reload()" />
      <el-button @click="reload()">查询</el-button>
      <el-button v-if="auth.can('tool:write')" type="primary" @click="openCreate">新增工具</el-button>
    </div>
    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="name" label="工具名" width="200" />
      <el-table-column prop="label" label="说明" min-width="180" show-overflow-tooltip />
      <el-table-column prop="category" label="分类" width="100" />
      <el-table-column prop="server" label="服务" width="120" />
      <el-table-column prop="kind" label="类型" width="80" />
      <el-table-column prop="http_path" label="路径" min-width="180" show-overflow-tooltip />
      <el-table-column label="参数" width="90">
        <template #default="{ row }">{{ (row.params || []).length }} 个</template>
      </el-table-column>
      <el-table-column label="重试" width="80">
        <template #default="{ row }">{{ row.retry_attempts ?? '默认' }}</template>
      </el-table-column>
      <el-table-column label="兜底" width="80">
        <template #default="{ row }">
          <el-tag :type="row.fallback && row.fallback.enabled ? 'success' : 'info'" size="small">
            {{ row.fallback && row.fallback.enabled ? '开' : '关' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button v-if="auth.can('tool:write')" link type="primary" @click="openTest(row)">试调</el-button>
          <el-button v-if="auth.can('tool:write')" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="auth.can('tool:write')" link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editingUuid ? '编辑工具' : '新增工具'" width="760px">
      <el-form label-position="top">
        <el-form-item label="工具名（MCP 工具名）">
          <el-input v-model="form.name" :disabled="Boolean(editingUuid)" placeholder="如 gov.business.query" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.label" />
        </el-form-item>
        <el-form-item label="分类">
          <el-input v-model="form.category" placeholder="query / validate / ..." />
        </el-form-item>
        <el-form-item label="服务名（AP_TOOL_SERVERS 的 key 或 MCP Server 名）">
          <el-input v-model="form.server" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.kind">
            <el-option label="http" value="http" />
            <el-option label="mcp" value="mcp" />
          </el-select>
        </el-form-item>
        <el-form-item label="HTTP 方法">
          <el-select v-model="form.http_method">
            <el-option v-for="item in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="HTTP 路径（留空用 /tools/&lt;工具名&gt;）">
          <el-input v-model="form.http_path" />
        </el-form-item>
        <el-form-item label="参数 schema（JSON 数组：name/type/required/enum）">
          <el-input v-model="form.params" type="textarea" :rows="5" />
        </el-form-item>
        <el-form-item label="重试次数（留空用全局 AP_TOOL_RETRY_ATTEMPTS）">
          <el-input-number v-model="form.retry_attempts" :min="0" controls-position="right" />
        </el-form-item>
        <el-form-item label="重试退避基数秒（留空用全局）">
          <el-input-number v-model="form.retry_backoff_seconds" :min="0" :step="0.1" controls-position="right" />
        </el-form-item>
        <el-form-item label="兜底策略（JSON：enabled/mode(empty|value|text)/value）">
          <el-input v-model="form.fallback" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="testVisible" :title="`试调：${testTarget ? testTarget.name : ''}`" width="640px">
      <el-form label-position="top">
        <el-form-item label="调用参数（JSON）">
          <el-input v-model="testArgs" type="textarea" :rows="6" />
        </el-form-item>
      </el-form>
      <div v-if="testResult" class="result">
        <p>返回</p>
        <pre>{{ testResult }}</pre>
      </div>
      <template #footer>
        <el-button @click="testVisible = false">关闭</el-button>
        <el-button type="primary" :loading="testing" @click="runTest">调用</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.toolbar__input {
  width: 200px;
}

.result {
  margin-top: 8px;
}

.result p {
  margin: 0 0 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.result pre {
  max-height: 240px;
  overflow: auto;
  margin: 0;
  padding: 8px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
}
</style>
