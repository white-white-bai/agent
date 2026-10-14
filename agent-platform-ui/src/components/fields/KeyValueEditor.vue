<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
  keyPlaceholder: { type: String, default: '键' },
  valuePlaceholder: { type: String, default: '值' },
})
const emit = defineEmits(['update:modelValue'])

const rows = ref([])

function toRows(value) {
  return Object.entries(value || {}).map(([key, item]) => ({
    key,
    value: item === null || item === undefined ? '' : String(item),
  }))
}

function toObject(items) {
  const result = {}
  items.forEach((item) => {
    if (item.key) {
      result[item.key] = item.value
    }
  })
  return result
}

watch(
  () => props.modelValue,
  (value) => {
    if (JSON.stringify(toObject(rows.value)) === JSON.stringify(value || {})) {
      return
    }
    rows.value = toRows(value)
  },
  { immediate: true, deep: true },
)

function commit() {
  emit('update:modelValue', toObject(rows.value))
}

function addRow() {
  rows.value.push({ key: '', value: '' })
}

function removeRow(index) {
  rows.value.splice(index, 1)
  commit()
}
</script>

<template>
  <div class="kv">
    <div v-for="(row, index) in rows" :key="index" class="kv__row">
      <el-input v-model="row.key" :placeholder="keyPlaceholder" @change="commit" />
      <el-input v-model="row.value" :placeholder="valuePlaceholder" @change="commit" />
      <el-button link type="danger" @click="removeRow(index)">删除</el-button>
    </div>
    <el-button link type="primary" @click="addRow">新增一行</el-button>
  </div>
</template>

<style scoped>
.kv__row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
</style>
