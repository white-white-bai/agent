<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  clearAgentMemory,
  getAgentApp,
  getApp,
  listAgents,
  listAgentAppVersions,
  listDatasets,
  listMcpServers,
  listProviders,
  listTools,
  publishAgentApp,
  resumeAgent,
  rollbackAgentApp,
  runAgentStream,
  saveAgentAppDraft,
} from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const appUuid = route.params.appUuid

const appRecord = ref(null)
const status = ref('draft')
const saving = ref(false)
const publishing = ref(false)
const versionDialog = ref(false)
const versions = ref([])

const modelOptions = ref([])
const toolOptions = ref([])
const datasetOptions = ref([])
const agentOptions = ref([])
const mcpOptions = ref([])

const form = reactive({
  name: '',
  instructions: '',
  provider: '',
  temperature: 0.3,
  max_tokens: null,
  opening_statement: '',
  tool_names: [],
  mcp_servers: [],
  knowledge_as_tool: true,
  browser: false,
  browser_allowed_hosts: '',
  browser_allow_private: false,
  browser_storage_state: '',
  dataset_ids: [],
  retriever: 'builtin',
  top_k: 5,
  memory_window: 10,
  summary_enabled: false,
  planning: false,
  reflection_rounds: 0,
  max_steps: 6,
  sub_agents: [],
  hitl_enabled: false,
  hitl_policy: 'off',
  hitl_prompt: '即将执行工具 {tool}，参数：{args}。是否批准？',
})

function buildDefinition() {
  return {
    name: form.name,
    instructions: form.instructions,
    provider: form.provider,
    temperature: form.temperature,
    max_tokens: form.max_tokens,
    opening_statement: form.opening_statement,
    tools: form.tool_names.map((name) => ({ name })),
    mcp_servers: form.mcp_servers,
    knowledge: {
      retriever: form.retriever,
      dataset_ids: form.dataset_ids,
      top_k: form.top_k,
      output_var: 'chunks',
    },
    knowledge_as_tool: form.knowledge_as_tool,
    browser: form.browser,
    browser_allowed_hosts: form.browser_allowed_hosts,
    browser_allow_private: form.browser_allow_private,
    browser_storage_state: form.browser_storage_state,
    memory: { window: form.memory_window, summary_enabled: form.summary_enabled },
    planning: form.planning,
    reflection_rounds: form.reflection_rounds,
    max_steps: form.max_steps,
    sub_agents: form.sub_agents,
    hitl: { enabled: form.hitl_enabled, policy: form.hitl_policy, prompt: form.hitl_prompt },
  }
}

function applyDefinition(definition) {
  const def = definition || {}
  const knowledge = def.knowledge || {}
  const memory = def.memory || {}
  const hitl = def.hitl || {}
  Object.assign(form, {
    name: def.name || '',
    instructions: def.instructions || '',
    provider: def.provider || '',
    temperature: def.temperature ?? 0.3,
    max_tokens: def.max_tokens ?? null,
    opening_statement: def.opening_statement || '',
    tool_names: (def.tools || []).map((item) => item.name),
    mcp_servers: def.mcp_servers || [],
    knowledge_as_tool: def.knowledge_as_tool ?? true,
    browser: Boolean(def.browser),
    browser_allowed_hosts: def.browser_allowed_hosts || '',
    browser_allow_private: Boolean(def.browser_allow_private),
    browser_storage_state: def.browser_storage_state || '',
    dataset_ids: knowledge.dataset_ids || [],
    retriever: knowledge.retriever || 'builtin',
    top_k: knowledge.top_k ?? 5,
    memory_window: memory.window ?? 10,
    summary_enabled: Boolean(memory.summary_enabled),
    planning: Boolean(def.planning),
    reflection_rounds: def.reflection_rounds ?? 0,
    max_steps: def.max_steps ?? 6,
    sub_agents: def.sub_agents || [],
    hitl_enabled: Boolean(hitl.enabled),
    hitl_policy: hitl.policy || 'off',
    hitl_prompt: hitl.prompt || '即将执行工具 {tool}，参数：{args}。是否批准？',
  })
}

async function loadOptions() {
  const [providers, tools, datasets, agents, mcpServers] = await Promise.all([
    listProviders().catch(() => null),
    listTools().catch(() => []),
    listDatasets().catch(() => []),
    listAgents().catch(() => []),
    listMcpServers().catch(() => []),
  ])
  modelOptions.value = ((providers && providers.llm) || []).map((item) => ({
    value: item.name,
    label: item.label || item.name,
  }))
  toolOptions.value = (tools || []).map((item) => ({ value: item.name, label: item.label || item.name }))
  datasetOptions.value = (datasets || []).map((item) => ({ value: item.uuid, label: item.name || item.uuid }))
  agentOptions.value = (agents || []).map((item) => ({ value: item.code, label: `${item.label || item.code}（${item.mode}）` }))
  mcpOptions.value = (mcpServers || []).map((item) => ({ value: item.name, label: item.name }))
}

async function loadAll() {
  appRecord.value = await getApp(appUuid)
  const config = await getAgentApp(appUuid)
  status.value = config?.status || 'draft'
  applyDefinition(config?.definition)
}

async function saveDraft() {
  saving.value = true
  try {
    await saveAgentAppDraft(appUuid, buildDefinition())
    ElMessage.success('草稿已保存')
  } catch (error) {
    ElMessage.error(error.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function publish() {
  publishing.value = true
  try {
    await publishAgentApp(appUuid, { definition: buildDefinition() })
    status.value = 'published'
    ElMessage.success('已发布')
  } catch (error) {
    ElMessage.error(error.message || '发布失败')
  } finally {
    publishing.value = false
  }
}

async function openVersions() {
  versions.value = await listAgentAppVersions(appUuid)
  versionDialog.value = true
}

async function rollback(row) {
  try {
    await ElMessageBox.confirm(`回滚到版本 ${row.version}？`, '回滚确认', { type: 'warning' })
  } catch {
    return
  }
  await rollbackAgentApp(appUuid, row.version)
  ElMessage.success('已回滚')
  versionDialog.value = false
  await loadAll()
}

// --------------------------------------------------------------------------- 调试对话台
const debugInput = ref('')
const debugRunning = ref(false)
const paused = ref(false)
const messages = ref([])
const debugThread = ref(`debug-${Math.random().toString(16).slice(2)}`)
let controller = null

function resetConsole() {
  messages.value = []
  paused.value = false
  debugThread.value = `debug-${Math.random().toString(16).slice(2)}`
}

async function clearMemory() {
  try {
    await clearAgentMemory(appUuid, debugThread.value)
    resetConsole()
    ElMessage.success('已清空该会话记忆')
  } catch (error) {
    ElMessage.error(error.message || '清空失败')
  }
}

function handleEvent(assistant, event) {
  if (event.type === 'token') {
    assistant.text += event.content
  } else if (event.type === 'final') {
    assistant.text = event.answer || assistant.text
    paused.value = Boolean(event.state && event.state.variables && event.state.variables.paused)
  } else if (event.type === 'error') {
    assistant.events.push(`错误：${event.message}`)
  } else if (event.type === 'agent_plan') {
    assistant.events.push(`计划：${event.plan}`)
  } else if (event.type === 'agent_tool') {
    const names = (event.tools || []).map((item) => item.tool).join('、')
    assistant.events.push(`工具调用：${names || '-'}`)
  } else if (event.type === 'agent_reflection') {
    assistant.events.push(`反思第 ${event.rounds} 轮`)
  } else if (event.type === 'agent_interrupt') {
    assistant.events.push(`等待人工确认：${event.prompt || ''}`)
  }
}

async function send() {
  const query = debugInput.value.trim()
  if (!query || debugRunning.value) {
    return
  }
  debugInput.value = ''
  messages.value.push({ role: 'user', text: query })
  const assistant = reactive({ role: 'assistant', text: '', events: [] })
  messages.value.push(assistant)
  debugRunning.value = true
  paused.value = false
  controller = new AbortController()
  try {
    await runAgentStream(
      appUuid,
      { query, conversation_id: debugThread.value, definition: buildDefinition() },
      (event) => handleEvent(assistant, event),
      { signal: controller.signal },
    )
  } catch (error) {
    assistant.events.push(`请求失败：${error.message || error}`)
  } finally {
    debugRunning.value = false
    controller = null
  }
}

async function decide(decision) {
  if (debugRunning.value) {
    return
  }
  messages.value.push({ role: 'user', text: decision === 'approve' ? '（批准执行）' : '（拒绝执行）' })
  const assistant = reactive({ role: 'assistant', text: '', events: [] })
  messages.value.push(assistant)
  debugRunning.value = true
  paused.value = false
  controller = new AbortController()
  try {
    await resumeAgent(
      appUuid,
      { conversation_id: debugThread.value, decision },
      (event) => handleEvent(assistant, event),
      { signal: controller.signal },
    )
  } catch (error) {
    assistant.events.push(`请求失败：${error.message || error}`)
  } finally {
    debugRunning.value = false
    controller = null
  }
}

const canWrite = computed(() => auth.can('agent:write'))

onMounted(async () => {
  await loadOptions()
  await loadAll()
})
</script>

<template>
  <div class="agent-config">
    <div class="toolbar">
      <span class="toolbar__title">Agent 配置 · {{ (appRecord && appRecord.app_name) || appUuid }}</span>
      <el-tag size="small" :type="status === 'published' ? 'success' : 'info'">{{ status }}</el-tag>
      <div class="toolbar__grow" />
      <el-button @click="openVersions">版本</el-button>
      <el-button v-if="canWrite" :loading="saving" @click="saveDraft">保存草稿</el-button>
      <el-button v-if="canWrite" type="primary" :loading="publishing" @click="publish">发布</el-button>
    </div>

    <div class="columns">
      <el-card class="columns__form" shadow="never">
        <el-form label-position="top">
          <el-form-item label="名称">
            <el-input v-model="form.name" />
          </el-form-item>
          <el-form-item label="指令（system prompt）">
            <el-input v-model="form.instructions" type="textarea" :rows="5" placeholder="定义这个 agent 的角色、目标与约束" />
          </el-form-item>
          <el-form-item label="模型">
            <el-select v-model="form.provider" clearable placeholder="留空用清单第一个" style="width: 100%">
              <el-option v-for="item in modelOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="temperature">
            <el-input-number v-model="form.temperature" :step="0.1" :min="0" :max="2" controls-position="right" />
          </el-form-item>
          <el-form-item label="工具（来自「工具声明」）">
            <el-select v-model="form.tool_names" multiple clearable style="width: 100%">
              <el-option v-for="item in toolOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="MCP Server（动态发现其工具）">
            <el-select v-model="form.mcp_servers" multiple clearable style="width: 100%">
              <el-option v-for="item in mcpOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="知识库">
            <el-select v-model="form.dataset_ids" multiple clearable style="width: 100%">
              <el-option v-for="item in datasetOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="知识作为工具（agent 自主决定是否检索）">
            <el-switch v-model="form.knowledge_as_tool" />
          </el-form-item>
          <el-form-item label="浏览器操作（Playwright，需服务端开启）">
            <el-switch v-model="form.browser" />
          </el-form-item>
          <el-form-item v-if="form.browser" label="浏览器 host 白名单（逗号分隔，留空用全局）">
            <el-input v-model="form.browser_allowed_hosts" placeholder="example.com,internal.example" />
          </el-form-item>
          <el-form-item v-if="form.browser" label="允许访问私网（仍需全局 AP_BROWSER_ALLOW_PRIVATE=true）">
            <el-switch v-model="form.browser_allow_private" />
          </el-form-item>
          <el-form-item v-if="form.browser" label="登录态文件（storage_state，可空）">
            <el-input v-model="form.browser_storage_state" placeholder=".run/browser/agent-state.json" />
          </el-form-item>
          <el-form-item label="子 agent（可委派）">
            <el-select v-model="form.sub_agents" multiple clearable style="width: 100%">
              <el-option v-for="item in agentOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="规划（先出计划再执行）">
            <el-switch v-model="form.planning" />
          </el-form-item>
          <el-form-item label="反思轮数">
            <el-input-number v-model="form.reflection_rounds" :min="0" controls-position="right" />
          </el-form-item>
          <el-form-item label="max_steps">
            <el-input-number v-model="form.max_steps" :min="1" controls-position="right" />
          </el-form-item>
          <el-form-item label="记忆窗口（条）">
            <el-input-number v-model="form.memory_window" :min="0" controls-position="right" />
          </el-form-item>
          <el-form-item label="人工审批（HITL）">
            <el-switch v-model="form.hitl_enabled" />
          </el-form-item>
          <el-form-item v-if="form.hitl_enabled" label="审批策略">
            <el-select v-model="form.hitl_policy" style="width: 100%">
              <el-option label="全部工具前" value="before_all_tools" />
              <el-option label="仅指定工具前" value="before_listed" />
              <el-option label="关闭" value="off" />
            </el-select>
          </el-form-item>
        </el-form>
      </el-card>

      <el-card class="columns__console" shadow="never">
        <template #header>
          <div class="console__header">
            <span>调试对话</span>
            <div>
              <el-button link @click="clearMemory">清空记忆</el-button>
              <el-button link @click="resetConsole">清空</el-button>
            </div>
          </div>
        </template>
        <div class="console__body">
          <div v-for="(message, index) in messages" :key="index" :class="['bubble', `bubble--${message.role}`]">
            <div class="bubble__text">{{ message.text }}</div>
            <div v-for="(line, i) in message.events || []" :key="i" class="bubble__event">{{ line }}</div>
          </div>
          <div v-if="!messages.length" class="console__empty">输入问题，实时查看 agent 的思考与工具调用。</div>
        </div>
        <div v-if="paused" class="console__approve">
          <span>等待人工确认</span>
          <el-button size="small" type="primary" @click="decide('approve')">批准</el-button>
          <el-button size="small" type="danger" @click="decide('reject')">拒绝</el-button>
        </div>
        <div class="console__input">
          <el-input
            v-model="debugInput"
            placeholder="输入问题，回车发送"
            :disabled="debugRunning"
            @keyup.enter="send"
          />
          <el-button type="primary" :loading="debugRunning" @click="send">发送</el-button>
        </div>
      </el-card>
    </div>

    <el-dialog v-model="versionDialog" title="Agent 版本" width="680px">
      <el-table :data="versions" border>
        <el-table-column prop="version" label="版本" width="80" />
        <el-table-column prop="note" label="说明" min-width="160" />
        <el-table-column prop="created_by" label="创建人" width="120" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button v-if="canWrite" link type="primary" @click="rollback(row)">回滚</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.agent-config {
  padding: 4px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.toolbar__title {
  font-weight: 600;
}

.toolbar__grow {
  flex: 1;
}

.columns {
  display: grid;
  grid-template-columns: minmax(360px, 1fr) minmax(360px, 1fr);
  gap: 12px;
}

.console__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.console__body {
  height: 60vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 4px;
}

.console__empty {
  color: #909399;
  font-size: 13px;
}

.console__input {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.console__approve {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  color: #e6a23c;
  font-size: 13px;
}

.bubble {
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
  line-height: 1.5;
}

.bubble--user {
  background: #ecf5ff;
  align-self: flex-end;
  max-width: 85%;
}

.bubble--assistant {
  background: #f5f7fa;
  align-self: flex-start;
  max-width: 95%;
}

.bubble__text {
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble__event {
  margin-top: 4px;
  color: #909399;
  font-size: 12px;
}
</style>
