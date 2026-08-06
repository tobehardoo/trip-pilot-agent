import { describe, expect, it } from 'vitest'
import { parseConstraint } from '../src/lib/constraint-parser'

// 固定 now = 2026-08-05 周三 UTC+8 12:00
const NOW = new Date('2026-08-05T04:00:00Z')

function parse(text: string) {
  return parseConstraint(text, NOW)
}

function getValue(ops: ReturnType<typeof parse>['operations'], field: string) {
  // 最后一个 set 生效
  for (let i = ops.length - 1; i >= 0; i--) {
    if (ops[i].type === 'set' && ops[i].field === field) return ops[i].value
  }
  return undefined
}

function getAppended(ops: ReturnType<typeof parse>['operations'], field: string): unknown[] {
  return ops.filter((o) => o.type === 'append' && o.field === field).map((o) => o.value)
}

describe('城市解析', () => {
  it('去广州玩', () => {
    const r = parse('去广州玩')
    const dest = getValue(r.operations, 'destination') as any
    expect(dest.city).toBe('广州')
    expect(dest.province).toBe('广东省')
  })
  it('广州三日游', () => {
    const r = parse('广州三日游')
    const dest = getValue(r.operations, 'destination') as any
    expect(dest.city).toBe('广州')
  })
  it('想去广州市', () => {
    const r = parse('想去广州市')
    const dest = getValue(r.operations, 'destination') as any
    expect(dest.city).toBe('广州')
  })
  it('不支持的城市', () => {
    const r = parse('去火星玩')
    expect(r.warnings.some((w) => w.code === 'UNSUPPORTED_CITY')).toBe(true)
  })
  it('多城市取第一个', () => {
    const r = parse('去广州和北京')
    const dest = getValue(r.operations, 'destination') as any
    expect(dest.city).toBe('广州')
  })
})

describe('日期解析', () => {
  it('明天去广州玩两天', () => {
    const r = parse('明天去广州玩两天')
    expect(getValue(r.operations, 'startDate')).toBe('2026-08-06')
    expect(getValue(r.operations, 'endDate')).toBe('2026-08-07')
  })
  it('下周末', () => {
    const r = parse('下周末去北京')
    expect(getValue(r.operations, 'startDate')).toBe('2026-08-15')
  })
  it('8月10日去杭州', () => {
    const r = parse('8月10日去杭州')
    expect(getValue(r.operations, 'startDate')).toBe('2026-08-10')
  })
  it('8月10日到12日', () => {
    const r = parse('8月10日到12日去杭州')
    expect(getValue(r.operations, 'startDate')).toBe('2026-08-10')
    expect(getValue(r.operations, 'endDate')).toBe('2026-08-12')
  })
  it('12月31日去两天', () => {
    const r = parse('12月31日去两天')
    expect(getValue(r.operations, 'startDate')).toBe('2026-12-31')
  })
})

describe('人数解析', () => {
  it('一个人', () => {
    expect(getValue(parse('一个人去广州').operations, 'travelers')).toBe(1)
  })
  it('两个人', () => {
    expect(getValue(parse('两个人去广州').operations, 'travelers')).toBe(2)
  })
  it('和女朋友', () => {
    expect(getValue(parse('和女朋友去广州').operations, 'travelers')).toBe(2)
  })
  it('和爸妈', () => {
    expect(getValue(parse('和爸妈去旅游').operations, 'travelers')).toBe(3)
  })
  it('带孩子 → ambiguous', () => {
    const r = parse('带孩子去玩')
    expect(r.warnings.some((w) => w.code === 'AMBIGUOUS_TRAVELERS')).toBe(true)
  })
})

describe('预算解析', () => {
  it('预算3000', () => {
    expect(getValue(parse('预算3000').operations, 'budgetAmount')).toBe(3000)
  })
  it('三千', () => {
    expect(getValue(parse('预算三千').operations, 'budgetAmount')).toBe(3000)
  })
  it('预算不限', () => {
    expect(getValue(parse('预算不限').operations, 'budgetAmount')).toBe(null)
  })
  it('3000元', () => {
    expect(getValue(parse('预算大约3000元').operations, 'budgetAmount')).toBe(3000)
  })
})

describe('偏好解析', () => {
  it('喜欢历史文化', () => {
    const r = parse('喜欢历史文化')
    expect(getAppended(r.operations, 'preferences')).toContain('历史文化')
  })
  it('想吃美食', () => {
    const r = parse('想吃美食')
    expect(getAppended(r.operations, 'preferences')).toContain('美食')
  })
  it('博物馆 → 历史文化', () => {
    const r = parse('喜欢博物馆')
    expect(getAppended(r.operations, 'preferences')).toContain('历史文化')
  })
})

describe('必去地点', () => {
  it('一定要去陈家祠', () => {
    const r = parse('一定要去陈家祠')
    expect(getAppended(r.operations, 'mustVisitPlaces')).toContain('陈家祠')
  })
  it('陈家祠和沙面必须去', () => {
    const r = parse('陈家祠和沙面必须去')
    const mv = getAppended(r.operations, 'mustVisitPlaces')
    expect(mv.length).toBeGreaterThanOrEqual(2)
  })
})

describe('修改意图', () => {
  it('不是广州，是佛山', () => {
    const r = parse('不是广州，是佛山')
    // 佛山不在白名单中，会警告
    expect(r.warnings.some((w) => w.code === 'UNSUPPORTED_CITY')).toBe(true)
  })
  it('预算改成5000', () => {
    const r = parse('预算改成5000')
    expect(getValue(r.operations, 'budgetAmount')).toBe(5000)
  })
  it('不去陈家祠了', () => {
    const r = parse('不去陈家祠了')
    expect(r.operations.some((o) => o.type === 'remove' && o.field === 'mustVisitPlaces')).toBe(true)
  })
  it('再加广东省博物馆', () => {
    const r = parse('再加广东省博物馆')
    expect(getAppended(r.operations, 'mustVisitPlaces')).toContain('广东省博物馆')
  })
})

describe('组合输入', () => {
  it('下周末去广州两个人预算3000喜欢历史文化一定要去陈家祠', () => {
    const r = parse('下周末去广州，两个人，预算3000，喜欢历史文化，一定要去陈家祠')
    const dest = getValue(r.operations, 'destination') as any
    expect(dest.city).toBe('广州')
    expect(getValue(r.operations, 'startDate')).toBe('2026-08-15')
    expect(getValue(r.operations, 'travelers')).toBe(2)
    expect(getValue(r.operations, 'budgetAmount')).toBe(3000)
    expect(getAppended(r.operations, 'preferences')).toContain('历史文化')
    expect(getAppended(r.operations, 'mustVisitPlaces')).toContain('陈家祠')
  })
})

describe('异常输入', () => {
  it('空字符串', () => {
    const r = parse('')
    expect(r.operations.length).toBe(0)
    expect(r.unrecognized).toContain('输入为空')
  })
  it('纯空格', () => {
    const r = parse('   ')
    expect(r.operations.length).toBe(0)
  })
  it('无关内容', () => {
    const r = parse('今天天气真好')
    expect(r.operations.length).toBe(0)
    expect(r.unrecognized.length).toBeGreaterThan(0)
  })
  it('火星', () => {
    const r = parse('去火星三日游')
    expect(r.warnings.some((w) => w.code === 'UNSUPPORTED_CITY')).toBe(true)
  })
})
