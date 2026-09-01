/**
 * B13-C: deterministic default trip-title preview.
 *
 * Mirrors the server-side TripTitleGenerator byte-for-byte so the form
 * preview and the persisted fallback always agree.  Dates are formatted in
 * Asia/Shanghai; same-year ranges drop the leading year from the second
 * date.
 */
export function defaultTripTitle(city: string, startDate: string, endDate: string): string {
  const base = normalizeCity(city)
  const sameYear = startDate.slice(0, 4) === endDate.slice(0, 4)
  const start = formatChinaDate(startDate, true)
  const end = formatChinaDate(endDate, !sameYear)
  return `${start}—${end} ${base}旅行规划`
}

function normalizeCity(city: string): string {
  const trimmed = city.trim()
  if (!trimmed) return ''
  for (const suffix of ['市', '自治州', '地区', '盟', '特别行政区']) {
    if (trimmed.endsWith(suffix)) return trimmed
  }
  return `${trimmed}市`
}

/** Formats YYYY-MM-DD as 年月日/月日 in Asia/Shanghai (date-only, tz-stable). */
function formatChinaDate(value: string, withYear: boolean): string {
  const [year, month, day] = value.split('-')
  return withYear
    ? `${year}年${pad(month)}月${pad(day)}日`
    : `${pad(month)}月${pad(day)}日`
}

function pad(part: string): string {
  return part.padStart(2, '0')
}
