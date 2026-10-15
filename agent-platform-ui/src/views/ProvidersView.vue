<script setup>
import { computed, ref } from 'vue'

import { getRetrievalConfig, listProviders } from '@/api'
import { useTable } from '@/composables/useTable'

const { data, loading } = useTable(() => listProviders())
const llm = computed(() => (data.value && data.value.llm) || [])
const retriever = computed(() => (data.value && data.value.retriever) || [])
const embedding = computed(() => (data.value && data.value.embedding) || {})
const observability = computed(() => (data.value && data.value.observability) || {})

// 检索流水线（入库 / 粗召回 / 精召回 / 重排序）配置回显
const retrieval = ref(null)
const mb = (bytes) => `${Math.round((Number(bytes) || 0) / (1024 * 1024))} MB`

async function loadRetrieval() {
  try {
    retrieval.value = (await getRetrievalConfig()) || null
  } catch {
    retrieval.value = null
  }
}
loadRetrieval()
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

    <el-card shadow="never" class="card">
      <template #header>检索流水线（只读，改配置走 .env）</template>
      <el-descriptions v-if="retrieval" :column="2" border>
        <el-descriptions-item label="入库分块">{{ retrieval.chunk_chars }} 字 / 重叠 {{ retrieval.chunk_overlap }} 字</el-descriptions-item>
        <el-descriptions-item label="单文件上限">{{ mb(retrieval.document_max_bytes) }}</el-descriptions-item>
        <el-descriptions-item label="粗召回候选数">
          {{ retrieval.coarse_top_k > 0 ? retrieval.coarse_top_k : '同节点 top_k' }}
        </el-descriptions-item>
        <el-descriptions-item label="精召回（混合检索）">
          <el-tag :type="retrieval.hybrid_enabled ? 'success' : 'info'" size="small">
            {{ retrieval.hybrid_enabled ? '开启' : '关闭' }}
          </el-tag>
          <span v-if="retrieval.hybrid_enabled"> 关键词 top {{ retrieval.lexical_top_k }} / RRF k={{ retrieval.rrf_k }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="重排序">
          <el-tag :type="retrieval.rerank_enabled ? 'success' : 'info'" size="small">
            {{ retrieval.rerank_enabled ? '开启' : '关闭' }}
          </el-tag>
          <span v-if="retrieval.rerank_enabled"> {{ retrieval.rerank_model || 'rerank' }} @ {{ retrieval.rerank_base_url || '-' }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="重排取数">
          {{ retrieval.rerank_top_k > 0 ? retrieval.rerank_top_k : '同节点 top_k' }}
        </el-descriptions-item>
      </el-descriptions>
      <el-empty v-else description="未读取到检索配置" :image-size="60" />
    </el-card>
  </div>
</template>

<style scoped>
.card {
  margin-bottom: 16px;
}
</style>
