<script setup>
import { ref } from 'vue'

import { useAuthStore } from '@/stores/auth'

defineProps({
  documents: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  dataset: { type: Object, default: null },
})
const emit = defineEmits(['refresh', 'upload', 'create', 'segments', 'reindex', 'remove'])
const auth = useAuthStore()
const selected = ref([])

const STATUS = {
  pending: { type: 'info', label: '入库中' },
  ready: { type: 'success', label: '已完成' },
  failed: { type: 'danger', label: '失败' },
}

function statusOf(row) {
  return STATUS[row.status] || { type: 'info', label: row.status || '未知' }
}

function formatSize(bytes) {
  if (!bytes) {
    return '-'
  }
  if (bytes < 1024) {
    return `${bytes} B`
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function onSelectionChange(rows) {
  selected.value = rows
}

function removeSelected() {
  emit('remove', selected.value)
}
</script>

<template>
  <div class="docs">
    <div class="docs__head">
      <span class="docs__title">{{ dataset ? dataset.name : '未选择知识库' }}</span>
      <span class="docs__spacer" />
      <el-button size="small" @click="emit('refresh')">刷新</el-button>
      <template v-if="auth.can('knowledge:write') && dataset">
        <el-button size="small" @click="emit('upload')">上传文件</el-button>
        <el-button size="small" type="primary" @click="emit('create')">新增文本</el-button>
        <el-button size="small" type="danger" :disabled="!selected.length" @click="removeSelected">
          批量删除
        </el-button>
      </template>
    </div>

    <el-table v-loading="loading" :data="documents" border @selection-change="onSelectionChange">
      <el-table-column type="selection" width="42" />
      <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
      <el-table-column prop="file_type" label="类型" width="80" />
      <el-table-column label="大小" width="100">
        <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
      </el-table-column>
      <el-table-column prop="chunk_count" label="分段" width="70" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tooltip :disabled="!row.error" :content="row.error">
            <el-tag size="small" :type="statusOf(row).type">{{ statusOf(row).label }}</el-tag>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180" show-overflow-tooltip />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="emit('segments', row)">分段</el-button>
          <el-button v-if="auth.can('knowledge:write')" link type="primary" @click="emit('reindex', row)">重传</el-button>
          <el-button v-if="auth.can('knowledge:write')" link type="danger" @click="emit('remove', [row])">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.docs__head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.docs__title {
  font-weight: 600;
}

.docs__spacer {
  flex: 1;
}
</style>
