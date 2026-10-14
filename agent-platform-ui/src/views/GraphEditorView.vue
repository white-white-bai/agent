<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { getApp, getGraph, importGraph, listGraphVersions, publishGraph, rollbackGraph, saveGraphDraft } from '@/api'
import GraphCanvas from '@/components/GraphCanvas.vue'
import NodeInspector from '@/components/NodeInspector.vue'
import NodePalette from '@/components/NodePalette.vue'
import { useAuthStore } from '@/stores/auth'

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

const versionDialog = ref(false)
const versions = ref([])
const importDialog = ref(false)
const importForm = ref({ content: '', llm_provider: 'cloud_gateway', retriever: 'builtin', name: '' })
const importWarnings = ref([])

const title = computed(() => (app.value && app.value.app_name) || appUuid)

async function load() {
  busy.value = true
  try {
    app.value = await getApp(appUuid)
    const graph = await getGraph(appUuid)
    definition.value = (graph && graph.definition) || {}
    selected.value = null
    dirty.value = false
    ready.value = true
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

async function saveDraft() {
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
  if (!importForm.value.content) {
    ElMessage.warning('请粘贴 Dify DSL 内容')
    return
  }
  busy.value = true
  try {
    const result = await importGraph(appUuid, { ...importForm.value })
    importWarnings.value = (result && result.warnings) || []
    loadIntoCanvas(result && result.definition)
    dirty.value = false
    importDialog.value = false
    ElMessage.success('导入完成，草稿已更新')
  } catch (error) {
    ElMessage.error(error.message || '导入失败')
  } finally {
    busy.value = false
  }
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
      <el-tag v-if="dirty" size="small" type="warning">未保存</el-tag>
      <span class="editor__spacer" />
      <el-button size="small" @click="fit">自适应</el-button>
      <el-button size="small" @click="openVersions">版本</el-button>
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
        <GraphCanvas v-if="ready" ref="canvas" :definition="definition" @select="onSelect" @change="dirty = true" />
      </div>
      <div class="editor__inspector">
        <NodeInspector :node="selected" @update="onUpdate" @remove="onRemove" />
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
        <el-form-item label="DSL 内容（YAML 或 JSON）">
          <el-input v-model="importForm.content" type="textarea" :rows="10" />
        </el-form-item>
        <el-form-item label="LLM provider">
          <el-select v-model="importForm.llm_provider">
            <el-option label="cloud_gateway" value="cloud_gateway" />
            <el-option label="openai" value="openai" />
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
</style>
