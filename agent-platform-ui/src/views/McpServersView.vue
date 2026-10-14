<script setup>
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { createMcpServer, deleteMcpServer, listMcpServers } from '@/api'
import { useTable } from '@/composables/useTable'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const tenantCode = ref('')
const { rows, loading, reload } = useTable(() => listMcpServers({ tenant_code: tenantCode.value }))

const dialogVisible = ref(false)
const saving = ref(false)
const form = reactive({ name: '', kind: 'mcp', url: '', tenant_code: '', headers: '{}' })

function openCreate() {
  Object.assign(form, { name: '', kind: 'mcp', url: '', tenant_code: '', headers: '{}' })
  dialogVisible.value = true
}

async function submit() {
  if (!form.name || !form.url) {
    ElMessage.warning('请填写名称与地址')
    return
  }
  let headers = {}
  try {
    headers = form.headers ? JSON.parse(form.headers) : {}
  } catch {
    ElMessage.warning('请求头须为合法 JSON')
    return
  }
  saving.value = true
  try {
    await createMcpServer({
      name: form.name,
      kind: form.kind,
      url: form.url,
      tenant_code: form.tenant_code,
      headers,
    })
    dialogVisible.value = false
    ElMessage.success('已保存')
    await reload()
  } catch (error) {
    ElMessage.error(error.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确认删除 MCP Server「${row.name}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteMcpServer(row.uuid)
    ElMessage.success('已删除')
    await reload()
  } catch (error) {
    ElMessage.error(error.message || '删除失败')
  }
}
</script>

<template>
  <div>
    <div class="toolbar">
      <el-input v-model="tenantCode" placeholder="租户编码（留空为全部）" class="toolbar__input" @keyup.enter="reload()" />
      <el-button @click="reload()">查询</el-button>
      <el-button v-if="auth.can('mcp:write')" type="primary" @click="openCreate">注册 MCP Server</el-button>
    </div>
    <el-table v-loading="loading" :data="rows" border>
      <el-table-column prop="name" label="名称" min-width="150" />
      <el-table-column prop="kind" label="类型" width="100" />
      <el-table-column prop="url" label="地址" min-width="240" show-overflow-tooltip />
      <el-table-column prop="tenant_code" label="租户" width="120" />
      <el-table-column label="请求头" min-width="160">
        <template #default="{ row }">{{ Object.keys(row.headers || {}).join(', ') || '-' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button v-if="auth.can('mcp:write')" link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" title="注册 MCP Server" width="520px">
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.kind">
            <el-option label="mcp" value="mcp" />
            <el-option label="sse" value="sse" />
            <el-option label="stdio" value="stdio" />
          </el-select>
        </el-form-item>
        <el-form-item label="地址">
          <el-input v-model="form.url" placeholder="http://host:port/sse" />
        </el-form-item>
        <el-form-item label="租户编码（留空取默认租户）">
          <el-input v-model="form.tenant_code" />
        </el-form-item>
        <el-form-item label="请求头（JSON）">
          <el-input v-model="form.headers" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.toolbar__input {
  width: 240px;
}
</style>
