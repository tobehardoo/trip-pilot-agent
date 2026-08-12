import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { afterEach, expect, test, vi } from 'vitest'

import ItineraryVersionPanel from '../src/components/ItineraryVersionPanel.vue'
import type { ItineraryVersionDiff, ItineraryVersionSummary } from '../src/lib/api'

afterEach(cleanup)

const versions: ItineraryVersionSummary[] = [
  {
    versionId: 'version-2',
    versionNumber: 2,
    parentVersionId: 'version-1',
    planningTaskId: null,
    versionSource: 'USER_EDIT',
    title: '广州两日游',
    estimatedTotalCost: 600,
    provider: 'AMAP',
    rollbackFromVersionId: null,
    createdAt: '2026-07-26T08:00:00Z',
    current: true,
  },
  {
    versionId: 'version-1',
    versionNumber: 1,
    parentVersionId: null,
    planningTaskId: 'task-1',
    versionSource: 'PLANNING_TASK',
    title: '广州两日游',
    estimatedTotalCost: 800,
    provider: 'AMAP',
    rollbackFromVersionId: null,
    createdAt: '2026-07-25T08:00:00Z',
    current: false,
  },
]

const diff: ItineraryVersionDiff = {
  fromVersionId: 'version-1',
  toVersionId: 'version-2',
  addedActivities: [],
  removedActivities: [{ key: 'museum', title: '广东省博物馆', date: '2026-08-01' }],
  changedActivities: [],
  addedTransitLegs: [],
  removedTransitLegs: [],
  changedTransitLegs: [],
  addedFactImpacts: [],
  removedFactImpacts: [],
  changedFactImpacts: [],
  fromTotalCost: 800,
  toTotalCost: 600,
  budgetChange: -200,
}

const fiveVersions: ItineraryVersionSummary[] = Array.from({ length: 5 }, (_, index) => ({
  ...versions[0]!,
  versionId: `version-${5 - index}`,
  versionNumber: 5 - index,
  current: index === 0,
}))

test('compares an old version with current and confirms an idempotent rollback', async () => {
  const getDiff = vi.fn(async () => diff)
  const rollback = vi.fn(async () => {})
  render(ItineraryVersionPanel, {
    props: {
      versions,
      currentVersionId: 'version-2',
      busy: false,
      error: null,
      getDiff,
      rollback,
    },
  })

  await fireEvent.click(screen.getByRole('button', { name: '比较版本 1 与当前版本' }))

  await waitFor(() => expect(getDiff).toHaveBeenCalledWith('version-1', 'version-2'))
  expect(screen.getByText('移除：广东省博物馆')).toBeTruthy()
  expect(screen.getByText('预算变化 -¥200')).toBeTruthy()

  await fireEvent.click(screen.getByRole('button', { name: '回滚到版本 1' }))
  await fireEvent.click(screen.getByRole('button', { name: '确认回滚到版本 1' }))

  expect(rollback).toHaveBeenCalledTimes(1)
  expect(rollback).toHaveBeenCalledWith(
    'version-1',
    'version-2',
    expect.stringMatching(/^[0-9a-f-]{36}$/),
  )
})

test('collapses older version records until explicitly expanded', async () => {
  const view = render(ItineraryVersionPanel, {
    props: {
      versions: fiveVersions, currentVersionId: 'version-5', busy: false, error: null,
      getDiff: async () => diff, rollback: async () => {},
    },
  })
  expect(view.container.querySelectorAll('ol > li')).toHaveLength(3)
  await fireEvent.click(screen.getByRole('button', { name: '查看其余 2 个较早版本' }))
  expect(view.container.querySelectorAll('ol > li')).toHaveLength(5)
})

const verifiedMetadata = {
  reportId: 'report-verified',
  schemaVersion: 1,
  validatorVersion: 'hard-validator-v4',
  status: 'VERIFIED',
  itineraryFingerprint: 'a'.repeat(64),
  validatedAt: '2026-07-25T08:00:00Z',
}

function versionWithFeasibility(feasibility: unknown): ItineraryVersionSummary {
  return {
    ...versions[1]!,
    versionId: 'version-3',
    versionNumber: 3,
    current: true,
    feasibility,
  }
}

test('shows VERIFIED feasibility metadata on the version record', () => {
  render(ItineraryVersionPanel, {
    props: {
      versions: [versionWithFeasibility(verifiedMetadata)],
      currentVersionId: 'version-3', busy: false, error: null,
      getDiff: async () => diff, rollback: async () => {},
    },
  })
  expect(screen.getByText('已验证')).toBeTruthy()
})

test('shows NEEDS_REPAIR and UNVERIFIED feasibility metadata', () => {
  render(ItineraryVersionPanel, {
    props: {
      versions: [
        versionWithFeasibility({ ...verifiedMetadata, status: 'NEEDS_REPAIR' }),
        { ...versionWithFeasibility({ ...verifiedMetadata, status: 'UNVERIFIED' }), versionId: 'version-4', current: false },
      ],
      currentVersionId: 'version-3', busy: false, error: null,
      getDiff: async () => diff, rollback: async () => {},
    },
  })
  expect(screen.getByText('待修复')).toBeTruthy()
  expect(screen.getByText('未验证')).toBeTruthy()
})

test('shows no historical validation copy when metadata is null, not UNVERIFIED', () => {
  render(ItineraryVersionPanel, {
    props: {
      versions: [versionWithFeasibility(null)],
      currentVersionId: 'version-3', busy: false, error: null,
      getDiff: async () => diff, rollback: async () => {},
    },
  })
  expect(screen.getByText('无历史验证')).toBeTruthy()
  expect(screen.queryByText('未验证')).toBeNull()
})

test('degrades malformed feasibility metadata without showing VERIFIED', () => {
  render(ItineraryVersionPanel, {
    props: {
      versions: [versionWithFeasibility('not-a-report')],
      currentVersionId: 'version-3', busy: false, error: null,
      getDiff: async () => diff, rollback: async () => {},
    },
  })
  expect(screen.queryByText('已验证')).toBeNull()
  expect(screen.getByText('验证信息无法读取')).toBeTruthy()
})
