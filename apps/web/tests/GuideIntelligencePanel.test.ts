import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { afterEach, expect, test, vi } from 'vitest'

import GuideIntelligencePanel from '../src/components/GuideIntelligencePanel.vue'

afterEach(cleanup)

const guideImports = [{
  id: '11111111-1111-1111-1111-111111111111',
  sourceUrl: 'https://example.com/guide',
  finalUrl: 'https://example.com/guide',
  sourceHost: 'example.com',
  title: '广州周末攻略',
  excerpt: '从公园前乘地铁 1 号线到陈家祠站。',
  contentHash: 'a'.repeat(64),
  fetchedAt: '2026-07-23T08:00:00Z',
  enabled: true,
  facts: [{
    id: '22222222-2222-2222-2222-222222222222',
    category: 'TRANSPORT',
    statement: '从公园前乘地铁 1 号线到陈家祠站。',
    evidence: '从公园前乘地铁 1 号线到陈家祠站。',
    confidence: 0.84,
    observedAt: '2026-07-23T08:00:00Z',
    expiresAt: '2099-07-30T08:00:00Z',
  }],
}]

test('submits a public guide URL and renders source and freshness evidence', async () => {
  const importGuide = vi.fn(async () => {})
  render(GuideIntelligencePanel, {
    props: {
      guideImports,
      busy: false,
      error: null,
      importGuide,
    },
  })

  expect(screen.getByText('广州周末攻略')).toBeTruthy()
  expect(screen.getByText('交通')).toBeTruthy()
  expect(screen.getByText('有效')).toBeTruthy()
  expect(screen.getByRole('link', { name: /查看原文/ }).getAttribute('href'))
    .toBe('https://example.com/guide')

  await fireEvent.update(
    screen.getByLabelText('公开攻略链接'),
    'https://example.com/new-guide',
  )
  await fireEvent.click(screen.getByRole('button', { name: '导入攻略' }))

  expect(importGuide).toHaveBeenCalledWith('https://example.com/new-guide')
})

test('shows an explicit empty and error state', () => {
  render(GuideIntelligencePanel, {
    props: {
      guideImports: [],
      busy: false,
      error: '攻略站点拒绝了公开访问',
      importGuide: vi.fn(),
    },
  })

  expect(screen.getByRole('alert').textContent).toContain('攻略站点拒绝了公开访问')
  expect(screen.getByText('还没有导入攻略')).toBeTruthy()
})

test('lets the user disable a source before the next planning task', async () => {
  const setGuideEnabled = vi.fn(async () => {})
  render(GuideIntelligencePanel, {
    props: {
      guideImports,
      busy: false,
      error: null,
      importGuide: vi.fn(),
      setGuideEnabled,
    },
  })

  await fireEvent.click(screen.getByRole('button', { name: '停用来源' }))

  expect(setGuideEnabled).toHaveBeenCalledWith(
    '11111111-1111-1111-1111-111111111111',
    false,
  )
})
