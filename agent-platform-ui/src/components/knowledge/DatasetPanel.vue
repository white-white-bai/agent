<script setup>
import { useAuthStore } from '@/stores/auth'

defineProps({
  datasets: { type: Array, default: () => [] },
  selected: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['select', 'create', 'edit', 'remove'])
const auth = useAuthStore()
</script>

<template>
  <div v-loading="loading" class="datasets">
    <div class="datasets__head">
      <span class="datasets__title">知识库</span>
      <el-button v-if="auth.can('knowledge:write')" size="small" type="primary" @click="emit('create')">新建</el-button>
    </div>
    <p v-if="!datasets.length" class="datasets__empty">暂无知识库</p>
    <div
      v-for="item in datasets"
      :key="item.uuid"
      class="datasets__item"
      :class="{ 'datasets__item--active': item.uuid === selected }"
      @click="emit('select', item.uuid)"
    >
      <div class="datasets__name">{{ item.name || item.uuid }}</div>
      <div class="datasets__meta">{{ item.document_count }} 篇文档</div>
      <div v-if="auth.can('knowledge:write')" class="datasets__actions" @click.stop>
        <el-button link type="primary" size="small" @click="emit('edit', item)">编辑</el-button>
        <el-button link type="danger" size="small" @click="emit('remove', item)">删除</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.datasets__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.datasets__title {
  font-weight: 600;
}

.datasets__empty {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  text-align: center;
  margin-top: 24px;
}

.datasets__item {
  padding: 8px 10px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  margin-bottom: 8px;
  cursor: pointer;
}

.datasets__item--active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.datasets__name {
  font-size: 14px;
  word-break: break-all;
}

.datasets__meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.datasets__actions {
  margin-top: 4px;
}
</style>
