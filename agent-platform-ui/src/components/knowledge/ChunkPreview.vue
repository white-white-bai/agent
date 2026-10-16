<script setup>
defineProps({
  chunks: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
})
</script>

<template>
  <div class="preview">
    <div class="preview__head">
      <span class="preview__badge">{{ total }} 预估块</span>
    </div>
    <p v-if="!chunks.length" class="preview__empty">点击「预览块」查看分段结果</p>
    <div v-for="item in chunks" :key="item.position" class="preview__item">
      <div class="preview__index">#{{ item.position + 1 }}</div>
      <p class="preview__content">{{ item.content }}</p>
    </div>
  </div>
</template>

<style scoped>
.preview__head {
  margin-bottom: 8px;
}

.preview__badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.preview__empty {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  text-align: center;
  margin-top: 32px;
}

.preview__item {
  border-bottom: 1px dashed var(--el-border-color-lighter);
  padding: 8px 0;
}

.preview__index {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.preview__content {
  margin: 4px 0 0;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--el-text-color-regular);
}
</style>
