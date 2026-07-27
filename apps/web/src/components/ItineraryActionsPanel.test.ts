import { cleanup, fireEvent, render } from '@testing-library/vue'
import { afterEach, expect, test, vi } from 'vitest'

import ItineraryActionsPanel from './ItineraryActionsPanel.vue'

afterEach(() => cleanup())

test('creates a version-bound share and provides both export formats', async () => {
  const createShare = vi.fn().mockResolvedValue({
    id: 'share-1',
    versionId: 'version-1',
    shareToken: 'secure-share-token',
    expiresAt: null,
    createdAt: '2026-07-27T07:00:00Z',
  })
  const revokeShare = vi.fn().mockResolvedValue(undefined)
  const download = vi.fn().mockResolvedValue(undefined)
  const view = render(ItineraryActionsPanel, {
    props: {
      versionId: 'version-1',
      shares: [],
      createShare,
      revokeShare,
      download,
    },
  })

  await fireEvent.click(view.getByTestId('create-itinerary-share'))

  expect(createShare).toHaveBeenCalledWith('version-1', undefined)
  expect(view.getByTestId('share-url').textContent).toContain('/share/secure-share-token')

  await fireEvent.click(view.getByTestId('export-ics'))
  await fireEvent.click(view.getByTestId('export-pdf'))
  expect(download).toHaveBeenCalledWith('version-1', 'ics')
  expect(download).toHaveBeenCalledWith('version-1', 'pdf')

  await fireEvent.click(view.getByTestId('revoke-share-share-1'))
  expect(revokeShare).toHaveBeenCalledWith('share-1')
})
