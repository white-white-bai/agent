<script setup>
import { reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { deleteSegment, listSegments, updateSegment } from '@/api'
import { useAuthStore } from '@/stores/auth'

const props = defineProps({
  visible: { type: Boolean, default: false },
  document: { type: Object, default: null },
})
const emit = defineEmits(['update:visible', 'changed'])
const auth = useAuthStore()

const rows = ref([])
const loading = ref(false)
const edit = reactive({ visible: false, uuid: '', content: '', saving: false })

async function load() {
  if (!props.document) {
    return
  }
  loading.value = true
  try {
    const data = await listSegments(props.document.uuid, { page: 1, size: 200 })
    rows.value = (data && data.items) || []
  } catch (error) {
    ElMessage.error(error.message || '分段加载失败')
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.visible, props.document && props.document.uuid],
  ([visible]) => {
    if (visible) {
      load()
    }
  },
  { immediate: true },
)

async function toggle(row) {
  try {
    await updateSegment(row.uuid, { enabled: row.enabled ? 0 : 1 })
    row.enabled = row.enabled ? 0 : 1
    emit('changed')
  } catch (error) {
    ElMessage.error(error.message || '启停失败')
  }
}

function openEdit(row) {
  Object.assign(edit, { visible: true, uuid: row.uuid, content: row.content })
}

async function submitEdit() {
  edit.saving = true
  try {
    await updateSegment(edit.uuid, { content: edit.content })
    edit.visible = false
    ElMessage.success('已保存并重新向量化')
    await load()
    emit('changed')
  } catch (error) {
    ElMessage.error(error.message || '保存失败')
  } finally {
    edit.saving = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm('确认删除该分段？', '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteSegment(row.uuid)
    ElMessage.success('已删除')
    await load()
    emit('changed')
  } catch (error) {
    ElMessage.error(error.message || '删除失败')
  }
}
</script>

<template>
  <el-drawer
    :model-value="visible"
    :title="document ? `分段 · ${document.name}` : '分段'"
    size="620px"
    @update:model-value="(value) => emit('update:visible', value)"
  >
    <div v-loading="loading" class="segments">
      <p v-if="!rows.length" class="segments__empty">暂无分段</p>
      <div v-for="(row, index) in rows" :key="row.uuid" class="segments__item">
        <div class="segments__head">
          <span class="segments__index">#{{ index + 1 }}</span>
          <el-tag v-if="!row.enabled" size="small" type="info">已停用</el-tag>
          <span class="segments__spacer" />
          <el-button v-if="auth.can('knowledge:write')" link type="primary" size="small" @click="toggle(row)">
            {{ row.enabled ? '停用' : '启用' }}
          </el-button>
          <el-button v-if="auth.can('knowledge:write')" link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="auth.can('knowledge:write')" link type="danger" size="small" @click="remove(row)">删除</el-button>
        </div>
        <p class="segments__content">{{ row.content }}</p>
      </div>
    </div>

    <el-dialog v-model="edit.visible" title="编辑分段" width="560px" append-to-body>
      <el-input v-model="edit.content" type="textarea" :rows="8" />
      <template #footer>
        <el-button @click="edit.visible = false">取消</el-button>
        <el-button type="primary" :loading="edit.saving" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </el-drawer>
</template>

<style scoped>
.segments__empty {
  color: var(--el-text-color-secondary);
  text-align: center;
  margin-top: 24px;
}

.segments__item {
  border-bottom: 1px dashed var(--el-border-color-lighter);
  padding: 8px 0;
}

.segments__head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.segments__index {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.segments__spacer {
  flex: 1;
}

.segments__content {
  margin: 4px 0 0;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--el-text-color-regular);
}
</style>
