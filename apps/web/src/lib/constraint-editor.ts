import type { PlaceRef, TripConstraints } from './api'

export type MealSource = 'DEFAULT' | 'USER' | 'DISABLED'

/**
 * B13-D: one selected place entry.  Structured candidates carry a PlaceRef;
 * legacy free-text names keep no ref and are never upgraded.
 */
export interface PlaceEntry {
  name: string
  placeRef?: PlaceRef
}

// Canonical soft-suggestion windows shown for DEFAULT meals and carried as
// inert payload for DISABLED meals (the wire still requires times).
export const MEAL_DEFAULT_WINDOWS: Record<'BREAKFAST' | 'LUNCH' | 'DINNER', [string, string]> = {
  BREAKFAST: ['08:00', '09:00'],
  LUNCH: ['12:00', '13:00'],
  DINNER: ['18:00', '19:00'],
}

export interface ConstraintEditorModel {
  budgetAmount: string
  travelers: number
  travelerType: TripConstraints['travelerType']
  pace: TripConstraints['pace']
  preferences: string[]
  arrivalPlace: string
  arrivalTime: string
  arrivalRef?: PlaceRef
  departurePlace: string
  departureTime: string
  departureRef?: PlaceRef
  accommodationPlace: string
  accommodationRef?: PlaceRef
  // B13_FIX.1 R2: immutable snapshot of the persisted anchor state at edit
  // time, so an untouched legacy free-text anchor can keep saving while any
  // newly typed or changed anchor must be re-selected from candidates.
  originalArrivalPlace: string
  originalArrivalRef?: PlaceRef
  originalDeparturePlace: string
  originalDepartureRef?: PlaceRef
  originalAccommodationPlace: string
  originalAccommodationRef?: PlaceRef
  mustVisitEntries: PlaceEntry[]
  avoidEntries: PlaceEntry[]
  breakfastSource: MealSource
  breakfastStart: string
  breakfastEnd: string
  lunchSource: MealSource
  lunchStart: string
  lunchEnd: string
  dinnerSource: MealSource
  dinnerStart: string
  dinnerEnd: string
  mobilityLevel: NonNullable<TripConstraints['mobilityLevel']>
}

export function createConstraintEditorModel(
  constraints?: TripConstraints,
): ConstraintEditorModel {
  const windows = constraints?.mealWindows ?? []
  const meal = (type: 'BREAKFAST' | 'LUNCH' | 'DINNER') =>
    windows.find((window) => window.mealType === type)
  // B13-F: absent windows default to the soft DEFAULT suggestion; historical
  // windows without a source keep hard USER semantics (never downgraded).
  const mealSource = (type: 'BREAKFAST' | 'LUNCH' | 'DINNER'): MealSource =>
    meal(type)?.source ?? (meal(type) ? 'USER' : 'DEFAULT')
  return {
    budgetAmount: constraints
      ? constraints.budgetAmount?.toString() ?? ''
      : '3000',
    travelers: constraints?.travelers ?? 1,
    travelerType: constraints?.travelerType ?? 'SOLO',
    pace: constraints?.pace ?? 'BALANCED',
    preferences: [...(constraints?.preferences ?? [])],
    arrivalPlace: constraints?.arrival?.placeName ?? '',
    arrivalTime: toChinaLocalInput(constraints?.arrival?.time),
    arrivalRef: constraints?.arrival?.placeRef,
    originalArrivalPlace: constraints?.arrival?.placeName ?? '',
    originalArrivalRef: constraints?.arrival?.placeRef,
    departurePlace: constraints?.departure?.placeName ?? '',
    departureTime: toChinaLocalInput(constraints?.departure?.time),
    departureRef: constraints?.departure?.placeRef,
    originalDeparturePlace: constraints?.departure?.placeName ?? '',
    originalDepartureRef: constraints?.departure?.placeRef,
    accommodationPlace: constraints?.accommodation?.placeName ?? '',
    accommodationRef: constraints?.accommodation?.placeRef,
    originalAccommodationPlace: constraints?.accommodation?.placeName ?? '',
    originalAccommodationRef: constraints?.accommodation?.placeRef,
    mustVisitEntries: entryList(
      constraints?.mustVisitPlaces ?? [],
      constraints?.mustVisitPlaceRefs ?? [],
    ),
    avoidEntries: entryList(
      constraints?.avoidPlaces ?? [],
      constraints?.avoidPlaceRefs ?? [],
    ),
    breakfastSource: mealSource('BREAKFAST'),
    breakfastStart: meal('BREAKFAST')?.startTime.slice(0, 5) ?? '',
    breakfastEnd: meal('BREAKFAST')?.endTime.slice(0, 5) ?? '',
    lunchSource: mealSource('LUNCH'),
    lunchStart: meal('LUNCH')?.startTime.slice(0, 5) ?? '',
    lunchEnd: meal('LUNCH')?.endTime.slice(0, 5) ?? '',
    dinnerSource: mealSource('DINNER'),
    dinnerStart: meal('DINNER')?.startTime.slice(0, 5) ?? '',
    dinnerEnd: meal('DINNER')?.endTime.slice(0, 5) ?? '',
    mobilityLevel: constraints?.mobilityLevel ?? 'STANDARD',
  }
}

function entryList(names: string[], refs: PlaceRef[]): PlaceEntry[] {
  return names.map((name, index) => ({ name, placeRef: refs[index] }))
}

export function validateConstraintEditor(
  model: ConstraintEditorModel,
  mode: 'create' | 'edit' = 'edit',
): string | null {
  if (model.travelers < 1 || model.travelers > 50) return '同行人数必须在 1 到 50 之间'
  if (model.budgetAmount !== '' && Number(model.budgetAmount) < 0) return '预算不能小于 0'
  if (Boolean(model.arrivalPlace) !== Boolean(model.arrivalTime)) {
    return '请同时填写到达地点和到达时间'
  }
  if (Boolean(model.departurePlace) !== Boolean(model.departureTime)) {
    return '请同时填写返程地点和返程时间'
  }
  const anchorError = validateAnchor(
    '到达地点',
    model.arrivalPlace,
    model.arrivalRef,
    mode,
    model.originalArrivalPlace,
    model.originalArrivalRef,
  )
  if (anchorError) return anchorError
  const departureError = validateAnchor(
    '返程地点',
    model.departurePlace,
    model.departureRef,
    mode,
    model.originalDeparturePlace,
    model.originalDepartureRef,
  )
  if (departureError) return departureError
  const accommodationError = validateAnchor(
    '住宿锚点',
    model.accommodationPlace,
    model.accommodationRef,
    mode,
    model.originalAccommodationPlace,
    model.originalAccommodationRef,
  )
  if (accommodationError) return accommodationError
  // B13_FIX.1 R2: newly added must/avoid entries must come from candidates.
  // Legacy entries preserved from the persisted trip stay untouched.
  if (mode === 'create') {
    for (const entry of [...model.mustVisitEntries, ...model.avoidEntries]) {
      if (entry.name && !entry.placeRef) return '请从搜索结果中选择有效地点'
    }
  }
  const incompleteUserMeal = [
    ['早餐', model.breakfastSource, model.breakfastStart, model.breakfastEnd],
    ['午餐', model.lunchSource, model.lunchStart, model.lunchEnd],
    ['晚餐', model.dinnerSource, model.dinnerStart, model.dinnerEnd],
  ].find(
    ([, source, start, end]) =>
      source === 'USER' && (!Boolean(start) || !Boolean(end)),
  )
  return incompleteUserMeal ? `请同时填写${incompleteUserMeal[0]}窗口的开始和结束时间` : null
}

function validateAnchor(
  label: string,
  place: string,
  ref: PlaceRef | undefined,
  mode: 'create' | 'edit',
  originalPlace: string,
  originalRef: PlaceRef | undefined,
): string | null {
  const current = place.trim()
  if (!current) return null // empty anchors follow the field's optionality
  if (ref) return null // a selected candidate always satisfies the gate
  // Edit mode keeps an untouched legacy free-text anchor exactly as it was
  // persisted; any change (or a create-mode free text) needs a candidate.
  const unchangedLegacy = mode === 'edit'
    && current === originalPlace
    && !originalRef
    && originalPlace !== ''
  if (unchangedLegacy) return null
  return '请从搜索结果中选择有效地点'
}

export function toTripConstraints(
  model: ConstraintEditorModel,
  fixedSchedules: TripConstraints['fixedSchedules'],
): Omit<TripConstraints, 'schemaVersion'> {
  return {
    budgetAmount: model.budgetAmount === '' ? null : Number(model.budgetAmount),
    travelers: model.travelers,
    travelerType: model.travelerType,
    pace: model.pace,
    preferences: [...model.preferences],
    fixedSchedules: fixedSchedules.map((schedule) => ({ ...schedule })),
    arrival: model.arrivalPlace && model.arrivalTime
      ? {
          placeName: model.arrivalPlace,
          time: `${model.arrivalTime}:00+08:00`,
          ...(model.arrivalRef ? { placeRef: model.arrivalRef } : {}),
        }
      : null,
    departure: model.departurePlace && model.departureTime
      ? {
          placeName: model.departurePlace,
          time: `${model.departureTime}:00+08:00`,
          ...(model.departureRef ? { placeRef: model.departureRef } : {}),
        }
      : null,
    accommodation: model.accommodationPlace
      ? {
          placeName: model.accommodationPlace,
          ...(model.accommodationRef ? { placeRef: model.accommodationRef } : {}),
        }
      : null,
    mustVisitPlaces: model.mustVisitEntries.map((entry) => entry.name),
    avoidPlaces: model.avoidEntries.map((entry) => entry.name),
    ...(allStructured(model.mustVisitEntries)
      ? { mustVisitPlaceRefs: model.mustVisitEntries.map((entry) => entry.placeRef as PlaceRef) }
      : {}),
    ...(allStructured(model.avoidEntries)
      ? { avoidPlaceRefs: model.avoidEntries.map((entry) => entry.placeRef as PlaceRef) }
      : {}),
    mealWindows: buildMealWindows(model),
    mobilityLevel: model.mobilityLevel,
  }
}

/**
 * B13-D: refs are parallel to names on the wire, so they are emitted only
 * when every entry is structured.  A mix with legacy free text sends no refs
 * at all — legacy names are never silently upgraded.
 */
function allStructured(entries: PlaceEntry[]): boolean {
  return entries.length > 0 && entries.every((entry) => entry.placeRef !== undefined)
}

function buildMealWindows(
  model: ConstraintEditorModel,
): NonNullable<TripConstraints['mealWindows']> {
  return ([
    ['BREAKFAST', 'breakfast', model.breakfastSource],
    ['LUNCH', 'lunch', model.lunchSource],
    ['DINNER', 'dinner', model.dinnerSource],
  ] as const)
    .map(([mealType, key, source]) => {
      if (source === 'USER') {
        const start = model[`${key}Start`]
        const end = model[`${key}End`]
        if (!start || !end) return null
        return { mealType, startTime: start, endTime: end, source }
      }
      const [defaultStart, defaultEnd] = MEAL_DEFAULT_WINDOWS[mealType]
      return { mealType, startTime: defaultStart, endTime: defaultEnd, source }
    })
    .filter((window): window is NonNullable<typeof window> => window !== null)
}

function toChinaLocalInput(value?: string): string {
  if (!value) return ''
  return new Date(value).toLocaleString('sv-SE', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
  }).replace(' ', 'T').slice(0, 16)
}
