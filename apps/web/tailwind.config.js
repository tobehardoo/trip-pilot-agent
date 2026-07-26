/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{vue,js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
          950: '#172554',
        },
        surface: {
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          300: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b',
          900: '#0f172a',
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
            from: '#2563eb',
            via: '#1d4ed8',
            to: '#1e3a8a',
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
