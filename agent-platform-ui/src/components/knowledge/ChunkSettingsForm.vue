<script setup>
import { reactive, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue'])

const form = reactive({
  qa_mode: false,
  separator: '\n\n',
  max_chars: 500,
  overlap_chars: 50,
  replace_whitespace: true,
  remove_urls_emails: false,
})

watch(
  () => props.modelValue,
  (value) => {
    const raw = value || {}
    const pre = raw.preprocess || {}
    form.qa_mode = Boolean(raw.qa_mode)
    form.separator = raw.separator ?? '\n\n'
    form.max_chars = raw.max_chars ?? 500
    form.overlap_chars = raw.overlap_chars ?? 50
    form.replace_whitespace = pre.replace_whitespace !== false
    form.remove_urls_emails = Boolean(pre.remove_urls_emails)
  },
  { immediate: true, deep: true },
)

function emitConfig() {
  emit('update:modelValue', {
    qa_mode: form.qa_mode,
    separator: form.separator || '\n\n',
    max_chars: form.max_chars,
    overlap_chars: form.overlap_chars,
    preprocess: {
      replace_whitespace: form.replace_whitespace,
      remove_urls_emails: form.remove_urls_emails,
    },
  })
}
</script>

<template>
  <el-form label-position="top" size="small" class="chunk">
    <el-form-item label="分段模式">
      <el-radio-group v-model="form.qa_mode" @change="emitConfig">
        <el-radio :value="false">通用</el-radio>
        <el-radio :value="true">Q&A（按问句成对）</el-radio>
      </el-radio-group>
    </el-form-item>
    <el-form-item label="分段标识符">
      <el-input v-model="form.separator" placeholder="\n\n" @change="emitConfig" />
    </el-form-item>
    <div class="chunk__row">
      <el-form-item label="分段最大长度（字符）">
        <el-input-number v-model="form.max_chars" :min="1" controls-position="right" @change="emitConfig" />
      </el-form-item>
      <el-form-item label="分段重叠长度（字符）">
        <el-input-number v-model="form.overlap_chars" :min="0" controls-position="right" @change="emitConfig" />
      </el-form-item>
    </div>
    <el-form-item label="文本预处理规则">
      <div class="chunk__checks">
        <el-checkbox v-model="form.replace_whitespace" @change="emitConfig">替换掉连续的空格、换行符和制表符</el-checkbox>
        <el-checkbox v-model="form.remove_urls_emails" @change="emitConfig">删除所有 URL 和电子邮件地址</el-checkbox>
      </div>
    </el-form-item>
  </el-form>
</template>

<style scoped>
.chunk__row {
  display: flex;
  gap: 16px;
}

.chunk__checks {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}
</style>
