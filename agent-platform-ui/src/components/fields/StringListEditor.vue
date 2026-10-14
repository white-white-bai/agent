<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  placeholder: { type: String, default: '值' },
})
const emit = defineEmits(['update:modelValue'])

const rows = ref([])

function toRows(value) {
  return (Array.isArray(value) ? value : []).map((item) => (item === null || item === undefined ? '' : String(item)))
}

watch(
  () => props.modelValue,
  (value) => {
    const next = toRows(value)
    if (JSON.stringify(rows.value) === JSON.stringify(next)) {
      return
    }
    rows.value = next
  },
  { immediate: true, deep: true },
)

function commit() {
  emit('update:modelValue', rows.value.filter((item) => item !== ''))
}

function addRow() {
  rows.value.push('')
}

function removeRow(index) {
  rows.value.splice(index, 1)
  commit()
}
</script>

<template>
  <div class="list">
    <div v-for="(row, index) in rows" :key="index" class="list__row">
      <el-input v-model="rows[index]" :placeholder="placeholder" @change="commit" />
      <el-button link type="danger" @click="removeRow(index)">删除</el-button>
    </div>
    <el-button link type="primary" @click="addRow">新增一项</el-button>
  </div>
</template>

<style scoped>
.list__row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
</style>
