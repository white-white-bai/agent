<script setup>
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { createAgent, deleteAgent, listAgents, updateAgent } from '@/api'
import { useTable } from '@/composables/useTable'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const filters = reactive({ tenant_code: '' })
const { rows, loading, reload } = useTable(() => listAgents({ tenant_code: filters.tenant_code }))

const MODES = ['react', 'autonomous', 'plan_execute', 'reflection', 'supervisor', 'pipeline', 'consensus', 'agent_as_tool', 'deep_search']
const ROLES = ['intent', 'retrieval', 'generate', 'compliance', 'custom']

const dialogVisible = ref(false)
const saving = ref(false)
const editingUuid = ref('')
const form = reactive({
  code: '',
  label: '',
  role: 'custom',
  mode: 'react',
  provider: '',
  system_prompt: '',
  prompt_template: '',
  cot: false,
  max_steps: 6,
  reflection_rounds: 2,
  temperature: 0.3,
  max_tokens: null,
  pipeline: '',
  tools: '[]',
  retriever: '{}',
})

function openCreate() {
  editingUuid.value = ''
  Object.assign(form, {
    code: '', label: '', role: 'custom', mode: 'react', provider: '', system_prompt: '',
    prompt_template: '', cot: false, max_steps: 6, reflection_rounds: 2, temperature: 0.3,
    max_tokens: null, pipeline: '', tools: '[]', retriever: '{}',
  })
  dialogVisible.value = true
}

function openEdit(row) {
  editingUuid.value = row.uuid
  Object.assign(form, {
    code: row.code,
    label: row.label,
    role: row.role,
    mode: row.mode,
    provider: row.provider,
    system_prompt: row.system_prompt,
    prompt_template: row.prompt_template,
    cot: Boolean(row.cot),
    max_steps: row.max_steps,
    reflection_rounds: row.reflection_rounds,
    temperature: row.temperature,
    max_tokens: row.max_tokens,
    pipeline: (row.pipeline || []).join(', '),
    tools: JSON.stringify(row.tools || [], null, 2),
    retriever: JSON.stringify(row.retriever || {}, null, 2),
  })
  dialogVisible.value = true
}

function buildPayload() {
  let tools = []
  let retriever = {}
  try {
    tools = form.tools ? JSON.parse(form.tools) : []
    retriever = form.retriever ? JSON.parse(form.retriever) : {}
  } catch {
    ElMessage.warning('工具 / 检索配置须为合法 JSON')
    return null
  }
  return {
    code: form.code,
    label: form.label,
    role: form.role,
    mode: form.mode,
    provider: form.provider,
    system_prompt: form.system_prompt,
    prompt_template: form.prompt_template,
    cot: form.cot,
    max_steps: form.max_steps,
    reflection_rounds: form.reflection_rounds,
    temperature: form.temperature,
    max_tokens: form.max_tokens,
    pipeline: form.pipeline.split(',').map((item) => item.trim()).filter(Boolean),
    tools,
    retriever,
  }
}

async function submit() {
  if (!form.code) {
    ElMessage.warning('请填写 agent code')
    return
  }
  const payload = buildPayload()
  if (!payload) {
    return
  }
  saving.value = true
  try {
    if (editingUuid.value) {
      await updateAgent(editingUuid.value, payload)
    } else {
      await createAgent(payload)
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
    await ElMessageBox.confirm(`确认删除智能体「${row.label || row.code}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteAgent(row.uuid)
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
      <el-button v-if="auth.can('agent:write')" type="primary" @click="openCreate">新增智能体</el-button>
    </div>
    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="code" label="code" width="160" />
      <el-table-column prop="label" label="名称" width="140" />
      <el-table-column prop="role" label="角色" width="110" />
      <el-table-column prop="mode" label="工作模式" width="150" />
      <el-table-column prop="provider" label="模型条目" width="120" />
      <el-table-column label="思维链" width="90">
        <template #default="{ row }">
          <el-tag :type="row.cot ? 'success' : 'info'" size="small">{{ row.cot ? '开' : '关' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="pipeline" label="成员/流水线" min-width="180">
        <template #default="{ row }">{{ (row.pipeline || []).join(' → ') || '-' }}</template>
      </el-table-column>
      <el-table-column label="内置" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.is_builtin" size="small" type="warning">内置</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button v-if="auth.can('agent:write')" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button
            v-if="auth.can('agent:write') && !row.is_builtin"
            link
            type="danger"
            @click="remove(row)"
          >删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editingUuid ? '编辑智能体' : '新增智能体'" width="760px">
      <el-form label-position="top">
        <el-form-item label="code（图节点按它引用）">
          <el-input v-model="form.code" :disabled="Boolean(editingUuid)" placeholder="如 gov.intent" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="form.label" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role">
            <el-option v-for="item in ROLES" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="工作模式">
          <el-select v-model="form.mode">
            <el-option v-for="item in MODES" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型条目（AP_LLM_MODELS 的 key，留空用默认）">
          <el-input v-model="form.provider" />
        </el-form-item>
        <el-form-item label="系统提示词">
          <el-input v-model="form.system_prompt" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="少样本提示词模板 code（可留空）">
          <el-input v-model="form.prompt_template" />
        </el-form-item>
        <el-form-item label="思维链（CoT）">
          <el-switch v-model="form.cot" />
        </el-form-item>
        <el-form-item label="流水线成员 / 可委派子智能体（逗号分隔，pipeline / supervisor / agent_as_tool 用）">
          <el-input v-model="form.pipeline" placeholder="gov.retrieval, gov.generate" />
        </el-form-item>
        <el-form-item label="max_steps">
          <el-input-number v-model="form.max_steps" :min="1" controls-position="right" />
        </el-form-item>
        <el-form-item label="reflection_rounds">
          <el-input-number v-model="form.reflection_rounds" :min="0" controls-position="right" />
        </el-form-item>
        <el-form-item label="temperature">
          <el-input-number v-model="form.temperature" :step="0.1" :min="0" :max="2" controls-position="right" />
        </el-form-item>
        <el-form-item label="工具（JSON，ToolRef 数组；discover=true 时从该 server 的 MCP tools/list 发现）">
          <el-input v-model="form.tools" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="检索配置（JSON，deep_search 用）">
          <el-input v-model="form.retriever" type="textarea" :rows="3" />
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
