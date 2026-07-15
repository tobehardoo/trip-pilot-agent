import { nextTick, watch, type Ref } from 'vue'

const FOCUSABLE_SELECTOR = [
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[href]',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export function useModalFocus(
  open: Ref<boolean>,
  dialog: Ref<HTMLElement | null>,
  close: () => void,
) {
  let returnFocus: HTMLElement | null = null

  function rememberTrigger(trigger: EventTarget | null | undefined) {
    if (trigger instanceof HTMLElement) returnFocus = trigger
  }

  watch(open, async (isOpen) => {
    if (isOpen) {
      if (!returnFocus && document.activeElement instanceof HTMLElement) {
        returnFocus = document.activeElement
      }
      await nextTick()
      const initialFocus = dialog.value?.querySelector<HTMLElement>('[data-modal-initial-focus]')
      const firstFocusable = focusableElements()[0]
      ;(initialFocus ?? firstFocusable ?? dialog.value)?.focus()
      return
    }

    if (returnFocus) {
      await nextTick()
      returnFocus.focus()
      returnFocus = null
    }
  }, { flush: 'post' })

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
      return
    }
    if (event.key !== 'Tab') return

    const elements = focusableElements()
    if (elements.length === 0) {
      event.preventDefault()
      dialog.value?.focus()
      return
    }

    const first = elements[0]
    const last = elements[elements.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  function focusableElements() {
    return Array.from(dialog.value?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR) ?? [])
      .filter((element) => !element.hasAttribute('hidden'))
  }

  return { handleKeydown, rememberTrigger }
}
