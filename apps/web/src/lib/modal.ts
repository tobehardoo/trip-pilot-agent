// 模态框焦点管理（仅供 shared UI Drawer 组件使用）
import { onMounted, onUnmounted, type Ref, watch } from 'vue'

export function useModalFocus(
  open: Ref<boolean>,
  panel: Ref<HTMLElement | null>,
  onClose: () => void,
) {
  let previousFocus: HTMLElement | null = null

  watch(open, (isOpen) => {
    if (isOpen) {
      previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    } else if (previousFocus) {
      previousFocus.focus()
      previousFocus = null
    }
  })

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && open.value) {
      onClose()
      return
    }
    if (event.key !== 'Tab' || !panel.value) return
    const focusable = panel.value.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    )
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  onMounted(() => document.addEventListener('keydown', handleKeydown))
  onUnmounted(() => document.removeEventListener('keydown', handleKeydown))

  return { handleKeydown }
}