import type { ItineraryTransitLeg } from './api'

export type PersistedCommuteMode = 'WALKING' | 'TRANSIT' | 'DRIVING' | 'TAXI'
export type CommuteMode = 'AUTO' | 'WALKING' | 'TRANSIT' | 'TAXI'

export function commuteModeLabel(mode: PersistedCommuteMode | CommuteMode | string): string {
  return {
    WALKING: '步行',
    TRANSIT: '公交/地铁',
    DRIVING: '打车',
    TAXI: '打车',
  }[mode] ?? mode
}

export function persistedTransitDisplayCost(
  leg: Pick<ItineraryTransitLeg, 'mode' | 'estimatedCost' | 'displayCost'>,
): number | null {
  if (leg.mode === 'DRIVING') return null
  if (leg.displayCost !== undefined) return leg.displayCost
  return leg.estimatedCost ?? null
}
