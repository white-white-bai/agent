<script setup>
import { onBeforeUnmount, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createDatasetDocument,
  deleteDataset,
  deleteDocument,
  getRetrievalConfig,
  listDatasetDocuments,
  listDatasets,
  listProviders,
  reindexDocument,
  updateDataset,
  uploadDatasetDocument,
} from '@/api'
import ChunkSettingsForm from '@/components/knowledge/ChunkSettingsForm.vue'
import DatasetPanel from '@/components/knowledge/DatasetPanel.vue'
import DocumentTable from '@/components/knowledge/DocumentTable.vue'
import HitTestDialog from '@/components/knowledge/HitTestDialog.vue'
import KnowledgeWizard from '@/components/knowledge/KnowledgeWizard.vue'
import SegmentDrawer from '@/components/knowledge/SegmentDrawer.vue'

// 与后端 DOCUMENT_SUFFIXES 保持一致
const UPLOAD_ACCEPT = '.txt,.md,.markdown,.mdx,.csv,.html,.htm,.pdf,.docx,.xlsx,.xls'
const POLL_MS = 2000

const datasets = ref([])
const datasetsLoading = ref(false)
const tenantFilter = ref('')
const selectedDataset = ref(null)
const documents = ref([])
const docsLoading = ref(false)
let pollTimer = null

const datasetDialog = ref(false)
const datasetSaving = ref(false)
const datasetForm = reactive({
  uuid: '',
  name: '',
  description: '',
  index_method: 'high_quality',
  chunk_config: {},
  retrieval_mode: 'vector',
  rerank: false,
  top_k: null,
  score_threshold: null,
})

const wizardVisible = ref(false)
const providers = ref({})
const retrievalConfig = ref({})

const uploadDialog = ref(false)
const uploading = ref(false)
const uploadFile = ref(null)
const uploadProgress = ref(0)
const uploadOverride = ref(false)
const uploadChunkConfig = ref({})

const textDialog = ref(false)
const textSaving = ref(false)
const textForm = reactive({ name: '', content: '' })

const segmentsVisible = ref(false)
const segmentDoc = ref(null)
const hitTestVisible = ref(false)

async function loadDatasets() {
  datasetsLoading.value = true
  try {
    datasets.value = (await listDatasets({ tenant_code: tenantFilter.value })) || []
    if (selectedDataset.value) {
      selectedDataset.value = datasets.value.find((item) => item.uuid === selectedDataset.value.uuid) || null
    }
  } catch (error) {
    ElMessage.error(error.message || '知识库加载失败')
  } finally {
    datasetsLoading.value = false
  }
}

async function loadDocuments() {
  if (!selectedDataset.value) {
    documents.value = []
    return
  }
  docsLoading.value = true
  try {
    const data = await listDatasetDocuments(selectedDataset.value.uuid, { page: 1, size: 50 })
    documents.value = (data && data.items) || []
    schedulePoll()
  } catch (error) {
    ElMessage.error(error.message || '文档加载失败')
  } finally {
    docsLoading.value = false
  }
}

function schedulePoll() {
  stopPoll()
  if (documents.value.some((row) => row.status === 'pending')) {
    pollTimer = setTimeout(() => {
      loadDocuments()
      loadDatasets()
    }, POLL_MS)
  }
}

function stopPoll() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

function selectDataset(uuid) {
  selectedDataset.value = datasets.value.find((item) => item.uuid === uuid) || null
  loadDocuments()
}

function openDatasetCreate() {
  wizardVisible.value = true
}

function openDatasetEdit(row) {
  const config = row.retrieval || {}
  Object.assign(datasetForm, {
    uuid: row.uuid,
    name: row.name,
    description: row.description,
    index_method: row.index_method || 'high_quality',
    chunk_config: row.chunk_config || {},
    retrieval_mode: config.mode || 'vector',
    rerank: Boolean(config.rerank),
    top_k: config.top_k ?? null,
    score_threshold: config.score_threshold ?? null,
  })
  datasetDialog.value = true
}

async function submitDataset() {
  if (!datasetForm.name.trim()) {
    ElMessage.warning('请填写知识库名称')
    return
  }
  const payload = {
    tenant_code: tenantFilter.value,
    name: datasetForm.name,
    description: datasetForm.description,
    index_method: datasetForm.index_method,
    chunk_config: datasetForm.chunk_config,
    retrieval: {
      mode: datasetForm.retrieval_mode,
      rerank: datasetForm.rerank,
      top_k: datasetForm.top_k ?? 5,
      score_threshold: datasetForm.score_threshold,
    },
  }
  datasetSaving.value = true
  try {
    await updateDataset(datasetForm.uuid, payload)
    datasetDialog.value = false
    ElMessage.success('已保存')
    await loadDatasets()
  } catch (error) {
    ElMessage.error(error.message || '保存失败')
  } finally {
    datasetSaving.value = false
  }
}

async function removeDataset(row) {
  try {
    await ElMessageBox.confirm(`确认删除知识库「${row.name}」及其文档？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteDataset(row.uuid)
    if (selectedDataset.value && selectedDataset.value.uuid === row.uuid) {
      selectedDataset.value = null
      documents.value = []
    }
    ElMessage.success('已删除')
    await loadDatasets()
  } catch (error) {
    ElMessage.error(error.message || '删除失败')
  }
}

function openUpload() {
  uploadFile.value = null
  uploadProgress.value = 0
  uploadOverride.value = false
  uploadChunkConfig.value = {}
  uploadDialog.value = true
}

function onUploadChange(file) {
  uploadFile.value = file.raw
}

async function submitUpload() {
  if (!uploadFile.value) {
    ElMessage.warning('请选择文件')
    return
  }
  const body = new FormData()
  body.append('file', uploadFile.value)
  if (uploadOverride.value) {
    body.append('chunk_config', JSON.stringify(uploadChunkConfig.value))
  }
  uploading.value = true
  uploadProgress.value = 0
  try {
    const result = await uploadDatasetDocument(selectedDataset.value.uuid, body, (value) => {
      uploadProgress.value = value
    })
    uploadDialog.value = false
    ElMessage.success(result.ingest === 'sync' ? `已入库 ${result.chunk_count} 个分段` : '已提交异步入库')
    await Promise.all([loadDatasets(), loadDocuments()])
  } catch (error) {
    ElMessage.error(error.message || '上传失败')
  } finally {
    uploading.value = false
  }
}

function openText() {
  Object.assign(textForm, { name: '', content: '' })
  textDialog.value = true
}

async function submitText() {
  if (!textForm.content.trim()) {
    ElMessage.warning('请填写文档内容')
    return
  }
  textSaving.value = true
  try {
    await createDatasetDocument(selectedDataset.value.uuid, { name: textForm.name, content: textForm.content })
    textDialog.value = false
    ElMessage.success('已入库')
    await Promise.all([loadDatasets(), loadDocuments()])
  } catch (error) {
    ElMessage.error(error.message || '入库失败')
  } finally {
    textSaving.value = false
  }
}

async function removeDocuments(rows) {
  const list = rows || []
  if (!list.length) {
    return
  }
  try {
    await ElMessageBox.confirm(`确认删除选中的 ${list.length} 篇文档？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await Promise.all(list.map((row) => deleteDocument(row.uuid)))
    ElMessage.success('已删除')
    await Promise.all([loadDatasets(), loadDocuments()])
  } catch (error) {
    ElMessage.error(error.message || '删除失败')
  }
}

async function reindex(row) {
  try {
    const result = await reindexDocument(row.uuid)
    ElMessage.success(result.ingest === 'sync' ? '已完成重传' : '已提交异步入库')
    await loadDocuments()
  } catch (error) {
    ElMessage.error(error.message || '重传失败')
  }
}

function openSegments(row) {
  segmentDoc.value = row
  segmentsVisible.value = true
}

function openHitTest() {
  hitTestVisible.value = true
}

async function loadMeta() {
  try {
    providers.value = (await listProviders()) || {}
  } catch {
    providers.value = {}
  }
  try {
    retrievalConfig.value = (await getRetrievalConfig()) || {}
  } catch {
    retrievalConfig.value = {}
  }
}

function onWizardCreated() {
  loadDatasets()
}

onBeforeUnmount(stopPoll)
loadDatasets()
loadMeta()
</script>

<template>
  <div class="kb">
    <div class="kb__bar">
      <el-input
        v-model="tenantFilter"
        placeholder="租户编码"
        class="kb__tenant"
        @keyup.enter="loadDatasets"
      />
      <el-button @click="loadDatasets">查询</el-button>
    </div>
    <div class="kb__body">
      <div class="kb__aside">
        <DatasetPanel
          :datasets="datasets"
          :selected="selectedDataset ? selectedDataset.uuid : ''"
          :loading="datasetsLoading"
          @select="selectDataset"
          @create="openDatasetCreate"
          @edit="openDatasetEdit"
          @remove="removeDataset"
        />
      </div>
      <div class="kb__main">
        <div v-if="selectedDataset" class="kb__tools">
          <el-button size="small" @click="openHitTest">召回测试</el-button>
        </div>
        <DocumentTable
          :documents="documents"
          :loading="docsLoading"
          :dataset="selectedDataset"
          @refresh="loadDocuments"
          @upload="openUpload"
          @create="openText"
          @segments="openSegments"
          @reindex="reindex"
          @remove="removeDocuments"
        />
      </div>
    </div>

    <el-dialog v-model="datasetDialog" title="编辑知识库" width="640px">
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="datasetForm.name" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="datasetForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-divider content-position="left">分段与清洗</el-divider>
        <ChunkSettingsForm v-model="datasetForm.chunk_config" />
        <el-divider content-position="left">索引与检索</el-divider>
        <el-form-item label="索引方式">
          <el-radio-group v-model="datasetForm.index_method">
            <el-radio value="high_quality">高质量（向量化）</el-radio>
            <el-radio value="economy">经济（仅关键词）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="检索模式">
          <el-radio-group v-model="datasetForm.retrieval_mode">
            <el-radio value="vector">向量检索</el-radio>
            <el-radio value="fulltext">全文检索</el-radio>
            <el-radio value="hybrid">混合检索</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="Rerank">
          <el-switch v-model="datasetForm.rerank" />
        </el-form-item>
        <el-form-item label="默认召回 top_k（召回测试用）">
          <el-input-number v-model="datasetForm.top_k" :min="1" controls-position="right" />
        </el-form-item>
        <el-form-item label="默认 score_threshold（留空不限制）">
          <el-input-number v-model="datasetForm.score_threshold" :step="0.01" controls-position="right" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="datasetDialog = false">取消</el-button>
        <el-button type="primary" :loading="datasetSaving" @click="submitDataset">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="uploadDialog" title="上传文档" width="560px">
      <el-form label-position="top">
        <el-form-item :label="`文件（${UPLOAD_ACCEPT}，单文件不超过 15MB）`">
          <el-upload
            :auto-upload="false"
            :limit="1"
            :accept="UPLOAD_ACCEPT"
            :on-change="onUploadChange"
            :on-remove="() => (uploadFile = null)"
          >
            <el-button>选择文件</el-button>
          </el-upload>
        </el-form-item>
        <el-progress v-if="uploading || uploadProgress" :percentage="uploadProgress" />
        <el-divider />
        <el-checkbox v-model="uploadOverride">覆盖知识库分段设置</el-checkbox>
        <ChunkSettingsForm v-if="uploadOverride" v-model="uploadChunkConfig" />
      </el-form>
      <template #footer>
        <el-button @click="uploadDialog = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="submitUpload">上传并入库</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="textDialog" title="新增文本" width="600px">
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="textForm.name" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="textForm.content" type="textarea" :rows="10" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="textDialog = false">取消</el-button>
        <el-button type="primary" :loading="textSaving" @click="submitText">入库</el-button>
      </template>
    </el-dialog>

    <SegmentDrawer v-model:visible="segmentsVisible" :document="segmentDoc" @changed="loadDocuments" />
    <HitTestDialog v-model:visible="hitTestVisible" :dataset="selectedDataset" />
    <KnowledgeWizard
      v-model:visible="wizardVisible"
      :tenant-code="tenantFilter"
      :providers="providers"
      :retrieval="retrievalConfig"
      @created="onWizardCreated"
    />
  </div>
</template>

<style scoped>
.kb {
  height: calc(100vh - 120px);
}

.kb__bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.kb__tenant {
  width: 220px;
}

.kb__body {
  display: flex;
  gap: 12px;
  height: calc(100% - 44px);
}

.kb__aside {
  width: 240px;
  flex: none;
  overflow: auto;
}

.kb__main {
  flex: 1;
  min-width: 0;
  overflow: auto;
}

.kb__tools {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}
</style>
