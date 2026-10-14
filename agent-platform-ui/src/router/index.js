import { createRouter, createWebHistory } from 'vue-router'

import AdminLayout from '@/layouts/AdminLayout.vue'

export const MENU_PAGES = [
  {
    path: '/apps',
    name: 'apps',
    component: () => import('@/views/AppsView.vue'),
    meta: { title: '应用注册', icon: 'Grid', permission: 'app:read' },
  },
  {
    path: '/providers',
    name: 'providers',
    component: () => import('@/views/ProvidersView.vue'),
    meta: { title: '模型与检索', icon: 'Cpu', permission: 'provider:read' },
  },
  {
    path: '/mcp',
    name: 'mcp',
    component: () => import('@/views/McpServersView.vue'),
    meta: { title: 'MCP 工具', icon: 'Connection', permission: 'mcp:read' },
  },
  {
    path: '/knowledge',
    name: 'knowledge',
    component: () => import('@/views/KnowledgeView.vue'),
    meta: { title: '知识库', icon: 'Notebook', permission: 'knowledge:read' },
  },
  {
    path: '/guards',
    name: 'guards',
    component: () => import('@/views/GuardsView.vue'),
    meta: { title: '护栏配置', icon: 'Lock', permission: 'guard:read' },
  },
  {
    path: '/accounts',
    name: 'accounts',
    component: () => import('@/views/AccountsView.vue'),
    meta: { title: '账号与角色', icon: 'User', permission: 'user:read' },
  },
  {
    path: '/metrics',
    name: 'metrics',
    component: () => import('@/views/MetricsView.vue'),
    meta: { title: '监控看板', icon: 'DataLine', permission: 'metrics:read' },
  },
]

export const GRAPH_PAGE = {
  path: '/apps/:appUuid/graph',
  name: 'graph',
  component: () => import('@/views/GraphEditorView.vue'),
  meta: { title: '图编排', icon: 'Share', permission: 'graph:read', hidden: true },
}

export const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    component: AdminLayout,
    redirect: '/apps',
    children: [...MENU_PAGES, GRAPH_PAGE],
  },
  {
    path: '/403',
    name: 'forbidden',
    component: () => import('@/views/ForbiddenView.vue'),
    meta: { title: '无权限', hidden: true },
  },
  { path: '/:pathMatch(.*)*', redirect: '/apps' },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
