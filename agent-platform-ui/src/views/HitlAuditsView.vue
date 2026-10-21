<script setup>
import { computed, reactive } from 'vue'

import { listHitlActions } from '@/api'
import { useTable } from '@/composables/useTable'

const filters = reactive({ tenant_code: '', kind: '', thread_id: '' })
const { data, loading, reload } = useTable(() => listHitlActions({ ...filters }))
const rows = computed(() => (data.value && data.value.items) || [])
const total = computed(() => (data.value && data.value.total) || 0)
</script>

<template>
  <div>
    <div class="toolbar">
      <el-input v-model="filters.tenant_code" placeholder="租户编码" class="toolbar__input" @keyup.enter="reload" />
      <el-select v-model="filters.kind" class="toolbar__input" clearable placeholder="类型">
        <el-option label="图运行" value="graph" />
        <el-option label="Agent 应用" value="agent" />
      </el-select>
      <el-input v-model="filters.thread_id" placeholder="thread_id" class="toolbar__input" @keyup.enter="reload" />
      <el-button @click="reload">查询</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="created_at" label="时间" width="180" />
      <el-table-column prop="tenant_code" label="租户" width="130" />
      <el-table-column prop="kind" label="类型" width="100" />
      <el-table-column prop="thread_id" label="thread_id" min-width="220" show-overflow-tooltip />
      <el-table-column prop="interrupt_id" label="interrupt_id" min-width="180" show-overflow-tooltip />
      <el-table-column prop="decision" label="决策" width="100" />
      <el-table-column prop="status" label="状态" width="100" />
    </el-table>
    <p class="hitl-audits__total">共 {{ total }} 条</p>
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

.hitl-audits__total {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
