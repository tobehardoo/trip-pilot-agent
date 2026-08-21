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

  // 主页面只显示当前版本摘要；历史版本进 Drawer。
  expect(screen.getByText('当前版本')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '比较版本 1 与当前版本' })).toBeNull()

  await fireEvent.click(screen.getByTestId('open-version-history'))
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

test('main panel shows only the current version; history drawer lists all versions', async () => {
  const view = render(ItineraryVersionPanel, {
    props: {
      versions: fiveVersions, currentVersionId: 'version-5', busy: false, error: null,
      getDiff: async () => diff, rollback: async () => {},
    },
  })
  // 主页面没有版本列表；只有当前版本摘要 + 历史入口。
  // 历史 Drawer 使用 Teleport 渲染到 body，因此用 document 查询。
  expect(document.querySelectorAll('ol > li')).toHaveLength(0)
  expect(view.getByText('当前版本')).toBeTruthy()
  await fireEvent.click(screen.getByTestId('open-version-history'))
  expect(document.querySelectorAll('ol > li')).toHaveLength(5)
  // 主面板与 Drawer 内当前行各有「当前」标识。
  expect(view.getAllByText('当前').length).toBeGreaterThanOrEqual(2)
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

test('shows NEEDS_REPAIR and UNVERIFIED feasibility metadata', async () => {
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
  // 当前版本（NEEDS_REPAIR）的验证状态直接显示在主面板。
  expect(screen.getByText('待修复')).toBeTruthy()
  // 历史版本（UNVERIFIED）的验证状态在 Drawer 中仍完整保留。
  expect(screen.queryByText('未验证')).toBeNull()
  await fireEvent.click(screen.getByTestId('open-version-history'))
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
