<script setup>
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { createDocument, deleteDocument, listDocuments, uploadDocument } from '@/api'
import { useTable } from '@/composables/useTable'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const filters = reactive({ tenant_code: '', dataset_id: '' })
const { rows, loading, reload } = useTable(() =>
  listDocuments({ tenant_code: filters.tenant_code, dataset_id: filters.dataset_id }),
)

const dialogVisible = ref(false)
const saving = ref(false)
const detail = ref(null)
const form = reactive({ tenant_code: '', dataset_id: '', title: '', content: '', metadata: '{}' })

const uploadVisible = ref(false)
const uploading = ref(false)
const uploadFile = ref(null)
const uploadForm = reactive({ tenant_code: '', dataset_id: '' })

// 与后端 DOCUMENT_SUFFIXES 保持一致
const UPLOAD_ACCEPT = '.txt,.md,.markdown,.mdx,.csv,.html,.htm,.pdf,.docx,.xlsx,.xls'

function openCreate() {
  Object.assign(form, { tenant_code: filters.tenant_code, dataset_id: filters.dataset_id, title: '', content: '', metadata: '{}' })
  dialogVisible.value = true
}

function openUpload() {
  Object.assign(uploadForm, { tenant_code: filters.tenant_code, dataset_id: filters.dataset_id })
  uploadFile.value = null
  uploadVisible.value = true
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
  body.append('tenant_code', uploadForm.tenant_code || '')
  body.append('dataset_id', uploadForm.dataset_id || '')
  uploading.value = true
  try {
    const result = await uploadDocument(body)
    uploadVisible.value = false
    ElMessage.success(`已入库 ${result.chunks} 个分块`)
    await reload()
  } catch (error) {
    ElMessage.error(error.message || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function submit() {
  if (!form.content) {
    ElMessage.warning('请填写文档内容')
    return
  }
  let metadata = {}
  try {
    metadata = form.metadata ? JSON.parse(form.metadata) : {}
  } catch {
    ElMessage.warning('元数据须为合法 JSON')
    return
  }
  saving.value = true
  try {
    await createDocument({
      tenant_code: form.tenant_code,
      dataset_id: form.dataset_id,
      title: form.title,
      content: form.content,
      metadata,
    })
    dialogVisible.value = false
    ElMessage.success('已入库')
    await reload()
  } catch (error) {
    ElMessage.error(error.message || '入库失败')
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确认删除文档「${row.title || row.uuid}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteDocument(row.uuid)
    ElMessage.success('已删除')
    await reload()
  } catch (error) {
    ElMessage.error(error.message || '删除失败')
  }
}
</script>

<template>
  <div>
    <div class="toolbar">
      <el-input v-model="filters.tenant_code" placeholder="租户编码" class="toolbar__input" @keyup.enter="reload()" />
      <el-input v-model="filters.dataset_id" placeholder="数据集 id" class="toolbar__input" @keyup.enter="reload()" />
      <el-button @click="reload()">查询</el-button>
      <el-button v-if="auth.can('knowledge:write')" type="primary" @click="openCreate">新增文档</el-button>
      <el-button v-if="auth.can('knowledge:write')" @click="openUpload">上传文件</el-button>
    </div>
    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="title" label="标题" min-width="160" />
      <el-table-column prop="dataset_id" label="数据集" width="140" />
      <el-table-column prop="tenant_code" label="租户" width="120" />
      <el-table-column prop="content" label="内容" min-width="260" show-overflow-tooltip />
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="detail = row">查看</el-button>
          <el-button v-if="auth.can('knowledge:write')" link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="uploadVisible" title="上传知识库文件" width="520px">
      <el-form label-position="top">
        <el-form-item :label="`文件（${UPLOAD_ACCEPT}，单文件不超过 15MB，按段落分块入库）`">
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
        <el-form-item label="数据集 id">
          <el-input v-model="uploadForm.dataset_id" placeholder="留空为默认数据集" />
        </el-form-item>
        <el-form-item label="租户编码（留空取默认租户）">
          <el-input v-model="uploadForm.tenant_code" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="submitUpload">上传并入库</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dialogVisible" title="新增知识库文档" width="600px">
      <el-form label-position="top">
        <el-form-item label="标题">
          <el-input v-model="form.title" />
        </el-form-item>
        <el-form-item label="数据集 id">
          <el-input v-model="form.dataset_id" placeholder="留空为默认数据集" />
        </el-form-item>
        <el-form-item label="租户编码（留空取默认租户）">
          <el-input v-model="form.tenant_code" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="form.content" type="textarea" :rows="6" />
        </el-form-item>
        <el-form-item label="元数据（JSON）">
          <el-input v-model="form.metadata" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">入库</el-button>
      </template>
    </el-dialog>

    <el-dialog :model-value="Boolean(detail)" title="文档详情" width="600px" @update:model-value="detail = null">
      <el-descriptions v-if="detail" :column="1" border>
        <el-descriptions-item label="标题">{{ detail.title }}</el-descriptions-item>
        <el-descriptions-item label="数据集">{{ detail.dataset_id }}</el-descriptions-item>
        <el-descriptions-item label="租户">{{ detail.tenant_code }}</el-descriptions-item>
        <el-descriptions-item label="内容">{{ detail.content }}</el-descriptions-item>
        <el-descriptions-item label="元数据">{{ JSON.stringify(detail.metadata || {}) }}</el-descriptions-item>
      </el-descriptions>
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
</style>
