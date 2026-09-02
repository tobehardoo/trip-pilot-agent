import { describe, expect, test, vi, afterEach } from 'vitest'
import { nextTick } from 'vue'
import { cleanup, fireEvent, render, screen } from '@testing-library/vue'

import WorkspaceComposer from '../src/workspace/composer/WorkspaceComposer.vue'
import CitySearchInput from '../src/workspace/lib/CitySearchInput.vue'

// CitySearchInput 换成确定性桩：点击即选中「广州」（模拟行政区划索引点选，
// 先发城市名、后发 region 编码，与真实组件的 emit 顺序一致）。
const CitySearchStub = {
  name: 'CitySearchInput',
  props: { modelValue: { type: String, default: '' }, region: { type: Object, default: null } },
  emits: ['update:modelValue', 'update:region'],
  template: `<button
    data-testid="stub-city-pick"
    @click="$emit('update:modelValue', '广州'); $emit('update:region', { provinceCode: '440000', cityCode: '440100' })"
  >选择广州</button>`,
}

async function openCityInline() {
  await fireEvent.click(screen.getByTestId('composer-destination-chip'))
  await screen.findByTestId('stub-city-pick')
  await fireEvent.click(screen.getByTestId('stub-city-pick'))
  await nextTick()
}

describe('WorkspaceComposer（三层 Composer）', () => {
  afterEach(cleanup)

  test('floating：Required Context 未填时发送禁用，点选城市后 emit 目的地 + region', async () => {
    const { emitted } = render(WorkspaceComposer, {
      props: { variant: 'floating' },
      global: { stubs: { CitySearchInput: CitySearchStub } },
    })

    expect((screen.getByTestId('composer-send') as HTMLButtonElement).disabled).toBe(true)

    await openCityInline()
    expect(emitted()['updateDestination']?.[0]).toEqual(['广州', { provinceCode: '440000', cityCode: '440100' }])
  })

  test('日期弹层：结束早于开始给内联提示；合法区间 emit 且收起弹层', async () => {
    const { emitted } = render(WorkspaceComposer, { props: { variant: 'floating' } })

    await fireEvent.click(screen.getByTestId('composer-date-chip'))
    await screen.findByTestId('composer-date-popover')
    await fireEvent.update(screen.getByTestId('composer-date-start'), '2026-09-13')
    await fireEvent.update(screen.getByTestId('composer-date-end'), '2026-09-10')
    expect(screen.getByTestId('composer-date-error').textContent).toContain('结束日期不能早于开始日期')

    await fireEvent.update(screen.getByTestId('composer-date-start'), '2026-09-10')
    expect(emitted()['updateDates']?.[0]).toEqual(['2026-09-10', '2026-09-10'])
    expect(screen.queryByTestId('composer-date-popover')).toBeNull()
  })

  test('chips 齐备后可发送；对话锁定后 chips 隐藏且弹层不再打开', async () => {
    render(WorkspaceComposer, {
      props: { variant: 'floating', destination: '广州', startDate: '2026-09-10', endDate: '2026-09-13', chipsLocked: true },
      global: { stubs: { CitySearchInput: CitySearchStub } },
    })

    // chipsLocked 时目的地和日期区域隐藏
    expect(screen.queryByTestId('composer-destination-chip')).toBeNull()

    await fireEvent.update(screen.getByTestId('composer-input'), '想去广州玩几天')
    expect((screen.getByTestId('composer-send') as HTMLButtonElement).disabled).toBe(false)
    await fireEvent.click(screen.getByTestId('composer-send'))
    expect(screen.getByTestId('composer-input').textContent).toBe('')
  })

  test('Enter 发送 / Shift+Enter 换行；ready 时显示开始规划', async () => {
    const { emitted } = render(WorkspaceComposer, {
      props: { variant: 'floating', destination: '广州', startDate: '2026-09-10', endDate: '2026-09-13', ready: true },
    })

    const input = screen.getByTestId('composer-input')
    await fireEvent.update(input, '想轻松一点')
    await fireEvent.keyDown(input, { key: 'Enter' })
    expect(emitted().send?.[0]).toEqual(['想轻松一点'])

    expect(screen.getByTestId('composer-start-planning').textContent).toContain('开始规划')
    await fireEvent.click(screen.getByTestId('composer-start-planning'))
    expect(emitted().startPlanning).toHaveLength(1)
  })

  test('docked：只读上下文行 + 发送透传文本；无 Required Context 门禁', async () => {
    const { emitted } = render(WorkspaceComposer, {
      props: { variant: 'docked', contextLabel: '广州 · 09/10 → 09/13' },
    })

    expect(screen.getByTestId('composer-context-label').textContent).toContain('广州 · 09/10 → 09/13')
    expect(screen.queryByTestId('composer-destination-chip')).toBeNull()

    await fireEvent.update(screen.getByTestId('composer-input'), '把第二天安排轻松一点')
    await fireEvent.click(screen.getByTestId('composer-send'))
    expect(emitted().send?.[0]).toEqual(['把第二天安排轻松一点'])
  })
})