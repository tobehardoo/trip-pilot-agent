import vue from '@vitejs/plugin-vue'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [vue()],
    server: {
      proxy: {
        '/api': env.TRAVEL_SERVER_URL || 'http://localhost:8080',
      },
    },
    test: {
      environment: 'jsdom',
    },
  }
})
