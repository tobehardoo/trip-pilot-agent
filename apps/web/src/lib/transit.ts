import type { ItineraryTransitLeg } from './api'

export type ConcreteCommuteMode = 'WALKING' | 'TRANSIT' | 'DRIVING' | 'TAXI'
export type CommuteMode = 'AUTO' | ConcreteCommuteMode

/**
 * 交通方式对当前 itinerary 的可用状态：
 * - AVAILABLE：真实可用且当前时间空档能容纳；
 * - REQUIRES_REPLAN：真实可用但当前时间空档不足，仍允许选择，需要调整后续行程；
 * - UNAVAILABLE：真实不可用（Provider 无路线、业务规则禁止、数据缺失）。
 */
export type CommuteModeStatus = 'AVAILABLE' | 'REQUIRES_REPLAN' | 'UNAVAILABLE'

export function commuteModeStatus(
  mode: ConcreteCommuteMode,
  options: CommuteEstimate[],
  availableSeconds?: number,
): CommuteModeStatus {
  const option = options.find((candidate) => candidate.mode === mode)
  if (!option) return 'UNAVAILABLE'
  if (availableSeconds !== undefined && option.durationSeconds > availableSeconds) {
    return 'REQUIRES_REPLAN'
  }
  return 'AVAILABLE'
}

export interface CommuteEstimate {
  mode: ConcreteCommuteMode
  durationSeconds: number
  cost: number
  estimated: boolean
}

const WALKING_SPEED_METERS_PER_SECOND = 1.25
const TRANSIT_SPEED_METERS_PER_SECOND = 5.5
const DRIVING_SPEED_METERS_PER_SECOND = 8.33

function roundDuration(seconds: number) {
  return Math.max(60, Math.round(seconds / 60) * 60)
}

function roundMoney(value: number) {
  return Math.round(value * 100) / 100
}

export function estimateCommuteOptions(
  leg: Pick<ItineraryTransitLeg, 'mode' | 'distanceMeters' | 'durationSeconds' | 'estimated'>,
): CommuteEstimate[] {
  const distance = Math.max(1, leg.distanceMeters)
  const distanceKilometers = distance / 1000
  const walkingDuration = leg.mode === 'WALKING'
    ? leg.durationSeconds
    : distance / WALKING_SPEED_METERS_PER_SECOND
  const drivingDuration = leg.mode === 'DRIVING'
    ? leg.durationSeconds
    : distance / DRIVING_SPEED_METERS_PER_SECOND + 180

  return [
    {
      mode: 'WALKING',
      durationSeconds: roundDuration(walkingDuration),
      cost: 0,
      estimated: leg.mode !== 'WALKING' || leg.estimated,
    },
    {
      mode: 'TRANSIT',
      durationSeconds: roundDuration(distance / TRANSIT_SPEED_METERS_PER_SECOND + 420),
      cost: roundMoney(2 + Math.floor(distanceKilometers / 6)),
      estimated: true,
    },
    {
      mode: 'DRIVING',
      durationSeconds: roundDuration(drivingDuration),
      cost: roundMoney(Math.max(3, distanceKilometers * 0.8)),
      estimated: leg.mode !== 'DRIVING' || leg.estimated,
    },
    {
      mode: 'TAXI',
      durationSeconds: roundDuration(drivingDuration + 120),
      cost: roundMoney(12 + distanceKilometers * 2.6),
      estimated: true,
    },
  ]
}

export function recommendedCommuteMode(options: CommuteEstimate[]): ConcreteCommuteMode {
  const walking = options.find((option) => option.mode === 'WALKING')
  const transit = options.find((option) => option.mode === 'TRANSIT')
  const taxi = options.find((option) => option.mode === 'TAXI')
  const driving = options.find((option) => option.mode === 'DRIVING')

  if (walking && walking.durationSeconds <= 20 * 60) return 'WALKING'
  if (transit && (!taxi || transit.durationSeconds <= taxi.durationSeconds * 1.6)) return 'TRANSIT'
  if (taxi) return 'TAXI'
  if (driving) return 'DRIVING'
  return walking?.mode ?? options[0]?.mode ?? 'WALKING'
}
