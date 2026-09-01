import type { Itinerary } from './api'

export interface MapCoordinate {
  longitude: number
  latitude: number
}

export interface MapBounds {
  minLongitude: number
  maxLongitude: number
  minLatitude: number
  maxLatitude: number
}

export interface MapActivity {
  id: string
  title: string
  coordinate: MapCoordinate
  dayDate: string
  order: number
}

export interface MapLeg {
  id: string
  fromActivityId: string
  toActivityId: string
  polyline: MapCoordinate[]
  distanceMeters: number
  durationSeconds: number
  estimated: boolean
}

export interface MapModel {
  activities: MapActivity[]
  legs: MapLeg[]
  bounds: MapBounds | null
}

function isCoordinate(value: MapCoordinate | null | undefined): value is MapCoordinate {
  return value !== null
    && value !== undefined
    && Number.isFinite(value.longitude)
    && Number.isFinite(value.latitude)
}

function boundsFor(points: MapCoordinate[]): MapBounds | null {
  if (points.length === 0) return null
  return points.reduce<MapBounds>((bounds, point) => ({
    minLongitude: Math.min(bounds.minLongitude, point.longitude),
    maxLongitude: Math.max(bounds.maxLongitude, point.longitude),
    minLatitude: Math.min(bounds.minLatitude, point.latitude),
    maxLatitude: Math.max(bounds.maxLatitude, point.latitude),
  }), {
    minLongitude: points[0].longitude,
    maxLongitude: points[0].longitude,
    minLatitude: points[0].latitude,
    maxLatitude: points[0].latitude,
  })
}

export function buildMapModel(itinerary: Pick<Itinerary, 'days'>): MapModel {
  const activities: MapActivity[] = []
  const legs: MapLeg[] = []

  itinerary.days.forEach((day) => {
    day.activities.forEach((activity, order) => {
      if (isCoordinate(activity.coordinates)) {
        activities.push({
          id: activity.id,
          title: activity.title,
          coordinate: activity.coordinates,
          dayDate: day.date,
          order,
        })
      }
    })
    for (const leg of day.transitLegs ?? []) {
      const polyline = leg.polyline.filter(isCoordinate)
      if (polyline.length > 1) {
        legs.push({
          id: leg.id,
          fromActivityId: leg.fromActivityId,
          toActivityId: leg.toActivityId,
          polyline,
          distanceMeters: leg.distanceMeters,
          durationSeconds: leg.durationSeconds,
          estimated: leg.estimated,
        })
      }
    }
  })

  return {
    activities,
    legs,
    bounds: boundsFor([
      ...activities.map((activity) => activity.coordinate),
      ...legs.flatMap((leg) => leg.polyline),
    ]),
  }
}

export interface ProjectedMapCoordinate {
  x: number
  y: number
}

export function projectMapCoordinate(coordinate: MapCoordinate, bounds: MapBounds): ProjectedMapCoordinate {
  const longitudeRange = bounds.maxLongitude - bounds.minLongitude
  const latitudeRange = bounds.maxLatitude - bounds.minLatitude
  const longitudeRatio = longitudeRange === 0 ? 0.5 : (coordinate.longitude - bounds.minLongitude) / longitudeRange
  const latitudeRatio = latitudeRange === 0 ? 0.5 : (coordinate.latitude - bounds.minLatitude) / latitudeRange
  return {
    x: 8 + Math.min(1, Math.max(0, longitudeRatio)) * 84,
    y: 92 - Math.min(1, Math.max(0, latitudeRatio)) * 84,
  }
}
