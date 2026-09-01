/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{vue,js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // ── TripPilot Design Baseline（F-UI-6b，2026-09-01）──
        // Developer Tool / AI Agent Workspace 中性体系。
        // 本色板是 workspace 及后续所有新页面的唯一取色来源；
        // 禁止在新代码中引入 primary 彩色装饰、渐变、阴影、大圆角。
        // 基准文档：docs/design/DESIGN-BASELINE.md
        tp: {
          bg: '#F7F7F5', // 应用背景
          panel: '#FCFCFB', // 侧栏 / 面板背景
          line: '#E5E5E5', // 主边框
          div: '#EBEBE9', // 次级分割线
          active: '#EFEFED', // 选中项背景
          hover: '#F2F2F0', // 悬停背景
          ink: '#1F1F1F', // 主文字
          body: '#3D3D3B', // 次级正文
          sub: '#6B6B6B', // 辅助文字
          mute: '#999999', // 弱化文字 / 元信息
          faint: '#C9C9C6', // 占位 / 禁用 / 最弱文字
          ok: '#4A7C59', // Completed（小字形专用）
          run: '#8A8A86', // Running（小圆点/文字专用）
          warn: '#A65D57', // Failed / 提示（低饱和红）
          dot: '#B7B7B3', // 脉冲圆点
        },
        // 旅程风主色 — 珊瑚（方案 A，P2.8b）〔仅限 Phase 2 待迁移的旧页面〕
        primary: {
          50: '#fff1f4',
          100: '#ffe1e7',
          200: '#ffc7d2',
          300: '#ff9eb0',
          400: '#ff6b8a',
          500: '#ff385c',
          600: '#e31c5f',
          700: '#c0134e',
          800: '#9e0f41',
          900: '#7c0c34',
          950: '#4a0720',
        },
        // 旅程风表面 — 暖白→沙色→墨阶
        surface: {
          50: '#fffdf9',
          100: '#f7f4ef',
          200: '#ebe3d9',
          300: '#d9cfc1',
          400: '#a89f93',
          500: '#6b6259',
          600: '#4a443d',
          700: '#35312b',
          800: '#211e1a',
          900: '#141210',
        },
        // 目的地氛围色 — 根据城市自动选择
        destination: {
          guangzhou: {
            from: '#f43f5e',
            via: '#f97316',
            to: '#eab308',
          },
          beijing: {
            from: '#dc2626',
            via: '#b91c1c',
            to: '#7f1d1d',
          },
          hangzhou: {
            from: '#10b981',
            via: '#14b8a6',
            to: '#06b6d4',
          },
          changsha: {
            from: '#f97316',
            via: '#ef4444',
            to: '#e11d48',
          },
          chengdu: {
            from: '#22c55e',
            via: '#10b981',
            to: '#0d9488',
          },
          shanghai: {
            from: '#64748b',
            via: '#475569',
            to: '#1e293b',
          },
          shenzhen: {
            from: '#06b6d4',
            via: '#3b82f6',
            to: '#6366f1',
          },
          default: {
            from: '#ff385c',
            via: '#e31c5f',
            to: '#ff7a45',
          },
        },
        // 暖色强调 — 价格、评分
        warm: {
          50: '#fffbeb',
          100: '#fef3c7',
          400: '#fbbf24',
          500: '#f59e0b',
          600: '#d97706',
          700: '#b45309',
        },
        // 成功/自然色
        nature: {
          50: '#ecfdf5',
          500: '#10b981',
          600: '#059669',
        },
      },
      borderRadius: {
        '2xl': '1rem',
        '3xl': '1.25rem',
        '4xl': '1.75rem',
      },
      boxShadow: {
        'card': '0 1px 3px 0 rgb(0 0 0 / 0.04), 0 1px 2px -1px rgb(0 0 0 / 0.06)',
        'card-hover': '0 4px 12px 0 rgb(0 0 0 / 0.08), 0 2px 4px -2px rgb(0 0 0 / 0.06)',
        'travel-card': '0 2px 16px -4px rgba(0,0,0,0.06), 0 4px 8px -2px rgba(0,0,0,0.04)',
        'travel-card-hover': '0 8px 32px -4px rgba(0,0,0,0.10), 0 4px 16px -4px rgba(0,0,0,0.06)',
        'dialog': '0 20px 60px -12px rgb(0 0 0 / 0.15), 0 8px 24px -8px rgb(0 0 0 / 0.1)',
        'soft': '0 2px 8px -2px rgb(0 0 0 / 0.06), 0 0 1px 0 rgb(0 0 0 / 0.08)',
        'soft-lg': '0 8px 24px -4px rgb(0 0 0 / 0.08), 0 2px 8px -2px rgb(0 0 0 / 0.04)',
        'map-marker': '0 4px 12px rgba(37,99,235,0.3)',
      },
      fontFamily: {
        sans: ['Inter', 'PingFang SC', 'Microsoft YaHei', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.35s cubic-bezier(0.16, 1, 0.3, 1)',
        'slide-down': 'slideDown 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
        'scale-in': 'scaleIn 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
        'slide-in-right': 'slideInRight 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
        'pipeline-dot': 'pipelineDot 1.4s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideDown: {
          '0%': { opacity: '0', transform: 'translateY(-8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        scaleIn: {
          '0%': { opacity: '0', transform: 'scale(0.95)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        slideInRight: {
          '0%': { opacity: '0', transform: 'translateX(8px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        pipelineDot: {
          '0%, 100%': { opacity: '0.4', transform: 'scale(0.8)' },
          '50%': { opacity: '1', transform: 'scale(1.2)' },
        },
      },
      transitionDuration: {
        '400': '400ms',
      },
    },
  },
  plugins: [],
}
