import vue from '@vitejs/plugin-vue'
import { loadEnv } from 'vite'
import { configDefaults, defineConfig } from 'vitest/config'
import { resolve } from 'node:path'
import tailwindcss from 'tailwindcss'
import autoprefixer from 'autoprefixer'

import { mergeTripPilotEnv } from './vite-env'

export default defineConfig(({ mode }) => {
  const repositoryEnvDir = resolve(import.meta.dirname, '../..')
  const webEnvDir = resolve(import.meta.dirname)
  const env = mergeTripPilotEnv(
    loadEnv(mode, repositoryEnvDir, ''),
    loadEnv(mode, webEnvDir, ''),
  )

  return {
    envDir: webEnvDir,
    define: {
      'import.meta.env.VITE_AMAP_WEB_JS_KEY': JSON.stringify(env.VITE_AMAP_WEB_JS_KEY || ''),
      'import.meta.env.VITE_AMAP_SECURITY_CODE': JSON.stringify(env.VITE_AMAP_SECURITY_CODE || ''),
    },
    css: {
      postcss: {
        plugins: [
          tailwindcss(),
          autoprefixer(),
        ],
      },
    },
    plugins: [vue()],
    server: {
      proxy: {
        '/api': env.TRAVEL_SERVER_URL || 'http://localhost:8080',
      },
    },
    test: {
      environment: 'jsdom',
      exclude: [...configDefaults.exclude, 'e2e/**'],
      coverage: {
        provider: 'v8',
        include: [
          'src/components/TripMap.vue',
          'src/lib/amap.ts',
          'src/lib/map.ts',
          'src/lib/feasibility.ts',
          'src/components/FeasibilityReportPanel.vue',
          'src/components/PlanningReviewPanel.vue',
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
