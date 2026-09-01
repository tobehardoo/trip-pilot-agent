// 极小工具集（仅保留 shared UI 组件依赖）
export function cn(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(' ')
}