<script setup>
import { computed, reactive } from 'vue'

import { listToolAudits } from '@/api'
import { useTable } from '@/composables/useTable'

const filters = reactive({ tenant_code: '', tool_name: '', status: '' })
const { data, loading, reload } = useTable(() => listToolAudits({ ...filters }))
const rows = computed(() => (data.value && data.value.items) || [])
const total = computed(() => (data.value && data.value.total) || 0)

function formatArgs(value) {
  try {
    return JSON.stringify(value || {}, null, 0)
  } catch {
    return String(value || '')
  }
}
</script>

<template>
  <div>
    <div class="toolbar">
      <el-input v-model="filters.tenant_code" placeholder="租户编码" class="toolbar__input" @keyup.enter="reload" />
      <el-input v-model="filters.tool_name" placeholder="工具名" class="toolbar__input" @keyup.enter="reload" />
      <el-select v-model="filters.status" class="toolbar__input" clearable placeholder="状态">
        <el-option label="成功" value="ok" />
        <el-option label="失败" value="error" />
      </el-select>
      <el-button @click="reload">查询</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="created_at" label="时间" width="180" />
      <el-table-column prop="tenant_code" label="租户" width="130" />
      <el-table-column prop="tool_name" label="工具" width="180" show-overflow-tooltip />
      <el-table-column prop="server" label="服务" width="140" show-overflow-tooltip />
      <el-table-column prop="status" label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'ok' ? 'success' : 'danger'">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="duration_ms" label="耗时(ms)" width="100" />
      <el-table-column prop="args" label="参数" min-width="260" show-overflow-tooltip>
        <template #default="{ row }">{{ formatArgs(row.args) }}</template>
      </el-table-column>
      <el-table-column prop="error" label="错误" min-width="220" show-overflow-tooltip />
    </el-table>
    <p class="tool-audits__total">共 {{ total }} 条</p>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.toolbar__input {
  width: 180px;
}

.tool-audits__total {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
