/**
 * 自然语言约束解析器。
 *
 * 纯函数，接收用户输入文本和当前时间，返回操作序列。
 * 不修改任何外部状态，不调用外部 API。
 */
import { extractCity, isSupportedCity } from './supported-cities'
import { findCity, findProvince, PROVINCES } from './china-divisions'

function resolveCityLocation(cityName: string): { province: string; city: string; districts: string[] } {
  for (const p of PROVINCES) {
    const c = p.cities.find((c) => c.name === cityName)
    if (c) {
      const whole = c.districts.find((d) => d.name.startsWith('全市'))
      return { province: p.name, city: c.name, districts: whole ? [whole.name] : [] }
    }
  }
  // fallback: unknown city → still return structured
  return { province: '', city: cityName, districts: [] }
}

// ── 类型 ──────────────────────────────────────────────────────

export type ConstraintOperation =
  | { type: 'set'; field: string; value: unknown }
  | { type: 'append'; field: string; value: unknown }
  | { type: 'remove'; field: string; value?: unknown }
  | { type: 'clear'; field: string }

export interface ParseWarning {
  code: string
  message: string
  fragment: string
}

export interface ParseResult {
  operations: ConstraintOperation[]
  warnings: ParseWarning[]
  unrecognized: string[]
}

/** 偏好关键词 → 标准名映射 */
const PREFERENCE_ALIASES: Record<string, string> = {
  '历史文化': '历史文化',
  '历史': '历史文化',
  '文化': '历史文化',
  '古迹': '历史文化',
  '博物馆': '历史文化',
  '古镇': '历史文化',
  '美食': '美食',
  '吃': '美食',
  '小吃': '美食',
  '火锅': '美食',
  '粤菜': '美食',
  '川菜': '美食',
  '餐厅': '美食',
  '自然': '自然风光',
  '山水': '自然风光',
  '风景': '自然风光',
  '户外': '自然风光',
  '爬山': '自然风光',
  '海滩': '自然风光',
  '自然风光': '自然风光',
  '购物': '购物',
  '买': '购物',
  '逛街': '购物',
  '商场': '购物',
  '休闲': '休闲',
  '放松': '休闲',
  '度假': '休闲',
  '慢节奏': '休闲',
  '泡温泉': '休闲',
}

// 中国数字
const CN_DIGITS: Record<string, number> = {
  '零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
  '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
}

// 人数推断（复杂情况标记 ambiguous）
const TRAVELER_PATTERNS: Array<{ regex: RegExp; value: number | null; source: 'explicit' | 'inferred' | 'ambiguous' }> = [
  { regex: /(\d+|[一两二三四五六七八九十])\s*个?\s*人/, value: 0, source: 'explicit' },
  { regex: /(\d+|[一两二三四五六七八九十])\s*人/, value: 0, source: 'explicit' },
  { regex: /(?:一个?人|独自|自己去|自己)/, value: 1, source: 'inferred' },
  { regex: /和(?:女朋友|男朋友|对象)/, value: 2, source: 'inferred' },
  { regex: /(?:和|带)爸妈/, value: 3, source: 'inferred' },
  { regex: /一家三[口个]/, value: 3, source: 'inferred' },
  { regex: /一家四[口个]/, value: 4, source: 'inferred' },
  { regex: /(?:带孩子|带小孩)/, value: null, source: 'ambiguous' },
  { regex: /和朋友们/, value: null, source: 'ambiguous' },
]

function cnNumber(s: string): number | null {
  if (/^\d+$/.test(s)) return parseInt(s)
  // 单个中文数字
  const single: Record<string, number> = { '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10 }
  if (single[s]) return single[s]
  return null
}

// ── 预处理 ────────────────────────────────────────────────────

function normalizeChineseNumbers(text: string): string {
  // 千/万/百 → 数字（仅处理常见旅游预算场景）
  let result = text
  result = result.replace(/三千[五六七八九]/, (m) => `3${cnDigit(m[2])}00`)
  result = result.replace(/三千五/, '3500')
  result = result.replace(/三千/, '3000')
  result = result.replace(/两千[五六七八九]/, (m) => `2${cnDigit(m[2])}00`)
  result = result.replace(/两千五/, '2500')
  result = result.replace(/两千/, '2000')
  result = result.replace(/一千[五六七八九]/, (m) => `1${cnDigit(m[2])}00`)
  result = result.replace(/一千五/, '1500')
  result = result.replace(/一千/, '1000')
  result = result.replace(/[四五六七八九]千[五六七八九]/, (m) => `${cnDigit(m[0])}${cnDigit(m[2])}00`)
  result = result.replace(/[四五六七八九]千五/, (m) => `${cnDigit(m[0])}500`)
  result = result.replace(/[四五六七八九]千/, (m) => `${cnDigit(m[0])}000`)
  result = result.replace(/[五六七八九]百/, (m) => `${cnDigit(m[0])}00`)
  result = result.replace(/一万/, '10000')
  return result
}

function cnDigit(c: string): number {
  return CN_DIGITS[c] ?? 0
}

// ── 日期解析 ──────────────────────────────────────────────────

interface DateParse {
  startDate: string
  endDate: string
  explicit: boolean // true=用户明确指定了日期，false=从"两天"推断
}

function toDateString(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function dateWithYear(month: number, day: number, now: Date): Date {
  const offset = 8 * 60 * 60 * 1000
  const today = new Date(now.getTime() + offset)
  const result = new Date(Date.UTC(today.getUTCFullYear(), month - 1, day))
  // 如果今年该日期已过，推到明年
  if (result.getTime() - offset < today.getTime() - offset) {
    result.setUTCFullYear(result.getUTCFullYear() + 1)
  }
  return result
}

function dayOfWeek(name: string): number {
  const map: Record<string, number> = { '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '日': 0, '天': 0 }
  return map[name] ?? 0
}

function nextWeekday(targetDow: number, now: Date): Date {
  const offset = 8 * 60 * 60 * 1000
  const today = new Date(now.getTime() + offset)
  const currentDow = today.getUTCDay()
  let daysAhead = targetDow - currentDow
  if (daysAhead <= 0) daysAhead += 7
  const result = new Date(today)
  result.setUTCDate(today.getUTCDate() + daysAhead)
  return result
}

function extractDate(text: string, now: Date): DateParse | null {
  // 1. 明确日期范围 "8月10号到12号"
  const rangeExplicit = /(\d{1,2})\s*月\s*(\d{1,2})\s*[号日]\s*[-到至]\s*(?:(\d{1,2})\s*月\s*)?(\d{1,2})\s*[号日]/.exec(text)
  if (rangeExplicit) {
    const m1 = parseInt(rangeExplicit[1]), d1 = parseInt(rangeExplicit[2])
    const m2 = rangeExplicit[3] ? parseInt(rangeExplicit[3]) : m1
    const d2 = parseInt(rangeExplicit[4])
    const start = dateWithYear(m1, d1, now)
    const end = dateWithYear(m2, d2, now)
    if (end < start) return null
    return { startDate: toDateString(start), endDate: toDateString(end), explicit: true }
  }

  // 2. 单一明确日期 "8月10号"
  const singleExplicit = /(\d{1,2})\s*月\s*(\d{1,2})\s*[号日]/.exec(text)
  if (singleExplicit) {
    const m = parseInt(singleExplicit[1]), d = parseInt(singleExplicit[2])
    const start = dateWithYear(m, d, now)
    // 继续扫描天数或相对日期
    const daysMatch = /(\d+)\s*[天日]/.exec(text)
    let end = ''
    if (daysMatch) {
      const days = parseInt(daysMatch[1])
      const endDate = new Date(start)
      endDate.setUTCDate(start.getUTCDate() + days - 1)
      end = toDateString(endDate)
    }
    return { startDate: toDateString(start), endDate: end, explicit: true }
  }

  // 3. "下周末" — 下周的周六和周日
  if (/下[个]?周末/.test(text)) {
    const thisSat = nextWeekday(6, now) // 本周六
    const sat = new Date(thisSat); sat.setUTCDate(thisSat.getUTCDate() + 7) // 下周六
    const sun = new Date(sat); sun.setUTCDate(sat.getUTCDate() + 1)
    return { startDate: toDateString(sat), endDate: toDateString(sun), explicit: false }
  }

  // 4. "这周末"
  if (/这[个]?周末/.test(text)) {
    const nowDate = new Date(now.getTime() + 8 * 60 * 60 * 1000)
    const currentDow = nowDate.getUTCDay()
    const daysToSat = (6 - currentDow + 7) % 7
    const sat = new Date(nowDate); sat.setUTCDate(nowDate.getUTCDate() + (daysToSat === 0 ? 7 : daysToSat))
    const sun = new Date(sat); sun.setUTCDate(sat.getUTCDate() + 1)
    return { startDate: toDateString(sat), endDate: toDateString(sun), explicit: false }
  }

  // 5. "下周一"
  const nextWeekdayMatch = /下周([一二三四五六日天])/.exec(text)
  if (nextWeekdayMatch) {
    const d = nextWeekday(dayOfWeek(nextWeekdayMatch[1]), now)
    return { startDate: toDateString(d), endDate: '', explicit: false }
  }

  // 6. 有天数的日期组合
  const daysMatch = /(\d+)\s*[天日]/.exec(text)
  let start = new Date(now.getTime() + 8 * 60 * 60 * 1000 + 86400000) // 默认明天
  let foundStart = false

  // "明天"
  if (/明天/.test(text)) {
    start = new Date(now.getTime() + 8 * 60 * 60 * 1000 + 86400000)
    foundStart = true
  }
  // "后天"
  if (/后天/.test(text)) {
    start = new Date(now.getTime() + 8 * 60 * 60 * 1000 + 2 * 86400000)
    foundStart = true
  }

  if (daysMatch) {
    const days = parseInt(daysMatch[1])
    const end = new Date(start)
    end.setUTCDate(start.getUTCDate() + days - 1)
    return { startDate: toDateString(start), endDate: toDateString(end), explicit: foundStart }
  }

  if (foundStart) {
    // 明天/后天但没有天数 → 默认 2 天
    const end = new Date(start)
    end.setUTCDate(start.getUTCDate() + 1)
    return { startDate: toDateString(start), endDate: toDateString(end), explicit: false }
  }

  return null
}

// ── 人数解析 ──────────────────────────────────────────────────

function extractTravelers(text: string): { value: number | null; source: 'explicit' | 'inferred' | 'ambiguous' } | null {
  for (const pat of TRAVELER_PATTERNS) {
    const m = pat.regex.exec(text)
    if (m) {
      if (pat.value !== 0) return { value: pat.value, source: pat.source }
      // 捕获组提取数字（支持中文）
      const n = cnNumber(m[1])
      if (n !== null && n >= 1 && n <= 50) return { value: n, source: pat.source }
    }
  }
  return null
}

// ── 预算解析 ──────────────────────────────────────────────────

function extractBudget(text: string): { value: number | null; source: 'explicit' } | null {
  // "预算不限"、"预算无所谓"
  if (/预算不限|预算无所谓|预算随意|不限预算/.test(text)) {
    return { value: null, source: 'explicit' }
  }
  // "预算XXXX"、"XXXX元"、"XXXX块"
  const budgetMatch = /预算\s*(\d+)|(\d+)\s*[元块]/.exec(text)
  if (budgetMatch) {
    const n = parseInt(budgetMatch[1] || budgetMatch[2])
    if (n >= 0) return { value: n, source: 'explicit' }
  }
  return null
}

// ── 偏好解析 ──────────────────────────────────────────────────

function extractPreferences(text: string): string[] {
  const prefs = new Set<string>()
  for (const [keyword, standard] of Object.entries(PREFERENCE_ALIASES)) {
    if (text.includes(keyword)) {
      prefs.add(standard)
    }
  }
  return [...prefs]
}

// ── 必去地点 ──────────────────────────────────────────────────

function extractMustVisit(text: string): string[] {
  const results: string[] = []
  // "一定要去X"、"必须去X"、"必去X"、"X必须去"、"不能不去X"
  const patterns = [
    /(?:一定要去|必须去|必去|不能不去)\s*(.+?)(?:[，,。.!！\s]|$)/g,
    /(.+?)\s*必须去/g,
  ]
  for (const pat of patterns) {
    let m: RegExpExecArray | null
    while ((m = pat.exec(text)) !== null) {
      const places = m[1].split(/[和、,，]/).map((s) => s.trim()).filter(Boolean)
      results.push(...places)
    }
  }
  return [...new Set(results)]
}

// ── 修改意图 ──────────────────────────────────────────────────

function extractModifications(text: string): { ops: ConstraintOperation[]; warnings: ParseWarning[] } {
  const ops: ConstraintOperation[] = []
  const warnings: ParseWarning[] = []

  // "不是X，是Y"、"X改成Y"、"改去X"
  const changeDest = /(?:不是|不去)\s*(.+?)[，,]\s*(?:是|改成|去)\s*(.+)/.exec(text)
  if (changeDest) {
    const newDest = changeDest[2].trim()
    if (isSupportedCity(newDest)) {
      ops.push({ type: 'set', field: 'destination', value: newDest })
    } else {
      warnings.push({
        code: 'UNSUPPORTED_CITY',
        message: `"${newDest}"不在当前支持的城市列表中（广州、北京、上海）`,
        fragment: newDest,
      })
    }
    return { ops, warnings }
  }

  // "预算改成X"、"预算改为X"
  const changeBudget = /预算\s*(?:改成|改为|改成)\s*(\d+)/.exec(text)
  if (changeBudget) {
    ops.push({ type: 'set', field: 'budgetAmount', value: parseInt(changeBudget[1]) })
  }

  // "不去X了"、"X不去了"、"删掉X"、"取消X"
  const removePlace = /(?:不去|删掉|取消)\s*(.+?)(?:了)?[，,。.!！\s]*$/.exec(text)
  if (removePlace) {
    ops.push({ type: 'remove', field: 'mustVisitPlaces', value: removePlace[1].trim() })
  }

  // "再加X"、"加上X"、"也去X"、"还有X"
  const appendPlace = /(?:再[加添]|加[上入]|也去|还有)\s*(.+)/.exec(text)
  if (appendPlace) {
    const places = appendPlace[1].split(/[和、,，]/).map((s) => s.trim()).filter(Boolean)
    for (const p of places) {
      ops.push({ type: 'append', field: 'mustVisitPlaces', value: p })
    }
  }

  return { ops, warnings }
}

// ── 主解析函数 ────────────────────────────────────────────────

export function parseConstraint(text: string, now: Date = new Date()): ParseResult {
  const operations: ConstraintOperation[] = []
  const warnings: ParseWarning[] = []
  const unrecognized: string[] = []

  // 0. 空输入
  const trimmed = text.trim()
  if (!trimmed) {
    return { operations: [], warnings: [], unrecognized: ['输入为空'] }
  }

  // 1. 预处理
  const normalized = normalizeChineseNumbers(trimmed)

  // 2. 修改意图
  const modResult = extractModifications(normalized)
  operations.push(...modResult.ops)
  warnings.push(...modResult.warnings)

  // 3. 日期
  const dateResult = extractDate(normalized, now)
  if (dateResult) {
    if (dateResult.startDate) {
      operations.push({ type: 'set', field: 'startDate', value: dateResult.startDate })
    }
    if (dateResult.endDate) {
      operations.push({ type: 'set', field: 'endDate', value: dateResult.endDate })
    } else if (!dateResult.explicit) {
      // 只有相对日期没有结束日期 → 默认 2 天
      const endDate = new Date(dateResult.startDate + 'T00:00:00+08:00')
      endDate.setUTCDate(endDate.getUTCDate() + 1)
      operations.push({ type: 'set', field: 'endDate', value: toDateString(endDate) })
    }
  }

  // 4. 目的地
  const city = extractCity(normalized)
  if (city) {
    operations.push({ type: 'set', field: 'destination', value: resolveCityLocation(city) })
  } else {
    // 检查是否有疑似城市名但不在白名单
    const possibleCity = /(?:去|到)\s*([一-鿿]{2,3})(?:[市州]|[，,。.！!\s\d]|三日|两日|游|$)/
      .exec(normalized)
    if (possibleCity && !isSupportedCity(possibleCity[1])) {
      warnings.push({
        code: 'UNSUPPORTED_CITY',
        message: `"${possibleCity[1]}"不在当前支持的城市列表中（广州、北京、上海）`,
        fragment: possibleCity[1],
      })
    }
  }

  // 5. 人数
  const travelers = extractTravelers(normalized)
  if (travelers) {
    if (travelers.source === 'ambiguous') {
      warnings.push({ code: 'AMBIGUOUS_TRAVELERS', message: '无法确定具体人数，请补充', fragment: '' })
    } else {
      operations.push({ type: 'set', field: 'travelers', value: travelers.value! })
    }
  }

  // 6. 预算
  const budget = extractBudget(normalized)
  if (budget && budget.value !== undefined) {
    operations.push({ type: 'set', field: 'budgetAmount', value: budget.value })
  }

  // 7. 偏好
  const prefs = extractPreferences(normalized)
  for (const p of prefs) {
    operations.push({ type: 'append', field: 'preferences', value: p })
  }

  // 8. 必去地点
  const mustVisit = extractMustVisit(normalized)
  for (const mv of mustVisit) {
    operations.push({ type: 'append', field: 'mustVisitPlaces', value: mv })
  }

  // 9. 未解析判断
  if (operations.length === 0) {
    unrecognized.push(normalized)
  }

  return { operations, warnings, unrecognized }
}
