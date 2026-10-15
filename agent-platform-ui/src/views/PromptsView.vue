<script setup>
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { createPrompt, deletePrompt, listPrompts, updatePrompt } from '@/api'
import { useTable } from '@/composables/useTable'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const filters = reactive({ tenant_code: '' })
const { rows, loading, reload } = useTable(() => listPrompts({ tenant_code: filters.tenant_code }))

const dialogVisible = ref(false)
const saving = ref(false)
const editingUuid = ref('')
const form = reactive({ code: '', label: '', system_prompt: '', cot_hint: '', examples: '[]' })

function openCreate() {
  editingUuid.value = ''
  Object.assign(form, { code: '', label: '', system_prompt: '', cot_hint: '', examples: '[]' })
  dialogVisible.value = true
}

function openEdit(row) {
  editingUuid.value = row.uuid
  Object.assign(form, {
    code: row.code,
    label: row.label,
    system_prompt: row.system_prompt,
    cot_hint: row.cot_hint,
    examples: JSON.stringify(row.examples || [], null, 2),
  })
  dialogVisible.value = true
}

async function submit() {
  if (!form.code) {
    ElMessage.warning('请填写模板 code')
    return
  }
  let examples = []
  try {
    examples = form.examples ? JSON.parse(form.examples) : []
  } catch {
    ElMessage.warning('示例须为合法 JSON')
    return
  }
  const payload = {
    code: form.code,
    label: form.label,
    system_prompt: form.system_prompt,
    cot_hint: form.cot_hint,
    examples,
  }
  saving.value = true
  try {
    if (editingUuid.value) {
      await updatePrompt(editingUuid.value, payload)
    } else {
      await createPrompt(payload)
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
    await ElMessageBox.confirm(`确认删除模板「${row.label || row.code}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deletePrompt(row.uuid)
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
      <el-button @click="reload()">查询</el-button>
      <el-button v-if="auth.can('prompt:write')" type="primary" @click="openCreate">新增模板</el-button>
    </div>
    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="code" label="code" width="200" />
      <el-table-column prop="label" label="名称" width="180" />
      <el-table-column prop="system_prompt" label="system 骨架" min-width="240" show-overflow-tooltip />
      <el-table-column label="示例" width="80">
        <template #default="{ row }">{{ (row.examples || []).length }}</template>
      </el-table-column>
      <el-table-column prop="cot_hint" label="CoT 提示" min-width="180" show-overflow-tooltip />
      <el-table-column label="内置" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.is_builtin" size="small" type="warning">内置</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button v-if="auth.can('prompt:write')" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button
            v-if="auth.can('prompt:write') && !row.is_builtin"
            link
            type="danger"
            @click="remove(row)"
          >删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editingUuid ? '编辑提示词模板' : '新增提示词模板'" width="720px">
      <el-form label-position="top">
        <el-form-item label="code（智能体按它引用）">
          <el-input v-model="form.code" :disabled="Boolean(editingUuid)" placeholder="如 fewshot.gov_answer" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="form.label" />
        </el-form-item>
        <el-form-item label="system 骨架">
          <el-input v-model="form.system_prompt" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="思维链提示（CoT 开启时追加）">
          <el-input v-model="form.cot_hint" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="少样本示例（JSON 数组：[{input, output}]）">
          <el-input v-model="form.examples" type="textarea" :rows="6" />
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
  width: 200px;
}
</style>
