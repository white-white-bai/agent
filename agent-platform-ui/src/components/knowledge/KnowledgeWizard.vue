<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { createDataset, createDatasetDocument, previewChunks, uploadDatasetDocument } from '@/api'
import ChunkPreview from '@/components/knowledge/ChunkPreview.vue'
import ChunkSettingsForm from '@/components/knowledge/ChunkSettingsForm.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  tenantCode: { type: String, default: '' },
  providers: { type: Object, default: () => ({}) },
  retrieval: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:visible', 'created'])

// 与后端 DOCUMENT_SUFFIXES 保持一致
const UPLOAD_ACCEPT = '.txt,.md,.markdown,.mdx,.csv,.html,.htm,.pdf,.docx,.xlsx,.xls'
const RETRIEVAL_LABELS = { vector: '向量检索', fulltext: '全文检索', hybrid: '混合检索' }

function defaultChunkConfig() {
  return {
    separator: '\n\n',
    max_chars: 500,
    overlap_chars: 50,
    preprocess: { replace_whitespace: true, remove_urls_emails: false },
    qa_mode: false,
  }
}

const step = ref(1)
const sourceType = ref('file')
const file = ref(null)
const form = reactive({ name: '', description: '', textName: '', content: '' })
const chunkConfig = ref(defaultChunkConfig())
const indexMethod = ref('high_quality')
const retrievalMode = ref('vector')
const rerankEnabled = ref(false)
const chunks = ref([])
const total = ref(0)
const previewing = ref(false)
const saving = ref(false)

const embeddingLabel = computed(() => {
  const info = props.providers.embedding || {}
  return info.detail || info.name || '未配置'
})
const rerankLabel = computed(() => props.retrieval.rerank_model || '未配置')

watch(
  () => props.visible,
  (value) => {
    if (value) {
      reset()
    }
  },
)

function reset() {
  step.value = 1
  sourceType.value = 'file'
  file.value = null
  Object.assign(form, { name: '', description: '', textName: '', content: '' })
  chunkConfig.value = defaultChunkConfig()
  indexMethod.value = 'high_quality'
  retrievalMode.value = 'vector'
  rerankEnabled.value = false
  resetPreview()
}

function onFileChange(uploadFile) {
  file.value = uploadFile.raw
}

function nextStep() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写知识库名称')
    return
  }
  if (sourceType.value === 'file' && !file.value) {
    ElMessage.warning('请选择文件')
    return
  }
  if (sourceType.value === 'text' && !form.content.trim()) {
    ElMessage.warning('请填写文本内容')
    return
  }
  step.value = 2
}

async function doPreview() {
  const body = new FormData()
  if (sourceType.value === 'file' && file.value) {
    body.append('file', file.value)
  } else {
    body.append('text', form.content)
  }
  body.append('chunk_config', JSON.stringify(chunkConfig.value))
  previewing.value = true
  try {
    const data = await previewChunks(body)
    chunks.value = (data && data.chunks) || []
    total.value = (data && data.total) || 0
  } catch (error) {
    ElMessage.error(error.message || '预览失败')
  } finally {
    previewing.value = false
  }
}

function resetPreview() {
  chunks.value = []
  total.value = 0
}

async function finish() {
  saving.value = true
  try {
    const dataset = await createDataset({
      tenant_code: props.tenantCode,
      name: form.name,
      description: form.description,
      index_method: indexMethod.value,
      chunk_config: chunkConfig.value,
      retrieval: { mode: retrievalMode.value, rerank: rerankEnabled.value, top_k: 5 },
    })
    if (sourceType.value === 'file' && file.value) {
      const body = new FormData()
      body.append('file', file.value)
      body.append('chunk_config', JSON.stringify(chunkConfig.value))
      await uploadDatasetDocument(dataset.uuid, body)
    } else if (form.content.trim()) {
      await createDatasetDocument(dataset.uuid, {
        name: form.textName || form.name,
        content: form.content,
        chunk_config: chunkConfig.value,
      })
    }
    ElMessage.success('知识库已创建')
    emit('created')
    emit('update:visible', false)
  } catch (error) {
    ElMessage.error(error.message || '创建失败')
  } finally {
    saving.value = false
  }
}

async function finishEmpty() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写知识库名称')
    return
  }
  saving.value = true
  try {
    await createDataset({
      tenant_code: props.tenantCode,
      name: form.name,
      description: form.description,
      index_method: indexMethod.value,
      chunk_config: chunkConfig.value,
      retrieval: { mode: retrievalMode.value, rerank: rerankEnabled.value, top_k: 5 },
    })
    ElMessage.success('知识库已创建')
    emit('created')
    emit('update:visible', false)
  } catch (error) {
    ElMessage.error(error.message || '创建失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="创建知识库"
    width="1000px"
    top="6vh"
    @update:model-value="(value) => emit('update:visible', value)"
  >
    <el-steps :active="step" finish-status="success" align-center class="wizard__steps">
      <el-step title="选择数据源" />
      <el-step title="文本分段与清洗" />
      <el-step title="处理并完成" />
    </el-steps>

    <div v-if="step === 1" class="wizard__step">
      <el-form label-position="top">
        <el-form-item label="知识库名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <el-tabs v-model="sourceType">
        <el-tab-pane label="上传文件" name="file">
          <el-upload
            :auto-upload="false"
            :limit="1"
            :accept="UPLOAD_ACCEPT"
            :on-change="onFileChange"
            :on-remove="() => (file = null)"
          >
            <el-button>选择文件</el-button>
          </el-upload>
        </el-tab-pane>
        <el-tab-pane label="文本" name="text">
          <el-input v-model="form.textName" placeholder="文本名称（可选）" class="wizard__text-name" />
          <el-input v-model="form.content" type="textarea" :rows="8" placeholder="粘贴文本内容" />
        </el-tab-pane>
      </el-tabs>
    </div>

    <div v-else-if="step === 2" class="wizard__step wizard__chunk">
      <div class="wizard__left">
        <ChunkSettingsForm v-model="chunkConfig" />
        <div class="wizard__preview-actions">
          <el-button type="primary" :loading="previewing" @click="doPreview">预览块</el-button>
          <el-button @click="resetPreview">重置</el-button>
        </div>
        <el-divider />
        <el-form label-position="top" size="small">
          <el-form-item label="索引方式">
            <el-radio-group v-model="indexMethod">
              <el-radio value="high_quality">高质量（向量化，推荐）</el-radio>
              <el-radio value="economy">经济（不嵌入，仅关键词）</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="Embedding 模型">
            <el-input :model-value="embeddingLabel" disabled />
          </el-form-item>
          <el-form-item label="检索设置">
            <el-radio-group v-model="retrievalMode">
              <el-radio value="vector">向量检索</el-radio>
              <el-radio value="fulltext">全文检索</el-radio>
              <el-radio value="hybrid">混合检索</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="Rerank 模型">
            <div class="wizard__rerank">
              <el-switch v-model="rerankEnabled" />
              <el-input :model-value="rerankLabel" disabled />
            </div>
          </el-form-item>
        </el-form>
      </div>
      <div class="wizard__right">
        <ChunkPreview :chunks="chunks" :total="total" />
      </div>
    </div>

    <div v-else class="wizard__step">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="知识库名称">{{ form.name }}</el-descriptions-item>
        <el-descriptions-item label="数据源">
          {{ sourceType === 'file' ? (file ? file.name : '未选择') : form.textName || '文本' }}
        </el-descriptions-item>
        <el-descriptions-item label="索引方式">
          {{ indexMethod === 'economy' ? '经济（仅关键词）' : '高质量（向量化）' }}
        </el-descriptions-item>
        <el-descriptions-item label="分段">
          {{ chunkConfig.max_chars }} 字符 / 重叠 {{ chunkConfig.overlap_chars }} /
          {{ chunkConfig.qa_mode ? 'Q&A' : '通用' }}
        </el-descriptions-item>
        <el-descriptions-item label="检索设置">
          {{ RETRIEVAL_LABELS[retrievalMode] }}<span v-if="rerankEnabled"> + Rerank</span>
        </el-descriptions-item>
      </el-descriptions>
    </div>

    <template #footer>
      <el-button v-if="step > 1" @click="step -= 1">上一步</el-button>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button v-if="step === 1" :loading="saving" @click="finishEmpty">仅创建知识库</el-button>
      <el-button v-if="step === 1" type="primary" @click="nextStep">下一步</el-button>
      <el-button v-if="step === 2" type="primary" @click="step = 3">下一步</el-button>
      <el-button v-if="step === 3" type="primary" :loading="saving" @click="finish">保存并处理</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.wizard__steps {
  margin-bottom: 20px;
}

.wizard__chunk {
  display: flex;
  gap: 20px;
}

.wizard__left {
  width: 420px;
  flex: none;
}

.wizard__right {
  flex: 1;
  min-width: 0;
  max-height: 460px;
  overflow: auto;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  padding: 12px;
}

.wizard__preview-actions {
  margin-top: 8px;
}

.wizard__text-name {
  margin-bottom: 8px;
}

.wizard__rerank {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
</style>
