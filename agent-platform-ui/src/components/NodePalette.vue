<script setup>
import { NODE_TYPES } from '@/graph/nodeMeta'

defineProps({
  types: { type: Array, default: () => NODE_TYPES },
})
const emit = defineEmits(['add'])
</script>

<template>
  <div class="palette">
    <p class="palette__title">节点</p>
    <button v-for="meta in types" :key="meta.type" type="button" class="palette__item" :title="meta.summary" @click="emit('add', meta.type)">
      <span class="palette__dot" :style="{ background: meta.color }" />
      <span class="palette__label">{{ meta.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.palette__title {
  margin: 0 0 8px;
  font-weight: 600;
  font-size: 13px;
}

.palette__item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 8px;
  margin-bottom: 6px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  background: var(--el-fill-color-blank);
  cursor: pointer;
  font-size: 13px;
}

.palette__item:hover {
  border-color: var(--el-color-primary);
}

.palette__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
</style>
