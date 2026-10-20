<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createUserMemory,
  deleteUserMemory,
  getMemoryConfig,
  listMemoryUsers,
  listUserMemories,
  purgeUserMemories,
  recallUserMemory,
  updateUserMemory,
} from '@/api'
import { useTable } from '@/composables/useTable'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const filters = reactive({ tenant_code: '', user_key: '', q: '' })
const { data, loading, reload } = useTable(() => listUserMemories({ ...filters }))
const rows = computed(() => (data.value && data.value.items) || [])
const total = computed(() => (data.value && data.value.total) || 0)
const config = ref({})
const users = ref([])

const dialogVisible = ref(false)
const editingUuid = ref('')
const saving = ref(false)
const form = reactive({
  tenant_code: '',
  app_uuid: '',
  user_key: '',
  user_name: '',
  kind: 'fact',
  content: '',
  importance: 0.5,
  enabled: true,
})

const recallVisible = ref(false)
const recallForm = reactive({ user_key: '', app_uuid: '', query: '', top_k: 5 })
const recallHits = ref([])
const recalling = ref(false)

const KINDS = ['fact', 'preference', 'episode']

async function loadMeta() {
  try {
    config.value = (await getMemoryConfig()) || {}
    users.value = (await listMemoryUsers({ tenant_code: filters.tenant_code })) || []
  } catch {
    // 回显失败不阻断列表
  }
}

function resetForm() {
  Object.assign(form, {
    tenant_code: filters.tenant_code,
    app_uuid: '',
    user_key: filters.user_key,
    user_name: '',
    kind: 'fact',
    content: '',
    importance: 0.5,
    enabled: true,
  })
}

function openCreate() {
  editingUuid.value = ''
  resetForm()
  dialogVisible.value = true
}

function openEdit(row) {
  editingUuid.value = row.uuid
  Object.assign(form, {
    tenant_code: row.tenant_code,
    app_uuid: row.app_uuid,
    user_key: row.user_key,
    user_name: row.user_name,
    kind: row.kind,
    content: row.content,
    importance: row.importance,
    enabled: Boolean(row.enabled),
  })
  dialogVisible.value = true
}

async function submit() {
  if (!form.user_key.trim() || !form.content.trim()) {
    ElMessage.warning('user_key 与 content 不能为空')
    return
  }
  saving.value = true
  try {
    if (editingUuid.value) {
      await updateUserMemory(editingUuid.value, { ...form })
    } else {
      await createUserMemory({ ...form })
    }
    dialogVisible.value = false
    ElMessage.success('已保存')
    await reload()
    await loadMeta()
  } catch (error) {
    ElMessage.error(error.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确认删除「${row.content}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteUserMemory(row.uuid)
    ElMessage.success('已删除')
    await reload()
  } catch (error) {
    ElMessage.error(error.message || '删除失败')
  }
}

async function purge() {
  const userKey = filters.user_key.trim()
  if (!userKey) {
    ElMessage.warning('请先填写用户标识')
    return
  }
  try {
    await ElMessageBox.confirm(`确认物理删除用户「${userKey}」的全部记忆？`, '隐私删除', { type: 'warning' })
  } catch {
    return
  }
  try {
    const result = await purgeUserMemories({ tenant_code: filters.tenant_code, user_key: userKey, app_uuid: '' })
    ElMessage.success(`已删除 ${(result && result.deleted) || 0} 条`)
    await reload()
  } catch (error) {
    ElMessage.error(error.message || '删除失败')
  }
}

function openRecall(row) {
  recallForm.user_key = row ? row.user_key : filters.user_key
  recallForm.app_uuid = row ? row.app_uuid : ''
  recallForm.query = ''
  recallForm.top_k = 5
  recallHits.value = []
  recallVisible.value = true
}

async function runRecall() {
  if (!recallForm.user_key.trim() || !recallForm.query.trim()) {
    ElMessage.warning('请填写 user_key 与 query')
    return
  }
  recalling.value = true
  try {
    const result = await recallUserMemory({ ...recallForm, tenant_code: filters.tenant_code })
    recallHits.value = (result && result.hits) || []
  } catch (error) {
    ElMessage.error(error.message || '召回失败')
  } finally {
    recalling.value = false
  }
}

async function refresh() {
  await reload()
  await loadMeta()
}

onMounted(loadMeta)
</script>

<template>
  <div>
    <el-alert type="info" :closable="false" show-icon class="memory__config">
      <p>
        开关：总闸 {{ config.enabled ? '开' : '关' }} / 写入 {{ config.write_enabled ? '开' : '关' }} /
        召回 {{ config.recall_enabled ? '开' : '关' }}；作用域 {{ config.scope || 'app' }}；top_k {{ config.top_k }}；
        单用户上限 {{ config.max_per_user }}
      </p>
      <p>生产环境请开启管理端鉴权，并由网关注入可信 user 标识。</p>
    </el-alert>

    <div class="toolbar">
      <el-input v-model="filters.tenant_code" placeholder="租户编码" class="toolbar__input" @keyup.enter="refresh" />
      <el-input v-model="filters.user_key" placeholder="用户标识" class="toolbar__input" @keyup.enter="refresh" />
      <el-input v-model="filters.q" placeholder="内容关键词" class="toolbar__input" @keyup.enter="refresh" />
      <el-button @click="refresh">查询</el-button>
      <el-button v-if="auth.can('memory:write')" type="primary" @click="openCreate">新增记忆</el-button>
      <el-button v-if="auth.can('memory:write')" type="danger" plain @click="purge">按用户清除</el-button>
      <el-button @click="openRecall(null)">召回测试</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="user_key" label="用户" width="140" />
      <el-table-column prop="app_uuid" label="应用" width="180" show-overflow-tooltip />
      <el-table-column prop="kind" label="类型" width="100" />
      <el-table-column prop="content" label="内容" min-width="260" show-overflow-tooltip />
      <el-table-column prop="importance" label="重要度" width="90" />
      <el-table-column prop="hit_count" label="命中" width="70" />
      <el-table-column prop="updated_at" label="更新时间" width="170" />
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openRecall(row)">召回</el-button>
          <el-button v-if="auth.can('memory:write')" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="auth.can('memory:write')" link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <p class="memory__total">共 {{ total }} 条</p>

    <el-dialog v-model="dialogVisible" :title="editingUuid ? '编辑记忆' : '新增记忆'" width="620px">
      <el-form label-position="top">
        <el-form-item label="用户标识 user_key">
          <el-input v-model="form.user_key" :disabled="Boolean(editingUuid)" />
        </el-form-item>
        <el-form-item label="应用 uuid（留空表示租户级）">
          <el-input v-model="form.app_uuid" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.kind">
            <el-option v-for="item in KINDS" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="form.content" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="重要度">
          <el-input-number v-model="form.importance" :min="0" :max="1" :step="0.1" controls-position="right" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="recallVisible" title="召回测试" width="620px">
      <el-form label-position="top">
        <el-form-item label="用户标识 user_key">
          <el-input v-model="recallForm.user_key" />
        </el-form-item>
        <el-form-item label="应用 uuid（可空）">
          <el-input v-model="recallForm.app_uuid" />
        </el-form-item>
        <el-form-item label="查询">
          <el-input v-model="recallForm.query" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="top_k">
          <el-input-number v-model="recallForm.top_k" :min="1" controls-position="right" />
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="recalling" @click="runRecall">召回</el-button>
      <el-table :data="recallHits" border class="memory__hits">
        <el-table-column prop="kind" label="类型" width="100" />
        <el-table-column prop="content" label="内容" min-width="260" show-overflow-tooltip />
        <el-table-column prop="score" label="分数" width="90" />
      </el-table>
      <template #footer>
        <el-button @click="recallVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.memory__config {
  margin-bottom: 12px;
}

.memory__config p {
  margin: 0;
  font-size: 12px;
}

.memory__total {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.memory__hits {
  margin-top: 12px;
}

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
</style>
