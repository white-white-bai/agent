<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { listRuns, resumeRun } from '@/api'
import { useTable } from '@/composables/useTable'
import { useAuthStore } from '@/stores/auth'
import { formatRunOutput } from '@/utils/run'

const auth = useAuthStore()
const filters = reactive({ tenant_code: '', status: 'interrupted' })
const { data, loading, reload } = useTable(() => listRuns({ ...filters }))
const rows = computed(() => data.value || [])

const dialogVisible = ref(false)
const current = ref(null)
const action = ref('approve')
const payloadText = ref('{}')
const busy = ref(false)
const output = ref('')
const error = ref('')

const STATUS_TYPES = {
  running: 'info',
  interrupted: 'warning',
  completed: 'success',
  failed: 'danger',
}

function openResume(row) {
  current.value = row
  action.value = 'approve'
  payloadText.value = '{}'
  output.value = ''
  error.value = ''
  dialogVisible.value = true
}

async function submit() {
  let payload = {}
  try {
    payload = payloadText.value ? JSON.parse(payloadText.value) : {}
  } catch {
    ElMessage.warning('payload 须为合法 JSON')
    return
  }
  busy.value = true
  error.value = ''
  output.value = ''
  try {
    await resumeRun(current.value.thread_id, { action: action.value, payload }, (event) => {
      if (!event || !event.type) {
        return
      }
      if (event.type === 'token') {
        output.value += event.content || ''
      } else if (event.type === 'final') {
        output.value = event.answer || output.value
      } else if (event.type === 'interrupt') {
        error.value = '审批后再次进入等待状态'
      } else if (event.type === 'error') {
        error.value = event.message || '恢复失败'
      }
    })
    await reload()
  } catch (err) {
    error.value = err.message || '恢复失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div>
    <div class="toolbar">
      <el-input v-model="filters.tenant_code" placeholder="租户编码" class="toolbar__input" @keyup.enter="reload" />
      <el-select v-model="filters.status" class="toolbar__input" clearable placeholder="状态">
        <el-option label="等待审批" value="interrupted" />
        <el-option label="运行中" value="running" />
        <el-option label="已完成" value="completed" />
        <el-option label="失败" value="failed" />
      </el-select>
      <el-button @click="reload">查询</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="status" label="状态" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="STATUS_TYPES[row.status] || 'info'">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="app_uuid" label="应用" width="180" show-overflow-tooltip />
      <el-table-column prop="thread_id" label="thread_id" min-width="220" show-overflow-tooltip />
      <el-table-column prop="created_by" label="发起人" width="120" />
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="row.status === 'interrupted' && auth.can('graph:write')"
            link
            type="primary"
            @click="openResume(row)"
          >审批/恢复</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" title="审批 / 恢复运行" width="620px">
      <p class="runs__thread">{{ current && current.thread_id }}</p>
      <el-form label-position="top">
        <el-form-item label="动作">
          <el-radio-group v-model="action">
            <el-radio-button value="approve">通过</el-radio-button>
            <el-radio-button value="reject">驳回</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="payload（JSON，可空）">
          <el-input v-model="payloadText" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <el-alert v-if="error" type="error" :closable="false" show-icon>{{ error }}</el-alert>
      <pre v-if="output" class="runs__output">{{ formatRunOutput(output) }}</pre>
      <template #footer>
        <el-button @click="dialogVisible = false">关闭</el-button>
        <el-button type="primary" :loading="busy" @click="submit">提交并继续</el-button>
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

.runs__thread {
  margin: 0 0 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  word-break: break-all;
}

.runs__output {
  max-height: 200px;
  overflow: auto;
  margin: 8px 0 0;
  padding: 8px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  white-space: pre-wrap;
}
</style>
