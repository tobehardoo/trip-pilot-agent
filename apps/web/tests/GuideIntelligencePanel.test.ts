import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/vue'
import { afterEach, describe, expect, it, test, vi } from 'vitest'

import { ApiError } from '../src/lib/api'
import GuideIntelligencePanel from '../src/components/GuideIntelligencePanel.vue'

afterEach(cleanup)

const guideImports = [{
  id: '11111111-1111-1111-1111-111111111111',
  sourceType: 'PUBLIC_GUIDE_URL' as const,
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
      destination: '广州',
      startDate: '2026-08-01',
      endDate: '2026-08-02',
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

  expect(importGuide).toHaveBeenCalledWith({
    sourceType: 'PUBLIC_GUIDE_URL',
    sourceUrl: 'https://example.com/new-guide',
  })
})

test('submits pasted Xiaohongshu share text as user-provided evidence', async () => {
  const importGuide = vi.fn(async () => {})
  render(GuideIntelligencePanel, {
    props: {
      guideImports: [],
      destination: '广州',
      startDate: '2026-08-01',
      endDate: '2026-08-02',
      busy: false,
      error: null,
      importGuide,
    },
  })

  await fireEvent.click(screen.getByRole('button', { name: '粘贴正文 / TXT' }))
  await fireEvent.update(screen.getByLabelText('正文标题'), '广州塔分享正文')
  await fireEvent.update(screen.getByLabelText('正文来源'), 'XIAOHONGSHU_SHARED_TEXT')
  await fireEvent.update(
    screen.getByLabelText('攻略正文'),
    '广州塔地址是阅江西路222号，门票约150元，建议提前购票。',
  )
  await fireEvent.click(screen.getByRole('button', { name: '识别正文' }))

  expect(importGuide).toHaveBeenCalledWith({
    sourceType: 'XIAOHONGSHU_SHARED_TEXT',
    title: '广州塔分享正文',
    content: '广州塔地址是阅江西路222号，门票约150元，建议提前购票。',
  })
})

test('syncs destination weather and attraction intelligence for the planning dates', async () => {
  const importGuide = vi.fn(async () => {})
  render(GuideIntelligencePanel, {
    props: {
      guideImports: [],
      destination: '广州',
      startDate: '2026-08-01',
      endDate: '2026-08-02',
      busy: false,
      error: null,
      importGuide,
    },
  })

  await fireEvent.click(screen.getByRole('button', { name: '同步城市情报' }))

  expect(importGuide).toHaveBeenCalledWith({
    sourceType: 'CITY_INTELLIGENCE',
    city: '广州',
    startDate: '2026-08-01',
    endDate: '2026-08-02',
  })
})

test('loads a TXT file into the text import form', async () => {
  const importGuide = vi.fn(async () => {})
  render(GuideIntelligencePanel, {
    props: {
      guideImports: [],
      destination: '广州',
      startDate: '2026-08-01',
      endDate: '2026-08-02',
      busy: false,
      error: null,
      importGuide,
    },
  })

  await fireEvent.click(screen.getByRole('button', { name: '粘贴正文 / TXT' }))
  const file = new File(
    ['陈家祠地址是中山七路，门票10元。'],
    '广州攻略.txt',
    { type: 'text/plain' },
  )
  Object.defineProperty(file, 'text', {
    value: async () => '陈家祠地址是中山七路，门票10元。',
  })
  await fireEvent.change(screen.getByLabelText('导入 TXT 或 Markdown'), {
    target: { files: [file] },
  })
  await fireEvent.click(screen.getByRole('button', { name: '识别正文' }))

  expect(importGuide).toHaveBeenCalledWith({
    sourceType: 'TEXT_FILE',
    title: '广州攻略.txt',
    content: '陈家祠地址是中山七路，门票10元。',
  })
})

test('shows an explicit empty and error state', () => {
  render(GuideIntelligencePanel, {
    props: {
      guideImports: [],
      destination: '广州',
      startDate: '2026-08-01',
      endDate: '2026-08-02',
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
      destination: '广州',
      startDate: '2026-08-01',
      endDate: '2026-08-02',
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

test('keeps city intelligence concise until the user opens its detail drawer', async () => {
  const setGuideEnabled = vi.fn(async () => {})
  render(GuideIntelligencePanel, {
    props: {
      guideImports: [{
        ...guideImports[0],
        sourceType: 'CITY_INTELLIGENCE',
        title: '杭州市城市实时情报',
        facts: [{
          ...guideImports[0].facts[0],
          category: 'WEATHER',
          statement: '杭州市当前天气：多云，29℃；坐标120.109486,30.095025。',
        }],
      }],
      destination: '杭州',
      startDate: '2026-08-01',
      endDate: '2026-08-02',
      busy: false,
      error: null,
      importGuide: vi.fn(),
      setGuideEnabled,
    },
  })

  expect(screen.getByRole('button', { name: '查看实时情报' })).toBeTruthy()
  expect(screen.queryByText(/120\.109486/)).toBeNull()

  await fireEvent.click(screen.getByRole('button', { name: '查看实时情报' }))

  const drawer = screen.getByRole('dialog', { name: '杭州实时情报' })
  expect(drawer).toBeTruthy()
  expect(within(drawer).getByText(/暂无可整理的地点资料/)).toBeTruthy()
  expect(within(drawer).queryByText(/杭州市当前天气/)).toBeNull()
  expect(screen.queryByText(/120\.109486/)).toBeNull()

  await fireEvent.click(within(drawer).getByRole('button', { name: '停用城市情报' }))
  expect(setGuideEnabled).toHaveBeenCalledWith(
    '11111111-1111-1111-1111-111111111111',
    false,
  )
})

test('uses only the newest enabled city intelligence import', async () => {
  render(GuideIntelligencePanel, {
    props: {
      guideImports: [
        {
          ...guideImports[0],
          id: 'new-disabled-city',
          sourceType: 'CITY_INTELLIGENCE',
          fetchedAt: '2026-08-02T08:00:00Z',
          enabled: false,
          facts: [{ ...guideImports[0].facts[0], statement: '新但已停用地点：地址天河路。' }],
        },
        {
          ...guideImports[0],
          id: 'old-enabled-city',
          sourceType: 'CITY_INTELLIGENCE',
          fetchedAt: '2026-08-01T08:00:00Z',
          enabled: true,
          facts: [{ ...guideImports[0].facts[0], statement: '旧地点：地址北京路。' }],
        },
      ],
      destination: '广州',
      startDate: '2026-08-01',
      endDate: '2026-08-02',
      busy: false,
      error: null,
      importGuide: vi.fn(),
      setGuideEnabled: vi.fn(),
    },
  })

  await fireEvent.click(screen.getByRole('button', { name: '查看实时情报' }))
  const drawer = screen.getByRole('dialog', { name: '广州实时情报' })
  expect(within(drawer).queryByText(/旧地点/)).toBeNull()
  expect(within(drawer).queryByText(/新但已停用地点/)).toBeNull()
  expect(within(drawer).getByRole('button', { name: '启用城市情报' })).toBeTruthy()
})

test('groups city intelligence into one place card with decision fields and excludes weather', async () => {
  render(GuideIntelligencePanel, {
    props: {
      guideImports: [{
        ...guideImports[0],
        sourceType: 'CITY_INTELLIGENCE',
        title: '杭州城市实时情报',
        facts: [
          {
            ...guideImports[0].facts[0],
            category: 'WEATHER',
            statement: '杭州市当前天气：晴，34℃，湿度45%。',
          },
          {
            ...guideImports[0].facts[0],
            id: 'place-address',
            category: 'LOCATION',
            statement: '西湖文化广场：地址西湖区西湖街道西湖街道西湖街道杨公堤10号；营业信息09:00-17:30；门票10元；需提前预约。',
          },
          {
            ...guideImports[0].facts[0],
            id: 'place-tip',
            category: 'TIP',
            statement: '西湖文化广场：雨天路滑，入口停车位较少。',
          },
        ],
      }],
      destination: '杭州',
      startDate: '2026-08-01',
      endDate: '2026-08-02',
      busy: false,
      error: null,
      importGuide: vi.fn(),
    },
  })

  await fireEvent.click(screen.getByRole('button', { name: '查看实时情报' }))

  const drawer = screen.getByRole('dialog', { name: '杭州实时情报' })
  const card = within(drawer).getByRole('article', { name: '西湖文化广场' })
  expect(card).toBeTruthy()
  expect(within(card).getByText('地点位置')).toBeTruthy()
  expect(within(card).getByText('西湖区西湖街道杨公堤10号')).toBeTruthy()
  expect(within(card).queryByText(/西湖街道西湖街道/)).toBeNull()
  expect(within(card).getByText('营业时间')).toBeTruthy()
  expect(within(card).getByText('09:00-17:30')).toBeTruthy()
  expect(within(card).getByText('门票')).toBeTruthy()
  expect(within(card).getByText('10 元')).toBeTruthy()
  expect(within(card).getByText('预约')).toBeTruthy()
  expect(within(card).getByText('需要提前预约')).toBeTruthy()
  expect(within(card).getByText('出行提示')).toBeTruthy()
  expect(within(card).getByText(/雨天路滑/)).toBeTruthy()
  expect(within(drawer).queryByText(/杭州市当前天气/)).toBeNull()
})

test('adds every itinerary place to the city intelligence drawer', async () => {
  render(GuideIntelligencePanel, {
    props: {
      guideImports: [{ ...guideImports[0], sourceType: 'CITY_INTELLIGENCE', facts: [] }],
      destination: '广州',
      startDate: '2026-08-01',
      endDate: '2026-08-01',
      itinerary: {
        days: [{
          date: '2026-08-01',
          activities: [{
            id: 'itinerary-place', title: '三元宫', startTime: '2026-08-01T01:00:00Z', endTime: '2026-08-01T02:00:00Z',
            estimatedCost: 0, source: 'DEMO', providerPoiId: null, coordinates: null, address: '越秀区应元路11号',
          }],
          transitLegs: [],
        }],
      },
      busy: false,
      error: null,
      importGuide: vi.fn(),
    },
  })

  await fireEvent.click(screen.getByRole('button', { name: '查看实时情报' }))
  const drawer = screen.getByRole('dialog', { name: '广州实时情报' })
  const card = within(drawer).getByRole('article', { name: '三元宫' })
  expect(within(card).getByText('行程中')).toBeTruthy()
  expect(within(card).getByText('越秀区应元路11号')).toBeTruthy()
})

test('shows a localized in-place error and recovers the sync button on failure (B14_FIX R1)', async () => {
  const importGuide = vi.fn(async () => {
    throw new Error('Guide intelligence service returned an invalid response')
  })
  render(GuideIntelligencePanel, {
    props: {
      guideImports: [],
      destination: '广州',
      startDate: '2026-08-01',
      endDate: '2026-08-02',
      busy: false,
      error: null,
      importGuide,
    },
  })

  await fireEvent.click(screen.getByRole('button', { name: '同步城市情报' }))

  // In-place localized error, not the raw English backend message.
  expect((await screen.findByRole('alert')).textContent).toContain('天气或攻略同步失败，请稍后重试')
  // The sync button must be usable again (no stuck submitting state).
  const syncButton = screen.getByRole('button', { name: '同步城市情报' })
  expect(syncButton.hasAttribute('disabled')).toBe(false)
})

function pngFile(name = 'guide.png', size = 1024): File {
  const content = new Uint8Array(size)
  return new File([content], name, { type: 'image/png' })
}

async function openImageMode(view: ReturnType<typeof render>) {
  await fireEvent.click(view.getByRole('button', { name: '图片截图' }))
}

async function addFileViaInput(
  view: ReturnType<typeof render>,
  file: File,
  { expectPreview = true }: { expectPreview?: boolean } = {},
) {
  const input = view.container.querySelector('input[type="file"]') as HTMLInputElement
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  await fireEvent.change(input)
  if (!expectPreview) return
  await waitFor(() => {
    view.getByAltText(`预览：${file.name}`)
  })
}

const baseProps = {
  guideImports: [],
  destination: '广州',
  startDate: '2026-09-01',
  endDate: '2026-09-03',
  itinerary: null,
  busy: false,
  error: null,
  importGuide: vi.fn().mockResolvedValue(undefined),
}

describe('GuideIntelligencePanel image import', () => {
  it('offers url, text, and image import modes', async () => {
    const view = render(GuideIntelligencePanel, { props: baseProps })

    for (const mode of ['公开链接', '粘贴正文 / TXT', '图片截图']) {
      view.getByRole('button', { name: mode })
    }
    await openImageMode(view)
    view.getByLabelText(/添加攻略截图/)
  })

  it('adds a preview with an accessible delete button after selecting a PNG', async () => {
    const view = render(GuideIntelligencePanel, { props: baseProps })
    await openImageMode(view)
    await addFileViaInput(view, pngFile('陈家祠.png'))

    view.getByAltText('预览：陈家祠.png')
    view.getByRole('button', { name: '删除图片 陈家祠.png' })
  })

  it('supports drag-and-drop and clipboard paste of screenshots', async () => {
    const view = render(GuideIntelligencePanel, { props: baseProps })
    await openImageMode(view)
    const dropzone = view.getByLabelText(/添加攻略截图/)

    await fireEvent.drop(dropzone, { dataTransfer: { files: [pngFile('dropped.png')] } })
    await waitFor(() => view.getByAltText('预览：dropped.png'))

    await fireEvent.paste(dropzone, {
      clipboardData: { files: [pngFile('pasted.png')] },
    })
    await waitFor(() => view.getByAltText('预览：pasted.png'))
  })

  it('rejects unsupported formats and oversized files without adding previews', async () => {
    const view = render(GuideIntelligencePanel, { props: baseProps })
    await openImageMode(view)

    await addFileViaInput(
      view,
      new File([new Uint8Array(10)], 'page.gif', { type: 'image/gif' }),
      { expectPreview: false },
    )
    expect(() => view.getByAltText('预览：page.gif')).toThrow()
    view.getByText(/不是支持的格式/)

    const huge = new File([new Uint8Array(5_000_001)], 'huge.png', { type: 'image/png' })
    const input = view.container.querySelector('input[type="file"]') as HTMLInputElement
    Object.defineProperty(input, 'files', { value: [huge], configurable: true })
    await fireEvent.change(input)
    await waitFor(() => view.getByText(/超过 5 MB 上限/))
    expect(() => view.getByAltText('预览：huge.png')).toThrow()
  })

  it('caps the batch at five images', async () => {
    const view = render(GuideIntelligencePanel, { props: baseProps })
    await openImageMode(view)
    for (let index = 0; index < 5; index += 1) {
      await addFileViaInput(view, pngFile(`shot-${index}.png`))
    }

    await addFileViaInput(view, pngFile('shot-6.png'), { expectPreview: false })

    view.getByText('一次最多导入 5 张图片。')
    expect(() => view.getByAltText('预览：shot-6.png')).toThrow()
  })

  it('removes a preview when its delete button is pressed', async () => {
    const view = render(GuideIntelligencePanel, { props: baseProps })
    await openImageMode(view)
    await addFileViaInput(view, pngFile('guide.png'))

    await fireEvent.click(view.getByRole('button', { name: '删除图片 guide.png' }))

    expect(() => view.getByAltText('预览：guide.png')).toThrow()
  })

  it('submits base64 payloads as IMAGE_OCR and clears the batch on success', async () => {
    const importGuide = vi.fn().mockResolvedValue(undefined)
    const view = render(GuideIntelligencePanel, {
      props: { ...baseProps, importGuide },
    })
    await openImageMode(view)

    const file = new File([new Uint8Array([0x68, 0x69])], 'hi.png', { type: 'image/png' })
    const input = view.container.querySelector('input[type="file"]') as HTMLInputElement
    Object.defineProperty(input, 'files', { value: [file], configurable: true })
    await fireEvent.change(input)
    await waitFor(() => view.getByAltText('预览：hi.png'))
    await fireEvent.click(view.getByRole('button', { name: '识别图片文字' }))
    await waitFor(() => expect(importGuide).toHaveBeenCalledOnce())

    expect(importGuide).toHaveBeenCalledWith({
      sourceType: 'IMAGE_OCR',
      images: [
        {
          dataBase64: 'aGk=',
          fileName: 'hi.png',
          contentType: 'image/png',
        },
      ],
    })
    await waitFor(() => {
      expect(() => view.getByAltText('预览：hi.png')).toThrow()
    })
  })

  it('surfaces an actionable message when OCR is not configured', async () => {
    const importGuide = vi.fn().mockRejectedValue(
      new ApiError(422, 'GUIDE_OCR_NOT_CONFIGURED', 'OCR_NOT_CONFIGURED'),
    )
    const view = render(GuideIntelligencePanel, {
      props: { ...baseProps, importGuide },
    })
    await openImageMode(view)
    await addFileViaInput(view, pngFile('guide.png'))

    await fireEvent.click(view.getByRole('button', { name: '识别图片文字' }))

    await waitFor(() =>
      view.getByText(/图片识别未配置：服务端尚未启用视觉识别模型/),
    )
  })

  it('surfaces unusable OCR text with a retry hint', async () => {
    const importGuide = vi.fn().mockRejectedValue(
      new ApiError(422, 'GUIDE_OCR_FAILED', 'OCR_NO_TEXT'),
    )
    const view = render(GuideIntelligencePanel, {
      props: { ...baseProps, importGuide },
    })
    await openImageMode(view)
    await addFileViaInput(view, pngFile('blur.png'))

    await fireEvent.click(view.getByRole('button', { name: '识别图片文字' }))

    await waitFor(() =>
      view.getByText(/未能从图片中识别出可用文字/),
    )
  })
})

describe('GuideIntelligencePanel url mode guidance', () => {
  it('explains static-page limits with concrete fallbacks', () => {
    const view = render(GuideIntelligencePanel, { props: baseProps })

    view.getByText(/动态渲染、登录墙或反爬限制的页面/)
    view.getByText(/复制正文粘贴，或在“图片截图”页上传页面截图/)
  })
})
