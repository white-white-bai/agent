import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const target = process.env.AP_UI_PROXY_TARGET || 'http://127.0.0.1:8900'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5199,
    proxy: Object.fromEntries(
      ['/admin', '/v1', '/api', '/healthz'].map((path) => [path, { target, changeOrigin: true }]),
    ),
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.js'],
    include: ['tests/**/*.spec.js'],
  },
})
