import vue from '@vitejs/plugin-vue'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import { resolve } from 'node:path'

export default defineConfig(({ mode }) => {
  const envDir = resolve(import.meta.dirname, '../..')
  const env = loadEnv(mode, envDir, '')

  return {
    envDir,
    plugins: [vue()],
    server: {
      proxy: {
        '/api': env.TRAVEL_SERVER_URL || 'http://localhost:8080',
      },
    },
    test: {
      environment: 'jsdom',
      coverage: {
        provider: 'v8',
        include: [
          'src/components/TripMap.vue',
          'src/lib/amap.ts',
          'src/lib/map.ts',
        ],
        reporter: ['text'],
        thresholds: {
          branches: 80,
          functions: 80,
          lines: 80,
          statements: 80,
        },
      },
    },
  }
})
