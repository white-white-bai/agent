import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIcons from '@element-plus/icons-vue'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import 'element-plus/dist/index.css'

import App from './App.vue'
import { setUnauthorizedHandler } from './api/client'
import router from './router'
import { createGuard } from './router/guard'
import { useAuthStore } from './stores/auth'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

const auth = useAuthStore(pinia)
setUnauthorizedHandler(() => {
  auth.logout()
  if (router.currentRoute.value.name !== 'login') {
    router.replace({ name: 'login' })
  }
})

router.beforeEach(createGuard(auth))
app.use(router)
app.use(ElementPlus, { locale: zhCn })
Object.entries(ElementPlusIcons).forEach(([name, component]) => app.component(name, component))
app.mount('#app')
