// 极小工具集（仅保留 shared UI 组件依赖）
import { clsx, type ClassValue } from 'clsx'

/**
 * clsx 风格合并：接受扁平项与条件对象（键=类名，值=是否启用）。
 * 直接委托 clsx：类型面与各组件 `import type { ClassValue } from 'clsx'` 完全一致。
 */
export function cn(...classes: ClassValue[]): string {
  return clsx(...classes)
}