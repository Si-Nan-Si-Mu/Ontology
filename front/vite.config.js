import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import vueDevTools from 'vite-plugin-vue-devtools'

/** 开发时把仓库根目录的 chat.json 映射到 GET /chat.json（便于联调 wx 导出文件，勿用于生产构建） */
function serveRepoChatJsonDev() {
  const frontDir = fileURLToPath(new URL('.', import.meta.url))
  const repoChatJson = path.resolve(frontDir, '..', 'chat.json')
  return {
    name: 'serve-repo-chat-json-dev',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const pathname = req.url?.split('?')[0]
        if (pathname !== '/chat.json') {
          next()
          return
        }
        if (!fs.existsSync(repoChatJson)) {
          next()
          return
        }
        res.setHeader('Content-Type', 'application/json; charset=utf-8')
        fs.createReadStream(repoChatJson).pipe(res)
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    serveRepoChatJsonDev(),
    vue(),
    vueJsx(),
    vueDevTools(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
  },
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/docs': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/openapi.json': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/redoc': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
