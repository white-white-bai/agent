<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { MENU_PAGES } from '@/router'
import { menuOf } from '@/router/guard'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const menus = computed(() => menuOf(MENU_PAGES, auth))
const activeMenu = computed(() => (route.meta && route.meta.hidden ? '/apps' : route.path))
const title = computed(() => (route.meta && route.meta.title) || 'agent 中台')

function logout() {
  auth.logout()
  router.replace({ name: 'login' })
}
</script>

<template>
  <el-container class="admin-layout">
    <el-aside width="200px" class="admin-layout__aside">
      <div class="admin-layout__brand">agent 中台</div>
      <el-menu :default-active="activeMenu" router>
        <el-menu-item v-for="page in menus" :key="page.path" :index="page.path">
          <el-icon><component :is="page.meta.icon" /></el-icon>
          <span>{{ page.meta.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="admin-layout__header">
        <span class="admin-layout__title">{{ title }}</span>
        <span class="admin-layout__account">
          <el-tag v-if="auth.roleCode" size="small" type="info">{{ auth.roleCode }}</el-tag>
          <span>{{ auth.displayName }}</span>
          <el-button link type="primary" @click="logout">退出</el-button>
        </span>
      </el-header>
      <el-main class="admin-layout__main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.admin-layout {
  height: 100vh;
}

.admin-layout__aside {
  border-right: 1px solid var(--el-border-color-light);
}

.admin-layout__brand {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  letter-spacing: 1px;
}

.admin-layout__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--el-border-color-light);
}

.admin-layout__title {
  font-weight: 600;
}

.admin-layout__account {
  display: flex;
  align-items: center;
  gap: 8px;
}

.admin-layout__main {
  background: var(--el-fill-color-blank);
}
</style>
