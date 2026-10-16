<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import { retrieveDataset } from '@/api'

const props = defineProps({
  visible: { type: Boolean, default: false },
  dataset: { type: Object, default: null },
})
const emit = defineEmits(['update:visible'])

const query = ref('')
const topK = ref(null)
const scoreThreshold = ref(null)
const hits = ref([])
const running = ref(false)

async function run() {
  if (!props.dataset) {
    return
  }
  if (!query.value.trim()) {
    ElMessage.warning('请输入检索问题')
    return
  }
  running.value = true
  try {
    const data = await retrieveDataset(props.dataset.uuid, {
      query: query.value,
      top_k: topK.value || null,
      score_threshold: scoreThreshold.value,
    })
    hits.value = (data && data.hits) || []
  } catch (error) {
    ElMessage.error(error.message || '召回失败')
  } finally {
    running.value = false
  }
}

function close(value) {
  emit('update:visible', value)
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="dataset ? `召回测试 · ${dataset.name}` : '召回测试'"
    width="720px"
    @update:model-value="close"
  >
    <el-form label-position="top" size="small">
      <el-form-item label="检索问题">
        <el-input v-model="query" placeholder="输入问题，回车检索" @keyup.enter="run" />
      </el-form-item>
      <div class="hits__params">
        <el-form-item label="top_k（留空用知识库配置）">
          <el-input-number v-model="topK" :min="1" controls-position="right" />
        </el-form-item>
        <el-form-item label="score_threshold（留空不限制）">
          <el-input-number v-model="scoreThreshold" :step="0.01" controls-position="right" />
        </el-form-item>
      </div>
    </el-form>

    <el-table :data="hits" border max-height="360">
      <el-table-column type="index" label="#" width="50" />
      <el-table-column prop="document_name" label="文档" width="140" show-overflow-tooltip />
      <el-table-column prop="score" label="分数" width="90" />
      <el-table-column prop="content" label="内容" min-width="260" show-overflow-tooltip />
    </el-table>

    <template #footer>
      <el-button @click="close(false)">关闭</el-button>
      <el-button type="primary" :loading="running" @click="run">检索</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.hits__params {
  display: flex;
  gap: 16px;
}
</style>
