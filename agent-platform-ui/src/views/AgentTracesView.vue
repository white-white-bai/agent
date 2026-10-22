<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

import { getAgentTraceStats, listAgentTraces } from '@/api'
import { useTable } from '@/composables/useTable'

const filters = reactive({ tenant_code: '', app_uuid: '', status: '' })
const { data, loading, reload } = useTable(() => listAgentTraces({ ...filters }))
const rows = computed(() => (data.value && data.value.items) || [])
const total = computed(() => (data.value && data.value.total) || 0)
const stats = ref(null)
const detailVisible = ref(false)
const current = ref(null)

async function loadStats() {
  try {
    stats.value = await getAgentTraceStats({ ...filters })
  } catch {
    stats.value = null
  }
}

function refresh() {
  reload()
  loadStats()
}

onMounted(loadStats)

function openDetail(row) {
  current.value = row
  detailVisible.value = true
}

function formatJson(value) {
  try {
    return JSON.stringify(value || [], null, 2)
  } catch {
    return String(value || '')
  }
}
</script>

<template>
  <div>
    <div class="toolbar">
      <el-input v-model="filters.tenant_code" placeholder="租户编码" class="toolbar__input" @keyup.enter="refresh" />
      <el-input v-model="filters.app_uuid" placeholder="应用 uuid" class="toolbar__input" @keyup.enter="refresh" />
      <el-select v-model="filters.status" class="toolbar__input" clearable placeholder="状态">
        <el-option label="完成" value="completed" />
        <el-option label="中断" value="interrupted" />
        <el-option label="失败" value="failed" />
      </el-select>
      <el-button @click="refresh">查询</el-button>
    </div>

    <div v-if="stats" class="stats">
      <div class="stats__card"><span>总轨迹</span><strong>{{ stats.total }}</strong></div>
      <div class="stats__card"><span>平均耗时</span><strong>{{ stats.avg_duration_ms }} ms</strong></div>
      <div class="stats__card"><span>P95 耗时</span><strong>{{ stats.p95_duration_ms }} ms</strong></div>
      <div class="stats__card"><span>平均工具数</span><strong>{{ stats.avg_tool_calls }}</strong></div>
      <div class="stats__card"><span>平均字符</span><strong>{{ stats.avg_token_chars }}</strong></div>
      <div class="stats__tools">
        <span>工具 Top：</span>
        <el-tag v-for="item in stats.top_tools || []" :key="item.tool" class="stats__tag">
          {{ item.tool }} × {{ item.count }}
        </el-tag>
        <span v-if="!(stats.top_tools || []).length">-</span>
      </div>
    </div>

    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="created_at" label="时间" width="180" />
      <el-table-column prop="tenant_code" label="租户" width="120" />
      <el-table-column prop="app_uuid" label="应用" width="180" show-overflow-tooltip />
      <el-table-column prop="query" label="问题" min-width="220" show-overflow-tooltip />
      <el-table-column prop="tool_calls" label="工具路径" min-width="220">
        <template #default="{ row }">{{ (row.tool_calls || []).join(' → ') }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100" />
      <el-table-column prop="duration_ms" label="耗时(ms)" width="100" />
      <el-table-column label="操作" width="90">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>
    <p class="agent-traces__total">共 {{ total }} 条</p>

    <el-dialog v-model="detailVisible" title="Agent 轨迹详情" width="760px">
      <template v-if="current">
        <p><strong>问题：</strong>{{ current.query }}</p>
        <p><strong>回答：</strong>{{ current.answer }}</p>
        <p><strong>工具：</strong>{{ (current.tool_calls || []).join(' → ') || '-' }}</p>
        <pre class="agent-traces__json">{{ formatJson(current.tool_events) }}</pre>
      </template>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
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
  flex-wrap: wrap;
}

.toolbar__input {
  width: 180px;
}

.stats {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.stats__card {
  display: flex;
  flex-direction: column;
  min-width: 110px;
  padding: 8px 12px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.stats__card strong {
  margin-top: 4px;
  color: var(--el-text-color-primary);
  font-size: 18px;
}

.stats__tools {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.stats__tag {
  margin-right: 4px;
}

.agent-traces__total {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.agent-traces__json {
  max-height: 320px;
  overflow: auto;
  padding: 8px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  white-space: pre-wrap;
}
</style>
