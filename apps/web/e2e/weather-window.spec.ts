import { expect, test, type Page } from '@playwright/test'

// B13-I: the public weather window is mounted above planning/review content
// and survives every planning state — it is not bound to the formal
// itinerary.  Verified at 1440×900 so the weather bar and the candidate
// schedule are visible before any validation details.

const tripId = '22222222-2222-2222-2222-222222222222'
const taskId = '33333333-3333-4333-8333-333333333333'

const session = {
  user: { id: '11111111-1111-1111-1111-111111111111', email: 'traveler@example.com', displayName: '旅行者' },
  accessToken: 'weather-window-token',
  tokenType: 'Bearer',
  expiresIn: 900,
}

const trip = {
  id: tripId,
  title: '广州周末四日',
  destination: '广州',
  startDate: '2026-08-01',
  endDate: '2026-08-04',
  status: 'DRAFT',
  version: 2,
  constraints: {
    budgetAmount: 4000,
    travelers: 2,
    travelerType: 'FRIENDS',
    pace: 'BALANCED',
    preferences: ['岭南文化', '本地美食'],
    fixedSchedules: [],
    arrival: null,
    departure: null,
    accommodation: null,
    mustVisitPlaces: [],
    avoidPlaces: [],
    mealWindows: [],
    mobilityLevel: 'STANDARD',
    schemaVersion: 2,
  },
  createdAt: '2026-07-26T01:00:00Z',
  updatedAt: '2026-07-26T02:00:00Z',
}

const candidateItinerary = {
  title: '候选行程',
  days: [{
    date: '2026-08-02',
    dayType: null,
    activities: [{
      activityId: '66666666-6666-6666-6666-666666666666',
      title: '候选活动',
      startTime: '2026-08-02T02:00:00Z',
      endTime: '2026-08-02T04:00:00Z',
      estimatedCost: 0,
      source: 'DEMO',
      providerPoiId: null,
      coordinates: null,
      address: null,
      typeCode: null,
      typeName: null,
      kind: null,
      timeFixed: null,
    }],
    transitLegs: [],
  }],
  estimatedTotalCost: 100,
}

const needsRepairReport = {
  schemaVersion: 1,
  reportId: 'c9c467cc-65c4-8ff1-e175-4af42f2ed545',
  validatorVersion: 'hard-validator-v4',
  itineraryFingerprint: 'b'.repeat(64),
  status: 'NEEDS_REPAIR',
  validatedAt: '2026-08-02T00:00:00Z',
  requiredRuleIds: ['MEAL_WINDOW'],
  missingRequiredRuleIds: [],
  summary: { totalCount: 1, passCount: 0, failCount: 1, unknownCount: 0, notApplicableCount: 0, missingRequiredCount: 0 },
  ruleResults: [{
    ruleId: 'MEAL_WINDOW',
    ruleVersion: 'hard-rule-v1',
    outcome: 'FAIL',
    reasonCode: 'MEAL_PLACEMENT_MISSING',
    message: '午餐窗口缺少安排',
    affectedDates: ['2026-08-02'],
    affectedEntityRefs: [],
    evidenceRefs: [],
    repairable: true,
  }],
  repairAttempts: [],
}

async function mockWeatherApi(page: Page) {
  const syncBodies: unknown[] = []
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname

    if (path === '/api/auth/refresh') {
      await route.fulfill({ json: session })
      return
    }
    if (path === '/api/trips' && request.method() === 'GET') {
      await route.fulfill({ json: [trip] })
      return
    }
    if (path === `/api/trips/${tripId}`) {
      await route.fulfill({ json: trip })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary`) {
      await route.fulfill({ status: 404, json: { code: 'ITINERARY_NOT_FOUND', message: '尚未生成行程' } })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary/versions`) {
      await route.fulfill({ json: [] })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary/shares`) {
      await route.fulfill({ json: [] })
      return
    }
    if (path === `/api/trips/${tripId}/guide-imports` && request.method() === 'GET') {
      await route.fulfill({ json: [] })
      return
    }
    if (path === `/api/trips/${tripId}/planning-tasks/latest`) {
      await route.fulfill({
        json: {
          taskId,
          tripId,
          taskType: 'CREATE',
          status: 'WAITING_USER',
          baselineTripVersion: 0,
          eventStreamUrl: `/api/planning-tasks/${taskId}/events`,
          feasibilityReport: needsRepairReport,
          candidateItinerary,
          createdAt: '2026-08-02T00:00:00Z',
          updatedAt: '2026-08-02T00:01:00Z',
        },
      })
      return
    }
    if (path === `/api/trips/${tripId}/guide-imports` && request.method() === 'POST') {
      syncBodies.push(request.postDataJSON())
      await route.fulfill({ status: 201, json: { id: 'import-1', sourceType: 'CITY_INTELLIGENCE' } })
      return
    }
    await route.fulfill({
      status: 501,
      json: { code: 'UNMOCKED_WEATHER_WINDOW_REQUEST', message: `${request.method()} ${path}` },
    })
  })
  return syncBodies
}

test.use({ viewport: { width: 1440, height: 900 } })

test('1440×900: waiting_user without a formal itinerary shows weather and candidate above validation details', async ({ page }) => {
  await mockWeatherApi(page)
  await page.goto(`/trips/${tripId}`)

  await expect(page.getByRole('heading', { name: trip.title, level: 1 })).toBeVisible()

  const weather = page.getByRole('region', { name: '行程天气' })
  await expect(weather).toBeVisible()
  // No weather facts are synced → the public sync action is offered.
  await expect(weather.getByRole('button', { name: '同步天气' })).toBeVisible()

  const review = page.locator('#planning-review-section')
  await expect(review).toBeVisible()
  await expect(review.getByRole('heading', { name: '方案需要调整' })).toBeVisible()
  await expect(review.getByText('预览方案')).toBeVisible()
  await expect(review.getByText('候选活动')).toBeVisible()

  // B15: the preview plan and its Chinese issue summary lead the panel; no
  // technical details toggle exists on the user page.  In a 900px viewport
  // the status heading must be visible WITHOUT scrolling: the page is pinned
  // at scrollY=0 and the heading's box must already fit the first viewport.
  await page.evaluate(() => window.scrollTo(0, 0))
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0)
  const statusBox = await review.getByRole('heading', { name: '方案需要调整' }).boundingBox()
  expect(statusBox!.y).toBeGreaterThanOrEqual(0)
  expect(statusBox!.y + statusBox!.height).toBeLessThanOrEqual(900)
  await expect(review.getByText('需要调整（1）')).toBeVisible()
  await expect(review.getByText('该项安排需要调整').first()).toBeVisible()
  await expect(review.getByText('MEAL_PLACEMENT_MISSING', { exact: true })).toHaveCount(0)
  await expect(review.getByText('hard-validator-v4', { exact: true })).toHaveCount(0)
  await expect(review.getByTestId('validation-details-toggle')).toHaveCount(0)

  // Weather window sits above the review section in the layout.
  const weatherBox = await weather.boundingBox()
  const reviewBox = await review.boundingBox()
  expect(weatherBox!.y + weatherBox!.height).toBeLessThanOrEqual(reviewBox!.y + 1)

  // Without any schedule, clicking a weather date only selects it (no error).
  const dayButton = weather.getByRole('button', { name: '选择 2026-08-02 天气' })
  await dayButton.click()
  await expect(dayButton).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('尚未生成行程')).toBeVisible()
})

test('P1-7: with a formal itinerary present, weather clicks still target the WAITING_USER candidate day', async ({ page }) => {
  const formalItinerary = {
    versionId: 'aaaa1111-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    versionNumber: 1,
    parentVersionId: null,
    title: '正式行程',
    estimatedTotalCost: 88,
    provider: 'DEMO',
    days: [{
      date: '2026-08-02',
      activities: [{
        id: 'ffff6666-ffff-ffff-ffff-ffffffffffff',
        title: '旧正式版本活动',
        startTime: '2026-08-02T01:00:00Z',
        endTime: '2026-08-02T02:00:00Z',
        estimatedCost: 0,
        source: 'DEMO',
        providerPoiId: null,
        coordinates: null,
        address: null,
        locked: false,
      }],
      transitLegs: [],
    }],
    knowledge: {
      status: 'UNAVAILABLE',
      query: '广州',
      citations: [],
      freshness: { status: 'UNAVAILABLE' },
      message: 'no knowledge',
    },
  }

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/api/auth/refresh') {
      await route.fulfill({ json: session })
      return
    }
    if (path === '/api/trips' && request.method() === 'GET') {
      await route.fulfill({ json: [trip] })
      return
    }
    if (path === `/api/trips/${tripId}`) {
      await route.fulfill({ json: trip })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary`) {
      await route.fulfill({ json: formalItinerary })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary/versions`) {
      await route.fulfill({ json: [] })
      return
    }
    if (path === `/api/trips/${tripId}/itinerary/shares`) {
      await route.fulfill({ json: [] })
      return
    }
    if (path === `/api/trips/${tripId}/guide-imports` && request.method() === 'GET') {
      await route.fulfill({ json: [] })
      return
    }
    if (path === `/api/trips/${tripId}/planning-tasks/latest`) {
      await route.fulfill({
        json: {
          taskId,
          tripId,
          taskType: 'CREATE',
          status: 'WAITING_USER',
          baselineTripVersion: 0,
          eventStreamUrl: `/api/planning-tasks/${taskId}/events`,
          feasibilityReport: needsRepairReport,
          candidateItinerary,
          createdAt: '2026-08-02T00:00:00Z',
          updatedAt: '2026-08-02T00:01:00Z',
        },
      })
      return
    }
    await route.fulfill({
      status: 501,
      json: { code: 'UNMOCKED_P17', message: `${request.method()} ${path}` },
    })
  })

  await page.goto(`/trips/${tripId}`)
  const weather = page.getByRole('region', { name: '行程天气' })
  await expect(weather).toBeVisible()
  const review = page.locator('#planning-review-section')
  await expect(review).toBeVisible()

  // With a formal itinerary present the candidate must still fit the first
  // 1440×900 viewport without scrolling (same gate as the no-formal case).
  await page.evaluate(() => window.scrollTo(0, 0))
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0)
  const candidateBox = await review.getByRole('heading', { name: '方案需要调整' }).boundingBox()
  expect(candidateBox!.y).toBeGreaterThanOrEqual(0)
  expect(candidateBox!.y + candidateBox!.height).toBeLessThanOrEqual(900)

  // The weather date click must light up the CANDIDATE day, never the old
  // formal version's route.
  const dayButton = weather.getByRole('button', { name: '选择 2026-08-02 天气' })
  await dayButton.click()
  const candidateDay = page.locator('#candidate-day-2026-08-02')
  await expect(candidateDay).toHaveClass(/border-primary-400/)
  await expect(page.locator('#day-2026-08-02')).toBeVisible()
  // The formal itinerary heading still exists and is untouched.
  await expect(page.getByRole('heading', { name: '正式行程' })).toBeVisible()

  // B13_FIX.1 R5: the formal activity must NOT carry the selected styles and
  // the map must NOT receive the old formal selection.
  const formalActivity = page.locator('#activity-ffff6666-ffff-ffff-ffff-ffffffffffff')
  await expect(formalActivity).not.toHaveClass(/z-10/)
  await expect(formalActivity).not.toHaveClass(/ring-primary-400/)
  // Fallback map markers (no AMap key) must not show any selected pin.
  await expect(page.locator('.amap-marker-pin.is-selected')).toHaveCount(0)
  await expect(page.locator('.overview-marker.is-selected')).toHaveCount(0)

  // "查看全部行程" clears both the candidate and the formal selection state.
  const showAll = page.getByRole('button', { name: '查看全部行程' })
  await expect(showAll).toBeVisible()
  await showAll.click()
  await expect(candidateDay).not.toHaveClass(/border-primary-400/)
  await expect(dayButton).toHaveAttribute('aria-pressed', 'false')
})

test('sync weather reuses the city-intelligence sync chain', async ({ page }) => {
  const syncBodies = await mockWeatherApi(page)
  await page.goto(`/trips/${tripId}`)

  const weather = page.getByRole('region', { name: '行程天气' })
  await expect(weather).toBeVisible()
  await weather.getByRole('button', { name: '同步天气' }).click()

  await expect.poll(() => syncBodies.length).toBe(1)
  expect(syncBodies[0]).toEqual({
    sourceType: 'CITY_INTELLIGENCE',
    city: '广州',
    startDate: '2026-08-01',
    endDate: '2026-08-04',
  })
})
