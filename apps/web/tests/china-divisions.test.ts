import { describe, expect, it } from 'vitest'

import { cityAdcode, findCity, findProvince, PROVINCES } from '../src/lib/china-divisions'

// B13_FIX R8 (P1-8): lookup helpers must resolve provinces/cities/adcodes.
describe('china-divisions lookup helpers', () => {
  it('finds a province by exact or prefixed name', () => {
    expect(findProvince('广东省')?.name).toBe('广东省')
    expect(findProvince('广东')?.name).toBe('广东省')
    expect(findProvince('不存在的省')).toBeUndefined()
  })

  it('finds a city inside a province by exact or prefixed name', () => {
    const guangdong = findProvince('广东省')
    expect(guangdong).toBeDefined()
    expect(findCity(guangdong!, '广州')?.name).toBe('广州')
    expect(findCity(guangdong!, '广')?.name).toBe('广州')
    expect(findCity(guangdong!, '不存在的市')).toBeUndefined()
  })

  it('resolves the municipality city code for 重庆 and explicit adcodes', () => {
    const chongqing = findProvince('重庆市')
    expect(chongqing).toBeDefined()
    const city = findCity(chongqing!, '重庆')
    expect(city).toBeDefined()
    expect(cityAdcode(city!)).toBe('500000')
    // A city without a fallback still reports its explicit adcode.
    expect(cityAdcode({ name: '广州市', adcode: '440100', districts: [] })).toBe('440100')
  })

  it('keeps a stable province dataset with the four municipalities', () => {
    const names = PROVINCES.map((province) => province.name)
    expect(names).toContain('北京市')
    expect(names).toContain('上海市')
    expect(names).toContain('天津市')
    expect(names).toContain('重庆市')
  })
})
