<script setup>
import { ref, toRaw, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  columns: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue'])

const rows = ref([])
const raw = ref({})

function cellKey(index, key) {
  return `${index}:${key}`
}

function emptyRow() {
  const row = {}
  props.columns.forEach((column) => {
    row[column.key] = column.kind === 'json' ? {} : ''
  })
  return row
}

function syncRaw(list) {
  const map = {}
  list.forEach((row, index) => {
    props.columns.forEach((column) => {
      if (column.kind === 'json') {
        const value = row[column.key]
        map[cellKey(index, column.key)] = JSON.stringify(value === undefined || value === null ? {} : value)
      }
    })
  })
  raw.value = map
}

watch(
  () => props.modelValue,
  (value) => {
    const list = Array.isArray(value) ? value : []
    if (JSON.stringify(list) === JSON.stringify(rows.value)) {
      return
    }
    rows.value = structuredClone(toRaw(list))
    syncRaw(rows.value)
  },
  { immediate: true, deep: true },
)

function commit() {
  emit('update:modelValue', structuredClone(toRaw(rows.value)))
}

function addRow() {
  rows.value.push(emptyRow())
  syncRaw(rows.value)
  commit()
}

function removeRow(index) {
  rows.value.splice(index, 1)
  syncRaw(rows.value)
  commit()
}

function setJson(index, key, text) {
  raw.value[cellKey(index, key)] = text
  try {
    rows.value[index][key] = JSON.parse(text)
  } catch {
    return
  }
  commit()
}
</script>

<template>
  <div class="rows">
    <div v-for="(row, index) in rows" :key="index" class="rows__row">
      <div v-for="column in columns" :key="column.key" class="rows__cell">
        <span class="rows__label">{{ column.label }}</span>
        <el-input
          v-if="column.kind === 'json'"
          type="textarea"
          :rows="2"
          :model-value="raw[cellKey(index, column.key)]"
          @update:model-value="(text) => setJson(index, column.key, text)"
        />
        <el-input v-else v-model="row[column.key]" @change="commit" />
      </div>
      <el-button link type="danger" class="rows__remove" @click="removeRow(index)">删除</el-button>
    </div>
    <el-button link type="primary" @click="addRow">新增一行</el-button>
  </div>
</template>

<style scoped>
.rows__row {
  position: relative;
  padding: 6px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}

.rows__cell {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.rows__label {
  flex: none;
  width: 72px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.rows__remove {
  position: absolute;
  top: 6px;
  right: 0;
}
</style>
