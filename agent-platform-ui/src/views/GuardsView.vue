<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { createSensitiveWord, deleteSensitiveWord, getGuardConfig, listSensitiveWords } from '@/api'
import { useTable } from '@/composables/useTable'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const filter = reactive({ tenant_code: '' })
const { data: guardConfig, loading: guardLoading } = useTable(() => getGuardConfig())
const { rows: words, loading: wordsLoading, reload: reloadWords } = useTable(() =>
  listSensitiveWords({ tenant_code: filter.tenant_code }),
)

const dialogVisible = ref(false)
const saving = ref(false)
const form = reactive({ tenant_code: '', word: '' })

const switches = computed(() => {
  const config = guardConfig.value || {}
  return [
    { label: '护栏总开关', value: config.enabled, hint: '关闭时全部护栏不生效' },
    { label: '敏感词', value: config.sensitive_enabled, hint: '命中敏感词走兜底回复' },
    { label: '配额', value: config.quota_enabled, hint: `每日 token 上限 ${config.daily_token_quota ?? '-'}` },
    { label: '限流', value: config.rate_enabled, hint: `每分钟 ${config.rate_per_minute ?? '-'} 次` },
    { label: '轮次', value: config.round_enabled, hint: `单会话最多 ${config.max_rounds ?? '-'} 轮` },
  ]
})

function openCreate() {
  Object.assign(form, { tenant_code: filter.tenant_code, word: '' })
  dialogVisible.value = true
}

async function submit() {
  if (!form.word) {
    ElMessage.warning('请填写敏感词')
    return
  }
  saving.value = true
  try {
    await createSensitiveWord({ tenant_code: form.tenant_code, word: form.word })
    dialogVisible.value = false
    ElMessage.success('已新增')
    await reloadWords()
  } catch (error) {
    ElMessage.error(error.message || '新增失败')
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确认删除敏感词「${row.word}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteSensitiveWord(row.id)
    ElMessage.success('已删除')
    await reloadWords()
  } catch (error) {
    ElMessage.error(error.message || '删除失败')
  }
}
</script>

<template>
  <div>
    <el-card v-loading="guardLoading" shadow="never" class="card">
      <template #header>护栏开关（进程级配置，只读）</template>
      <el-descriptions :column="1" border>
        <el-descriptions-item v-for="item in switches" :key="item.label" :label="item.label">
          <el-tag :type="item.value ? 'success' : 'info'" size="small">{{ item.value ? '开启' : '关闭' }}</el-tag>
          <span class="hint">{{ item.hint }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="兜底回复">{{ (guardConfig && guardConfig.default_reply) || '（空）' }}</el-descriptions-item>
      </el-descriptions>
      <p class="hint">开关由服务端环境变量驱动，修改后需重启进程；双跑期与 Java 侧保持一致。</p>
    </el-card>

    <el-card shadow="never">
      <template #header>敏感词</template>
      <div class="toolbar">
        <el-input v-model="filter.tenant_code" placeholder="租户编码（留空为全部）" class="toolbar__input" @keyup.enter="reloadWords()" />
        <el-button @click="reloadWords()">查询</el-button>
        <el-button v-if="auth.can('guard:write')" type="primary" @click="openCreate">新增敏感词</el-button>
      </div>
      <el-table v-loading="wordsLoading" :data="words" border>
        <el-table-column prop="word" label="敏感词" min-width="180" />
        <el-table-column prop="tenant_code" label="租户" width="140" />
        <el-table-column prop="id" label="id" width="90" />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button v-if="auth.can('guard:write')" link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="新增敏感词" width="420px">
      <el-form label-position="top">
        <el-form-item label="敏感词">
          <el-input v-model="form.word" />
        </el-form-item>
        <el-form-item label="租户编码（留空取默认租户）">
          <el-input v-model="form.tenant_code" />
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
.card {
  margin-bottom: 16px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.toolbar__input {
  width: 240px;
}

.hint {
  margin-left: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
