<script setup>
import { computed, ref, toRaw, watch } from 'vue'

import KeyValueEditor from '@/components/fields/KeyValueEditor.vue'
import RowsEditor from '@/components/fields/RowsEditor.vue'
import StringListEditor from '@/components/fields/StringListEditor.vue'
import { nodeMeta } from '@/graph/nodeMeta'

const props = defineProps({
  node: { type: Object, default: null },
})
const emit = defineEmits(['update', 'remove'])

const draft = ref(null)

const meta = computed(() => (props.node ? nodeMeta(props.node.type) : null))
const fields = computed(() => (meta.value ? meta.value.fields : []))

watch(
  () => [props.node && props.node.id, props.node && props.node.type],
  () => {
    draft.value = props.node ? structuredClone(toRaw(props.node)) : null
  },
  { immediate: true },
)

function fieldValue(key) {
  return draft.value ? draft.value.config[key] : undefined
}

function publish() {
  if (!draft.value) {
    return
  }
  emit('update', { id: draft.value.id, title: draft.value.title, config: draft.value.config })
}

function setField(key, value) {
  if (!draft.value) {
    return
  }
  draft.value.config[key] = value
  publish()
}

function setTitle(value) {
  if (!draft.value) {
    return
  }
  draft.value.title = value
  publish()
}
</script>

<template>
  <div class="inspector">
    <p v-if="!draft" class="inspector__empty">未选中节点</p>
    <template v-else>
      <div class="inspector__head">
        <el-tag size="small" effect="dark" :color="meta.color">{{ meta.label }}</el-tag>
        <span class="inspector__id">{{ draft.id }}</span>
        <el-button link type="danger" size="small" @click="emit('remove', draft.id)">删除节点</el-button>
      </div>
      <p class="inspector__summary">{{ meta.summary }}</p>
      <el-form label-position="top" size="small">
        <el-form-item label="节点名称">
          <el-input :model-value="draft.title" @update:model-value="setTitle" />
        </el-form-item>
        <el-form-item v-for="field in fields" :key="field.key" :label="field.label">
          <el-input
            v-if="field.kind === 'text'"
            :model-value="fieldValue(field.key)"
            :placeholder="field.placeholder || ''"
            @update:model-value="(value) => setField(field.key, value)"
          />
          <el-input
            v-else-if="field.kind === 'textarea'"
            type="textarea"
            :rows="field.rows || 3"
            :model-value="fieldValue(field.key)"
            @update:model-value="(value) => setField(field.key, value)"
          />
          <el-input-number
            v-else-if="field.kind === 'number'"
            :model-value="fieldValue(field.key)"
            :step="field.step || 1"
            :min="field.min"
            :max="field.max"
            controls-position="right"
            class="inspector__number"
            @update:model-value="(value) => setField(field.key, value === undefined ? null : value)"
          />
          <el-select
            v-else-if="field.kind === 'select'"
            :model-value="fieldValue(field.key)"
            class="inspector__select"
            @update:model-value="(value) => setField(field.key, value)"
          >
            <el-option v-for="option in field.options" :key="option" :label="option" :value="option" />
          </el-select>
          <KeyValueEditor
            v-else-if="field.kind === 'keyvalue'"
            :model-value="fieldValue(field.key) || {}"
            @update:model-value="(value) => setField(field.key, value)"
          />
          <StringListEditor
            v-else-if="field.kind === 'stringlist'"
            :model-value="fieldValue(field.key) || []"
            @update:model-value="(value) => setField(field.key, value)"
          />
          <RowsEditor
            v-else-if="field.kind === 'rows'"
            :model-value="fieldValue(field.key) || []"
            :columns="field.columns || []"
            @update:model-value="(value) => setField(field.key, value)"
          />
          <p v-if="field.help" class="inspector__help">{{ field.help }}</p>
        </el-form-item>
      </el-form>
    </template>
  </div>
</template>

<style scoped>
.inspector__empty {
  color: var(--el-text-color-secondary);
  text-align: center;
  margin-top: 32px;
}

.inspector__head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.inspector__id {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.inspector__summary {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.inspector__help {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.inspector__number,
.inspector__select {
  width: 100%;
}
</style>
