export type AppRoute =
  | { name: 'trip-list' }
  | { name: 'trip-detail'; tripId: string }
  | { name: 'not-found' }

const TRIP_DETAIL_PATH = /^\/trips\/([^/]+)\/?$/

export function parseRoute(pathname: string): AppRoute {
  if (pathname === '/' || pathname === '/trips' || pathname === '/trips/') {
    return { name: 'trip-list' }
  }

  const detailMatch = pathname.match(TRIP_DETAIL_PATH)
  if (detailMatch) {
    try {
      return { name: 'trip-detail', tripId: decodeURIComponent(detailMatch[1]) }
    } catch {
      return { name: 'not-found' }
    }
  }

  return { name: 'not-found' }
}

export function tripDetailPath(tripId: string) {
  return `/trips/${encodeURIComponent(tripId)}`
}
