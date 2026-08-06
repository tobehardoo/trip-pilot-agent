/**
 * 当前支持的城市白名单。
 *
 * 与后端 CityIntelligencePrewarmService.cityCode() + knowledge/sources/ 保持同步。
 * 后端新增城市时必须同步更新此列表。
 */
export const SUPPORTED_CITIES: ReadonlyArray<string> = [
  '广州',
  '北京',
  '上海',
]

const _CITY_SET = new Set(SUPPORTED_CITIES.map((c) => c.toLowerCase()))

/** 检查城市名是否在支持列表中。"市"后缀和大小写均忽略。 */
export function isSupportedCity(name: string): boolean {
  const normalized = name.trim().replace(/市$/, '').toLowerCase()
  return _CITY_SET.has(normalized)
}

/** 从文本中提取第一个匹配的支持城市名。返回标准化城市名或 null。 */
export function extractCity(text: string): string | null {
  // 长度降序：先匹配"广州市"再匹配"广州"
  const sorted = [...SUPPORTED_CITIES].sort((a, b) => b.length - a.length)
  for (const city of sorted) {
    const pattern = new RegExp(`${escapeRegExp(city)}市?`, 'i')
    if (pattern.test(text)) {
      return city
    }
  }
  return null
}

function escapeRegExp(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
