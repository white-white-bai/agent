<script setup>
import { computed, reactive } from 'vue'

import { metricsOverview } from '@/api'
import BarChart from '@/components/BarChart.vue'
import { useTable } from '@/composables/useTable'
import { formatPercent } from '@/utils/chart'

const filters = reactive({ tenant_code: '', app_uuid: '', days: 7 })
const { data, loading, reload } = useTable(() =>
  metricsOverview({ tenant_code: filters.tenant_code, app_uuid: filters.app_uuid, days: filters.days }),
)

const range = computed(() => (data.value && data.value.range) || {})
const conversations = computed(() => (data.value && data.value.conversations) || { total: 0, series: [] })
const messages = computed(() => (data.value && data.value.messages) || { total: 0, user: 0, assistant: 0 })
const satisfaction = computed(() => (data.value && data.value.satisfaction) || { like: 0, dislike: 0, rate: 0 })
const tokens = computed(() => (data.value && data.value.tokens) || { total: 0, series: [] })
const errors = computed(() => (data.value && data.value.errors) || { total: 0, rate: 0, series: [] })
</script>

<template>
  <div v-loading="loading">
    <div class="toolbar">
      <el-input v-model="filters.tenant_code" placeholder="租户编码" class="toolbar__input" @keyup.enter="reload()" />
      <el-input v-model="filters.app_uuid" placeholder="应用 uuid" class="toolbar__input" @keyup.enter="reload()" />
      <el-input-number v-model="filters.days" :min="1" :max="90" controls-position="right" />
      <el-button type="primary" @click="reload()">刷新</el-button>
      <span class="toolbar__range">{{ range.start }} ~ {{ range.end }}</span>
    </div>

    <div class="cards">
      <el-card shadow="never">
        <el-statistic title="会话数" :value="conversations.total" />
      </el-card>
      <el-card shadow="never">
        <el-statistic title="消息数" :value="messages.total" />
      </el-card>
      <el-card shadow="never">
        <el-statistic title="用户轮次" :value="messages.user" />
      </el-card>
      <el-card shadow="never">
        <el-statistic title="Token 总量" :value="tokens.total" />
      </el-card>
      <el-card shadow="never">
        <el-statistic title="点赞 / 点踩" :value="satisfaction.like" />
        <p class="sub">点踩 {{ satisfaction.dislike }}，好评率 {{ formatPercent(satisfaction.rate) }}</p>
      </el-card>
      <el-card shadow="never">
        <el-statistic title="异常数" :value="errors.total" />
        <p class="sub">异常率 {{ formatPercent(errors.rate) }}</p>
      </el-card>
    </div>

    <el-card shadow="never" class="chart-card">
      <template #header>会话趋势</template>
      <BarChart :series="conversations.series" color="#409eff" unit="会话" />
    </el-card>
    <el-card shadow="never" class="chart-card">
      <template #header>Token 消耗趋势</template>
      <BarChart :series="tokens.series" color="#e6a23c" unit="token" />
    </el-card>
    <el-card shadow="never" class="chart-card">
      <template #header>异常趋势</template>
      <BarChart :series="errors.series" color="#f56c6c" unit="异常" />
    </el-card>
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
  width: 220px;
}

.toolbar__range {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.sub {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.chart-card {
  margin-bottom: 16px;
}
</style>
