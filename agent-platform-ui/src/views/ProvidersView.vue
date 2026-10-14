<script setup>
import { computed } from 'vue'

import { listProviders } from '@/api'
import { useTable } from '@/composables/useTable'

const { data, loading } = useTable(() => listProviders())
const llm = computed(() => (data.value && data.value.llm) || [])
const retriever = computed(() => (data.value && data.value.retriever) || [])
const embedding = computed(() => (data.value && data.value.embedding) || {})
const observability = computed(() => (data.value && data.value.observability) || {})
</script>

<template>
  <div v-loading="loading">
    <el-card shadow="never" class="card">
      <template #header>大模型 provider</template>
      <el-table :data="llm" border>
        <el-table-column prop="name" label="名称" width="180" />
        <el-table-column prop="label" label="说明" min-width="200" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.configured ? 'success' : 'info'" size="small">
              {{ row.configured ? '已配置' : '未配置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="detail" label="地址" min-width="220" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-card shadow="never" class="card">
      <template #header>检索 provider</template>
      <el-table :data="retriever" border>
        <el-table-column prop="name" label="名称" width="180" />
        <el-table-column prop="label" label="说明" min-width="200" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.configured ? 'success' : 'info'" size="small">
              {{ row.configured ? '已配置' : '未配置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="detail" label="地址" min-width="220" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-descriptions :column="2" border class="card">
      <el-descriptions-item label="向量化">
        {{ embedding.name || '-' }}（{{ embedding.configured ? '已配置' : '未配置' }}）
      </el-descriptions-item>
      <el-descriptions-item label="向量化明细">{{ embedding.detail || '-' }}</el-descriptions-item>
      <el-descriptions-item label="可观测">
        {{ observability.name || '-' }}（{{ observability.configured ? '已配置' : '未配置' }}）
      </el-descriptions-item>
      <el-descriptions-item label="Langfuse 地址">{{ observability.detail || '-' }}</el-descriptions-item>
    </el-descriptions>
  </div>
</template>

<style scoped>
.card {
  margin-bottom: 16px;
}
</style>
