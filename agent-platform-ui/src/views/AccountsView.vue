<script setup>
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { createRole, createUser, deleteRole, deleteUser, listRoles, listUsers, updateUser } from '@/api'
import { useTable } from '@/composables/useTable'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const { rows: users, loading: usersLoading, reload: reloadUsers } = useTable(() => listUsers())
const { rows: roles, loading: rolesLoading, reload: reloadRoles } = useTable(() => listRoles())

const roleOptions = ref([])
async function loadRoleOptions() {
  try {
    roleOptions.value = (await listRoles()) || []
  } catch {
    roleOptions.value = []
  }
}
loadRoleOptions()

const userDialog = ref(false)
const editing = ref(null)
const saving = ref(false)
const userForm = reactive({ username: '', password: '', display_name: '', role_code: 'viewer', tenant_code: '' })

const roleDialog = ref(false)
const roleForm = reactive({ code: '', name: '', permissions: '' })

function openCreateUser() {
  editing.value = null
  Object.assign(userForm, { username: '', password: '', display_name: '', role_code: 'viewer', tenant_code: '' })
  userDialog.value = true
}

function openEditUser(row) {
  editing.value = row
  Object.assign(userForm, {
    username: row.username,
    password: '',
    display_name: row.display_name || '',
    role_code: row.role_code || 'viewer',
    tenant_code: row.tenant_code || '',
  })
  userDialog.value = true
}

async function submitUser() {
  if (!editing.value && (!userForm.username || !userForm.password)) {
    ElMessage.warning('请填写账号与口令')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      const payload = { role_code: userForm.role_code, tenant_code: userForm.tenant_code, display_name: userForm.display_name }
      if (userForm.password) {
        payload.password = userForm.password
      }
      await updateUser(editing.value.uuid, payload)
    } else {
      await createUser({ ...userForm })
    }
    userDialog.value = false
    ElMessage.success('已保存')
    await reloadUsers()
  } catch (error) {
    ElMessage.error(error.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function removeUser(row) {
  try {
    await ElMessageBox.confirm(`确认删除账号「${row.username}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteUser(row.uuid)
    ElMessage.success('已删除')
    await reloadUsers()
  } catch (error) {
    ElMessage.error(error.message || '删除失败')
  }
}

async function submitRole() {
  if (!roleForm.code) {
    ElMessage.warning('请填写角色编码')
    return
  }
  saving.value = true
  try {
    await createRole({
      code: roleForm.code,
      name: roleForm.name,
      permissions: roleForm.permissions.split(',').map((item) => item.trim()).filter(Boolean),
    })
    roleDialog.value = false
    roleForm.code = ''
    roleForm.name = ''
    roleForm.permissions = ''
    ElMessage.success('已新增')
    await reloadRoles()
    await loadRoleOptions()
  } catch (error) {
    ElMessage.error(error.message || '新增失败')
  } finally {
    saving.value = false
  }
}

async function removeRole(row) {
  try {
    await ElMessageBox.confirm(`确认删除角色「${row.code}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteRole(row.code)
    ElMessage.success('已删除')
    await reloadRoles()
    await loadRoleOptions()
  } catch (error) {
    ElMessage.error(error.message || '删除失败')
  }
}
</script>

<template>
  <div>
    <el-card shadow="never" class="card">
      <template #header>
        <div class="head">
          <span>账号</span>
          <el-button v-if="auth.can('user:write')" type="primary" size="small" @click="openCreateUser">新增账号</el-button>
        </div>
      </template>
      <el-table v-loading="usersLoading" :data="users" border>
        <el-table-column prop="username" label="账号" min-width="140" />
        <el-table-column prop="display_name" label="显示名" min-width="140" />
        <el-table-column prop="role_code" label="角色" width="120" />
        <el-table-column prop="tenant_code" label="租户" width="140" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button v-if="auth.can('user:write')" link type="primary" @click="openEditUser(row)">编辑</el-button>
            <el-button v-if="auth.can('user:write')" link type="danger" @click="removeUser(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span>角色</span>
          <el-button v-if="auth.can('role:write')" type="primary" size="small" @click="roleDialog = true">新增角色</el-button>
        </div>
      </template>
      <el-table v-loading="rolesLoading" :data="roles" border>
        <el-table-column prop="code" label="编码" width="140" />
        <el-table-column prop="name" label="名称" width="160" />
        <el-table-column label="权限点" min-width="280">
          <template #default="{ row }">
            <el-tag v-for="permission in row.permissions || []" :key="permission" size="small" class="perm">{{ permission }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="内置" width="80">
          <template #default="{ row }">{{ row.is_builtin ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button v-if="auth.can('role:write')" link type="danger" @click="removeRole(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="userDialog" :title="editing ? '编辑账号' : '新增账号'" width="460px">
      <el-form label-position="top">
        <el-form-item label="账号">
          <el-input v-model="userForm.username" :disabled="Boolean(editing)" />
        </el-form-item>
        <el-form-item :label="editing ? '口令（留空不修改）' : '口令'">
          <el-input v-model="userForm.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="userForm.display_name" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="userForm.role_code">
            <el-option v-for="role in roleOptions" :key="role.code" :label="`${role.name || role.code}`" :value="role.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="租户编码（留空取默认租户）">
          <el-input v-model="userForm.tenant_code" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitUser">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="roleDialog" title="新增角色" width="460px">
      <el-form label-position="top">
        <el-form-item label="角色编码">
          <el-input v-model="roleForm.code" />
        </el-form-item>
        <el-form-item label="角色名称">
          <el-input v-model="roleForm.name" />
        </el-form-item>
        <el-form-item label="权限点（逗号分隔）">
          <el-input v-model="roleForm.permissions" placeholder="app:read,graph:read" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitRole">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.card {
  margin-bottom: 16px;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.perm {
  margin: 0 4px 4px 0;
}
</style>
