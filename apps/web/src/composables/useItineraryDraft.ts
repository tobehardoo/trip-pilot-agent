import { ref } from 'vue'

import type { ItineraryEditInput } from '../lib/api'

type CommitItineraryEdits = (
  baseVersionId: string,
  edits: ItineraryEditInput[],
) => Promise<void>

export function useItineraryDraft(
  commitItineraryEdits: CommitItineraryEdits,
  formatError: (cause: unknown) => string = (cause) => (
    cause instanceof Error ? cause.message : '保存行程草稿失败，请稍后重试'
  ),
) {
  const edits = ref<ItineraryEditInput[]>([])
  const busy = ref(false)
  const error = ref<string | null>(null)

  function queue(input: ItineraryEditInput) {
    if (input.operation === 'UPDATE_TRANSIT_LEG' && input.transitLegId) {
      const index = edits.value.findIndex((edit) => (
        edit.operation === 'UPDATE_TRANSIT_LEG' && edit.transitLegId === input.transitLegId
      ))
      if (index >= 0) {
        edits.value[index] = { ...edits.value[index]!, ...input }
        return
      }
    }
    edits.value.push(input)
  }

  function discard() {
    edits.value = []
    error.value = null
  }

  async function commit(baseVersionId: string): Promise<boolean> {
    if (busy.value || edits.value.length === 0) return false
    busy.value = true
    error.value = null
    try {
      await commitItineraryEdits(baseVersionId, edits.value)
      edits.value = []
      return true
    } catch (cause) {
      error.value = formatError(cause)
      return false
    } finally {
      busy.value = false
    }
  }

  return { edits, busy, error, queue, discard, commit }
}
