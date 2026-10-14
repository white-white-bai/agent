<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { createApp, deleteApp, listApps, updateApp } from '@/api'
import { useTable } from '@/composables/useTable'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const tenantCode = ref('')
const { rows, loading, reload } = useTable(() => listApps({ tenant_code: tenantCode.value }))

const dialogVisible = ref(false)
const editing = ref(null)
const saving = ref(false)
const form = reactive({
  app_id: '',
  api_key: '',
  app_name: '',
  app_type: 'chat',
  opening_statement: '',
  suggested_questions: '',
  tenant_code: '',
})

function openCreate() {
  editing.value = null
  Object.assign(form, {
    app_id: '',
    api_key: '',
    app_name: '',
    app_type: 'chat',
    opening_statement: '',
    suggested_questions: '',
    tenant_code: '',
  })
  dialogVisible.value = true
}

function openEdit(row) {
  editing.value = row
  Object.assign(form, {
    app_id: row.app_id,
    api_key: row.api_key,
    app_name: row.app_name,
    app_type: row.app_type || 'chat',
    opening_statement: row.opening_statement || '',
    suggested_questions: (row.suggested_questions || []).join('\n'),
    tenant_code: row.tenant_code,
  })
  dialogVisible.value = true
}

async function submit() {
  if (!form.app_name) {
    ElMessage.warning('请填写应用名称')
    return
  }
  const payload = {
    app_name: form.app_name,
    app_type: form.app_type,
    opening_statement: form.opening_statement,
    suggested_questions: form.suggested_questions.split('\n').map((item) => item.trim()).filter(Boolean),
  }
  saving.value = true
  try {
    if (editing.value) {
      await updateApp(editing.value.uuid, payload)
    } else {
      await createApp({
        ...payload,
        app_id: form.app_id,
        api_key: form.api_key,
        tenant_code: form.tenant_code,
      })
    }
    dialogVisible.value = false
    ElMessage.success('已保存')
    await reload()
  } catch (error) {
    ElMessage.error(error.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确认删除应用「${row.app_name || row.app_id}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteApp(row.uuid)
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
      <el-input v-model="tenantCode" placeholder="租户编码（留空为全部）" class="toolbar__input" @keyup.enter="reload()" />
      <el-button @click="reload()">查询</el-button>
      <el-button v-if="auth.can('app:write')" type="primary" @click="openCreate">新增应用</el-button>
    </div>
    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="app_name" label="应用名称" min-width="150" />
      <el-table-column prop="app_id" label="app_id" min-width="180" />
      <el-table-column prop="tenant_code" label="租户" width="120" />
      <el-table-column prop="app_type" label="类型" width="90" />
      <el-table-column prop="api_key" label="api_key" min-width="180" show-overflow-tooltip />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="router.push(`/apps/${row.uuid}/graph`)">编排</el-button>
          <el-button v-if="auth.can('app:write')" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="auth.can('app:write')" link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑应用' : '新增应用'" width="520px">
      <el-form label-position="top">
        <el-form-item label="应用名称">
          <el-input v-model="form.app_name" />
        </el-form-item>
        <el-form-item label="应用类型">
          <el-select v-model="form.app_type">
            <el-option label="chat" value="chat" />
            <el-option label="completion" value="completion" />
            <el-option label="agent" value="agent" />
          </el-select>
        </el-form-item>
        <template v-if="!editing">
          <el-form-item label="app_id（留空自动生成）">
            <el-input v-model="form.app_id" />
          </el-form-item>
          <el-form-item label="api_key（留空自动生成）">
            <el-input v-model="form.api_key" />
          </el-form-item>
          <el-form-item label="租户编码（留空取默认租户）">
            <el-input v-model="form.tenant_code" />
          </el-form-item>
        </template>
        <el-form-item label="开场白">
          <el-input v-model="form.opening_statement" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="建议问题（每行一条）">
          <el-input v-model="form.suggested_questions" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
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
}

.toolbar__input {
  width: 240px;
}
</style>
