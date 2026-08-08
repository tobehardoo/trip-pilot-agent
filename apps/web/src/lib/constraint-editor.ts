import type { TripConstraints } from './api'

export interface ConstraintEditorModel {
  budgetAmount: string
  travelers: number
  travelerType: TripConstraints['travelerType']
  pace: TripConstraints['pace']
  preferences: string[]
  arrivalPlace: string
  arrivalTime: string
  departurePlace: string
  departureTime: string
  accommodationPlace: string
  mustVisitText: string
  avoidText: string
  breakfastStart: string
  breakfastEnd: string
  lunchStart: string
  lunchEnd: string
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
    departurePlace: constraints?.departure?.placeName ?? '',
    departureTime: toChinaLocalInput(constraints?.departure?.time),
    accommodationPlace: constraints?.accommodation?.placeName ?? '',
    mustVisitText: (constraints?.mustVisitPlaces ?? []).join('、'),
    avoidText: (constraints?.avoidPlaces ?? []).join('、'),
    breakfastStart: meal('BREAKFAST')?.startTime.slice(0, 5) ?? '',
    breakfastEnd: meal('BREAKFAST')?.endTime.slice(0, 5) ?? '',
    lunchStart: meal('LUNCH')?.startTime.slice(0, 5) ?? '',
    lunchEnd: meal('LUNCH')?.endTime.slice(0, 5) ?? '',
    dinnerStart: meal('DINNER')?.startTime.slice(0, 5) ?? '',
    dinnerEnd: meal('DINNER')?.endTime.slice(0, 5) ?? '',
    mobilityLevel: constraints?.mobilityLevel ?? 'STANDARD',
  }
}

export function validateConstraintEditor(model: ConstraintEditorModel): string | null {
  if (model.travelers < 1 || model.travelers > 50) return '同行人数必须在 1 到 50 之间'
  if (model.budgetAmount !== '' && Number(model.budgetAmount) < 0) return '预算不能小于 0'
  if (Boolean(model.arrivalPlace) !== Boolean(model.arrivalTime)) {
    return '请同时填写到达地点和到达时间'
  }
  if (Boolean(model.departurePlace) !== Boolean(model.departureTime)) {
    return '请同时填写返程地点和返程时间'
  }
  const partialMeal = [
    ['早餐', model.breakfastStart, model.breakfastEnd],
    ['午餐', model.lunchStart, model.lunchEnd],
    ['晚餐', model.dinnerStart, model.dinnerEnd],
  ].find(([, start, end]) => Boolean(start) !== Boolean(end))
  return partialMeal ? `请同时填写${partialMeal[0]}窗口的开始和结束时间` : null
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
      ? { placeName: model.arrivalPlace, time: `${model.arrivalTime}:00+08:00` }
      : null,
    departure: model.departurePlace && model.departureTime
      ? { placeName: model.departurePlace, time: `${model.departureTime}:00+08:00` }
      : null,
    accommodation: model.accommodationPlace
      ? { placeName: model.accommodationPlace }
      : null,
    mustVisitPlaces: splitPlaces(model.mustVisitText),
    avoidPlaces: splitPlaces(model.avoidText),
    mealWindows: buildMealWindows(model),
    mobilityLevel: model.mobilityLevel,
  }
}

function splitPlaces(value: string): string[] {
  return [...new Set(value.split(/[,，、\n]/).map((item) => item.trim()).filter(Boolean))]
}

function buildMealWindows(
  model: ConstraintEditorModel,
): NonNullable<TripConstraints['mealWindows']> {
  return [
    ['BREAKFAST', model.breakfastStart, model.breakfastEnd],
    ['LUNCH', model.lunchStart, model.lunchEnd],
    ['DINNER', model.dinnerStart, model.dinnerEnd],
  ].filter(([, start, end]) => start && end)
    .map(([mealType, startTime, endTime]) => ({
      mealType: mealType as 'BREAKFAST' | 'LUNCH' | 'DINNER',
      startTime,
      endTime,
    }))
}

function toChinaLocalInput(value?: string): string {
  if (!value) return ''
  return new Date(value).toLocaleString('sv-SE', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
  }).replace(' ', 'T').slice(0, 16)
}
