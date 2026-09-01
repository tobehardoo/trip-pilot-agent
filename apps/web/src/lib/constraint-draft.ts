/**
 * 结构化目的地与区域引用工具（B13-B）。
 *
 * 从省市区级联选择转换为后端 RegionRef；旧自由文本目的地永远返回
 * undefined（legacy，不伪造行政区代码）。
 */
import type { RegionRef } from './api'

export interface StructuredDestination {
  province: string
  provinceCode?: string
  city: string
  cityCode?: string
  districts: string[]
  districtCodes?: string[]
}

export const REGION_DATASET_VERSION = '2023-06-30'

export function destinationToRegionRef(
  destination: string | StructuredDestination,
): RegionRef | undefined {
  if (typeof destination === 'string') return undefined
  const provinceCode = destination.provinceCode
  const cityCode = destination.cityCode
  const districtCodes = destination.districtCodes ?? []
  if (!provinceCode || !cityCode) return undefined
  if (!/^\d{6}$/.test(provinceCode) || !/^\d{6}$/.test(cityCode)) return undefined
  if (!provinceCode.endsWith('0000') || provinceCode.slice(0, 2) !== cityCode.slice(0, 2)) {
    return undefined
  }
  const municipality = cityCode.slice(2, 4) === '00'
  const districtBelongs = municipality
    ? (code: string) => code.slice(0, 2) === cityCode.slice(0, 2)
    : (code: string) => code.slice(0, 4) === cityCode.slice(0, 4)
  if (districtCodes.some((code) => !/^\d{6}$/.test(code)
    || code === cityCode
    || code.endsWith('00')
    || !districtBelongs(code))) {
    return undefined
  }
  return {
    provinceCode,
    cityCode,
    districtCodes: [...districtCodes],
    provinceName: destination.province,
    cityName: destination.city,
    districtNames: [...destination.districts],
    datasetVersion: REGION_DATASET_VERSION,
  }
}
