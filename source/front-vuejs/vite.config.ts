import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: '/dashboard/',
  plugins: [vue()],
  build: {
    outDir: 'dist/dashboard',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        dashboard: resolve(__dirname, 'index.html'),
        ide: resolve(__dirname, 'ide.html'),
        metrics: resolve(__dirname, 'metrics.html')
      }
    }
  },
  server: {
    port: 5173,
    host: true
  }
})
