<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { getApp, getGraph, getGraphTemplate, importGraph, importGraphFile, listAgents, listDatasets, listGraphVersions, listProviders, publishGraph, rollbackGraph, runGraphStream, runNode, saveGraphDraft } from '@/api'
import GraphCanvas from '@/components/GraphCanvas.vue'
import NodeInspector from '@/components/NodeInspector.vue'
import NodePalette from '@/components/NodePalette.vue'
import RowsEditor from '@/components/fields/RowsEditor.vue'
import { useAuthStore } from '@/stores/auth'
import { buildRunInputs, formatRunOutput, mergeRunInputs } from '@/utils/run'

const route = useRoute()
const auth = useAuthStore()
const appUuid = route.params.appUuid

const canvas = ref(null)
const app = ref(null)
const definition = ref({})
const selected = ref(null)
const ready = ref(false)
const dirty = ref(false)
const busy = ref(false)
// 自动保存：编辑后防抖落库，避免改一处要点一次「保存草稿」
const autoSaving = ref(false)
const AUTO_SAVE_DELAY = 600
let autoSaveTimer = null
let revision = 0

const versionDialog = ref(false)
const versions = ref([])
const importDialog = ref(false)
const importForm = ref({ content: '', llm_provider: '', retriever: 'builtin', name: '' })
const importFile = ref(null)
const importWarnings = ref([])
// 可用模型条目（AP_LLM_MODELS），供节点检查器与导入对话框下拉使用
const modelOptions = ref([])
// 可用智能体（/admin/agents），供 agent 节点的下拉使用
const agentOptions = ref([])
// 可用知识库（/admin/datasets），供 knowledge 节点的下拉使用
const datasetOptions = ref([])

// 运行（整图 / 单节点）
const runDialog = ref(false)
const runTarget = ref(null)
const runValues = ref({})
const runExtras = ref([])
const runOutput = ref('')
const runFinal = ref(null)
const runSteps = ref([])
const runBusy = ref(false)
const runError = ref('')
const runColumns = [
  { key: 'name', label: '变量名', kind: 'text' },
  { key: 'value', label: '值', kind: 'text' },
]
let runController = null

const title = computed(() => (app.value && app.value.app_name) || appUuid)

async function loadModelOptions() {
  try {
    const data = await listProviders()
    return ((data && data.llm) || []).map((item) => ({ value: item.name, label: item.label || item.name }))
  } catch {
    // 拿不到模型清单不阻断编辑器
    return []
  }
}

async function loadAgentOptions() {
  try {
    const rows = (await listAgents()) || []
    return rows.map((item) => ({ value: item.code, label: `${item.label || item.code}（${item.mode}）` }))
  } catch {
    // 拿不到智能体清单不阻断编辑器
    return []
  }
}

async function loadDatasetOptions() {
  try {
    const rows = (await listDatasets({ tenant_code: (app.value && app.value.tenant_code) || '' })) || []
    return rows.map((item) => ({ value: item.uuid, label: item.name || item.uuid }))
  } catch {
    // 拿不到知识库清单不阻断编辑器
    return []
  }
}

async function insertPipelineTemplate() {
  try {
    const template = await getGraphTemplate('pipeline.gov_consult')
    if (!template || !template.definition) {
      ElMessage.warning('模板不存在')
      return
    }
    loadIntoCanvas(template.definition)
    markDirty()
    ElMessage.success('已插入「政务咨询分角色流水线」，保存草稿后即可运行')
  } catch (error) {
    ElMessage.error(error.message || '插入模板失败')
  }
}

async function load() {
  busy.value = true
  try {
    app.value = await getApp(appUuid)
    const graph = await getGraph(appUuid)
    definition.value = (graph && graph.definition) || {}
    selected.value = null
    clearAutoSave()
    dirty.value = false
    ready.value = true
    modelOptions.value = await loadModelOptions()
    agentOptions.value = await loadAgentOptions()
    datasetOptions.value = await loadDatasetOptions()
  } catch (error) {
    ElMessage.error(error.message || '加载失败')
  } finally {
    busy.value = false
  }
}
load()

function currentDefinition() {
  if (!canvas.value) {
    return definition.value
  }
  return canvas.value.readDefinition({
    app_id: (app.value && app.value.app_id) || '',
    name: (app.value && app.value.app_name) || '',
    schema_version: definition.value.schema_version,
    inputs: definition.value.inputs,
    global_variables: definition.value.global_variables,
  })
}

function clearAutoSave() {
  if (autoSaveTimer) {
    clearTimeout(autoSaveTimer)
    autoSaveTimer = null
  }
}

function markDirty() {
  revision += 1
  dirty.value = true
  if (!auth.can('graph:write')) {
    return
  }
  clearAutoSave()
  autoSaveTimer = setTimeout(autoSave, AUTO_SAVE_DELAY)
}

async function autoSave() {
  autoSaveTimer = null
  if (!dirty.value || autoSaving.value || !app.value) {
    return
  }
  const current = revision
  autoSaving.value = true
  try {
    const saved = await saveGraphDraft(appUuid, currentDefinition())
    definition.value = (saved && saved.definition) || definition.value
    if (revision === current) {
      dirty.value = false
    } else {
      // 请求期间又有改动，安排下一轮
      autoSaveTimer = setTimeout(autoSave, AUTO_SAVE_DELAY)
    }
  } catch (error) {
    ElMessage.error(error.message || '自动保存失败')
  } finally {
    autoSaving.value = false
  }
}

onBeforeUnmount(clearAutoSave)

async function saveDraft() {
  clearAutoSave()
  busy.value = true
  try {
    const saved = await saveGraphDraft(appUuid, currentDefinition())
    definition.value = (saved && saved.definition) || definition.value
    dirty.value = false
    ElMessage.success('草稿已保存')
  } catch (error) {
    ElMessage.error(error.message || '保存失败')
  } finally {
    busy.value = false
  }
}

async function publish() {
  let note = ''
  try {
    const result = await ElMessageBox.prompt('发布说明', '发布图', { inputValue: '' })
    note = result.value || ''
  } catch {
    return
  }
  busy.value = true
  try {
    clearAutoSave()
    await saveGraphDraft(appUuid, currentDefinition())
    const version = await publishGraph(appUuid, { note, created_by: auth.displayName })
    dirty.value = false
    ElMessage.success(`已发布 v${version.version}`)
  } catch (error) {
    ElMessage.error(error.message || '发布失败，请检查图定义')
  } finally {
    busy.value = false
  }
}

async function openVersions() {
  try {
    versions.value = (await listGraphVersions(appUuid)) || []
    versionDialog.value = true
  } catch (error) {
    ElMessage.error(error.message || '版本列表加载失败')
  }
}

async function rollback(row) {
  try {
    await ElMessageBox.confirm(`确认回滚到 v${row.version}？草稿将被覆盖。`, '回滚确认', { type: 'warning' })
  } catch {
    return
  }
  busy.value = true
  try {
    const version = await rollbackGraph(appUuid, row.version)
    loadIntoCanvas(version && version.definition)
    clearAutoSave()
    dirty.value = false
    versionDialog.value = false
    ElMessage.success(`已回滚到 v${row.version}`)
  } catch (error) {
    ElMessage.error(error.message || '回滚失败')
  } finally {
    busy.value = false
  }
}

async function runImport() {
  if (!importFile.value && !importForm.value.content) {
    ElMessage.warning('请选择 DSL 文件或粘贴 DSL 内容')
    return
  }
  busy.value = true
  try {
    const result = importFile.value
      ? await importGraphFile(appUuid, buildImportFormData())
      : await importGraph(appUuid, { ...importForm.value })
    importWarnings.value = (result && result.warnings) || []
    loadIntoCanvas(result && result.definition)
    clearAutoSave()
    dirty.value = false
    importDialog.value = false
    importFile.value = null
    ElMessage.success('导入完成，草稿已更新')
  } catch (error) {
    ElMessage.error(error.message || '导入失败')
  } finally {
    busy.value = false
  }
}

function buildImportFormData() {
  const form = new FormData()
  form.append('file', importFile.value)
  form.append('llm_provider', importForm.value.llm_provider)
  form.append('retriever', importForm.value.retriever)
  form.append('name', importForm.value.name || '')
  return form
}

function onImportFileChange(file) {
  importFile.value = file.raw
}

function onAdd(type) {
  canvas.value.addNode(type)
}

function fit() {
  if (canvas.value) {
    canvas.value.zoomToFit()
  }
}

function loadIntoCanvas(next) {
  definition.value = next || {}
  selected.value = null
  if (canvas.value) {
    canvas.value.loadDefinition(definition.value)
  }
}

function openRun() {
  runTarget.value = null
  openRunDialog()
}

function openNodeRun(nodeId) {
  const node = (definition.value.nodes || []).find((item) => item.id === nodeId)
  runTarget.value = { id: nodeId, title: (node && node.title) || nodeId }
  openRunDialog()
}

function openRunDialog() {
  runValues.value = buildRunInputs(definition.value.inputs || [])
  runExtras.value = []
  runOutput.value = ''
  runFinal.value = null
  runSteps.value = []
  runError.value = ''
  runDialog.value = true
}

function runPayload() {
  return { definition: currentDefinition(), inputs: mergeRunInputs(runValues.value, runExtras.value) }
}

function onRunEvent(event) {
  if (!event || !event.type) {
    return
  }
  if (event.type === 'token') {
    runOutput.value += event.content || ''
  } else if (event.type === 'node_start') {
    runSteps.value.push({ node: event.node, title: event.title || event.node, status: 'running' })
  } else if (event.type === 'node_end') {
    const step = runSteps.value.find((item) => item.node === event.node)
    if (step) {
      step.status = 'done'
    } else {
      runSteps.value.push({ node: event.node, title: event.node, status: 'done' })
    }
  } else if (event.type === 'final') {
    runFinal.value = event.state || {}
    if (!runOutput.value) {
      runOutput.value = event.answer || ''
    }
  } else if (event.type === 'error') {
    runError.value = event.message || '运行失败'
  }
}

async function startRun() {
  runBusy.value = true
  runError.value = ''
  runOutput.value = ''
  runFinal.value = null
  runSteps.value = []
  runController = new AbortController()
  try {
    if (runTarget.value) {
      const result = await runNode(appUuid, { ...runPayload(), node_id: runTarget.value.id })
      runFinal.value = result
      runOutput.value = formatRunOutput(result && result.output)
    } else {
      await runGraphStream(appUuid, runPayload(), onRunEvent, { signal: runController.signal })
    }
  } catch (error) {
    if (error.name !== 'AbortError') {
      runError.value = error.message || '运行失败'
    }
  } finally {
    runBusy.value = false
    runController = null
  }
}

function stopRun() {
  if (runController) {
    runController.abort()
  }
}

function onSelect(node) {
  selected.value = node
}

function onUpdate(patch) {
  canvas.value.applyNode(patch)
  selected.value = { ...selected.value, title: patch.title, config: patch.config }
}

function onRemove(id) {
  canvas.value.removeNode(id)
  selected.value = null
}
</script>

<template>
  <div v-loading="busy" class="editor">
    <div class="editor__bar">
      <span class="editor__title">{{ title }}</span>
      <el-tag v-if="autoSaving" size="small" type="info">保存中…</el-tag>
      <el-tag v-else-if="dirty" size="small" type="warning">未保存</el-tag>
      <span class="editor__spacer" />
      <el-button size="small" @click="fit">自适应</el-button>
      <el-button size="small" @click="openVersions">版本</el-button>
      <el-button v-if="auth.can('graph:write')" size="small" type="success" @click="openRun">运行</el-button>
      <el-button v-if="auth.can('graph:write')" size="small" @click="insertPipelineTemplate">插入流水线模板</el-button>
      <el-button v-if="auth.can('graph:write')" size="small" @click="importDialog = true">导入 Dify DSL</el-button>
      <el-button v-if="auth.can('graph:write')" size="small" @click="saveDraft">保存草稿</el-button>
      <el-button v-if="auth.can('graph:write')" size="small" type="primary" @click="publish">发布</el-button>
    </div>
    <div class="editor__body">
      <div class="editor__aside">
        <NodePalette @add="onAdd" />
        <el-alert v-if="importWarnings.length" type="warning" :closable="false" show-icon class="editor__warnings">
          <p v-for="(warning, index) in importWarnings" :key="index">{{ warning }}</p>
        </el-alert>
      </div>
      <div class="editor__canvas">
        <GraphCanvas v-if="ready" ref="canvas" :definition="definition" @select="onSelect" @change="markDirty" />
      </div>
      <div class="editor__inspector">
        <NodeInspector
          :node="selected"
          :model-options="modelOptions"
          :agent-options="agentOptions"
          :dataset-options="datasetOptions"
          @update="onUpdate"
          @remove="onRemove"
          @run="openNodeRun"
        />
      </div>
    </div>

    <el-dialog v-model="versionDialog" title="图版本" width="680px">
      <el-table :data="versions" border max-height="360">
        <el-table-column prop="version" label="版本" width="80" />
        <el-table-column prop="note" label="说明" min-width="200" show-overflow-tooltip />
        <el-table-column prop="created_by" label="发布人" width="140" />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button v-if="auth.can('graph:write')" link type="primary" @click="rollback(row)">回滚</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="importDialog" title="导入 Dify DSL" width="640px">
      <el-form label-position="top">
        <el-form-item label="DSL 文件（.yml / .yaml / .json，选择后优先于下方内容）">
          <el-upload :auto-upload="false" :show-file-list="true" :limit="1" accept=".yml,.yaml,.json" :on-change="onImportFileChange" :on-remove="() => (importFile = null)">
            <el-button>选择文件</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item label="DSL 内容（YAML 或 JSON，未选文件时使用）">
          <el-input v-model="importForm.content" type="textarea" :rows="10" :disabled="Boolean(importFile)" />
        </el-form-item>
        <el-form-item label="模型（AP_LLM_MODELS 条目）">
          <el-select v-model="importForm.llm_provider" clearable placeholder="留空用清单第一个">
            <el-option v-for="item in modelOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="检索 provider">
          <el-select v-model="importForm.retriever">
            <el-option label="builtin" value="builtin" />
            <el-option label="light_rag" value="light_rag" />
            <el-option label="knowflow" value="knowflow" />
            <el-option label="knowledge_graph" value="knowledge_graph" />
          </el-select>
        </el-form-item>
        <el-form-item label="图名称（留空取应用名）">
          <el-input v-model="importForm.name" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importDialog = false">取消</el-button>
        <el-button type="primary" :loading="busy" @click="runImport">导入并覆盖草稿</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="runDialog" :title="runTarget ? `运行节点：${runTarget.title}` : '运行图（当前草稿）'" width="720px">
      <el-form label-position="top" size="small">
        <el-form-item v-for="item in (definition.inputs || [])" :key="item.name" :label="item.required ? `${item.name} *` : item.name">
          <el-input v-model="runValues[item.name]" :placeholder="item.description || ''" />
        </el-form-item>
        <el-form-item label="额外变量（覆盖同名输入）">
          <RowsEditor v-model="runExtras" :columns="runColumns" />
        </el-form-item>
      </el-form>

      <el-alert v-if="runError" type="error" :closable="false" show-icon class="editor__warnings">{{ runError }}</el-alert>

      <div v-if="runSteps.length" class="editor__steps">
        <el-tag
          v-for="step in runSteps"
          :key="step.node"
          size="small"
          :type="step.status === 'done' ? 'success' : 'info'"
          class="editor__step"
        >
          {{ step.title }}
        </el-tag>
      </div>

      <pre v-if="runOutput" class="editor__runout">{{ runOutput }}</pre>

      <div v-if="runFinal" class="editor__runfinal">
        <p>运行结果</p>
        <pre>{{ formatRunOutput(runFinal) }}</pre>
      </div>

      <template #footer>
        <el-button v-if="runBusy" @click="stopRun">停止</el-button>
        <el-button v-else @click="runDialog = false">关闭</el-button>
        <el-button type="primary" :loading="runBusy" @click="startRun">开始运行</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.editor {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 120px);
}

.editor__bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.editor__title {
  font-weight: 600;
}

.editor__spacer {
  flex: 1;
}

.editor__body {
  flex: 1;
  display: flex;
  gap: 12px;
  min-height: 0;
}

.editor__aside {
  width: 160px;
  flex: none;
  overflow: auto;
}

.editor__canvas {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
}

.editor__inspector {
  width: 300px;
  flex: none;
  overflow: auto;
  padding: 0 4px;
}

.editor__warnings {
  margin-top: 12px;
}

.editor__warnings p {
  margin: 0;
  font-size: 12px;
}

.editor__steps {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0;
}

.editor__runout {
  max-height: 240px;
  overflow: auto;
  margin: 8px 0 0;
  padding: 8px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
}

.editor__runfinal {
  margin-top: 12px;
}

.editor__runfinal p {
  margin: 0 0 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.editor__runfinal pre {
  max-height: 200px;
  overflow: auto;
  margin: 0;
  padding: 8px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
}
</style>
