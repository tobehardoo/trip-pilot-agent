import { describe, expect, it } from 'vitest'

import type { ItineraryEditInput } from '../lib/api'
import { useItineraryDraft } from './useItineraryDraft'

const transitEdit = (mode: ItineraryEditInput['transitMode']): ItineraryEditInput => ({
  baseVersionId: 'version-1',
  operation: 'UPDATE_TRANSIT_LEG',
  transitLegId: 'leg-1',
  transitMode: mode,
})

describe('useItineraryDraft', () => {
  it('merges repeated edits for the same transit leg', () => {
    const draft = useItineraryDraft(async () => {})

    draft.queue(transitEdit('WALKING'))
    draft.queue({ ...transitEdit('TRANSIT'), transitLocked: true })

    expect(draft.edits.value).toEqual([
      expect.objectContaining({ transitLegId: 'leg-1', transitMode: 'TRANSIT', transitLocked: true }),
    ])
  })

  it('preserves queued edits when a commit fails', async () => {
    const draft = useItineraryDraft(async () => {
      throw new Error('network unavailable')
    })
    draft.queue(transitEdit('TRANSIT'))

    await expect(draft.commit('version-1')).resolves.toBe(false)

    expect(draft.edits.value).toHaveLength(1)
    expect(draft.error.value).toBe('network unavailable')
  })

  it('clears a draft only after its batch commit succeeds', async () => {
    const commits: ItineraryEditInput[][] = []
    const draft = useItineraryDraft(async (_versionId, edits) => {
      commits.push(edits)
    })
    draft.queue(transitEdit('TRANSIT'))

    await expect(draft.commit('version-1')).resolves.toBe(true)

    expect(commits).toEqual([[expect.objectContaining({ transitMode: 'TRANSIT' })]])
    expect(draft.edits.value).toEqual([])
    expect(draft.error.value).toBeNull()
  })
})
