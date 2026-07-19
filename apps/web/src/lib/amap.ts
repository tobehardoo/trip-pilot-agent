export interface AMapConfig {
  key: string
  securityJsCode: string
}

export interface AMapMarker {
  setMap(map: AMapMap | null): void
  on?(event: string, handler: () => void): void
  setPosition?(position: [number, number]): void
  setContent?(content: string): void
}

export interface AMapPolyline {
  setMap(map: AMapMap | null): void
}

export interface AMapMap {
  setFitView(overlays?: unknown[]): void
  setCenter?(position: [number, number]): void
  setZoom?(zoom: number): void
  destroy?(): void
}

export interface AMapNamespace {
  Map: new (container: HTMLElement, options?: Record<string, unknown>) => AMapMap
  Marker: new (options: Record<string, unknown>) => AMapMarker
  Polyline: new (options: Record<string, unknown>) => AMapPolyline
}

declare global {
  interface Window {
    AMap?: AMapNamespace
    _AMapSecurityConfig?: { securityJsCode?: string }
  }
}

export function getAMapConfig(): AMapConfig | null {
  const key = import.meta.env.VITE_AMAP_WEB_JS_KEY?.trim()
  const securityJsCode = import.meta.env.VITE_AMAP_SECURITY_CODE?.trim()
  if (!key || !securityJsCode) return null
  return { key, securityJsCode }
}

let amapPromise: Promise<AMapNamespace> | null = null

export function loadAMap(config = getAMapConfig()): Promise<AMapNamespace> {
  if (!config) return Promise.reject(new Error('VITE_AMAP_WEB_JS_KEY is not configured'))
  if (window.AMap) return Promise.resolve(window.AMap)
  if (amapPromise) return amapPromise

  amapPromise = new Promise<AMapNamespace>((resolve, reject) => {
    window._AMapSecurityConfig = { securityJsCode: config.securityJsCode }
    const existing = document.querySelector<HTMLScriptElement>('script[data-trip-pilot-amap]')
    const handleLoad = (script: HTMLScriptElement) => {
      if (window.AMap) resolve(window.AMap)
      else {
        script.remove()
        reject(new Error('AMap SDK loaded without a namespace'))
      }
    }
    const handleError = (script: HTMLScriptElement) => {
      script.remove()
      reject(new Error('AMap SDK failed to load'))
    }
    if (existing) {
      existing.addEventListener('load', () => handleLoad(existing), { once: true })
      existing.addEventListener('error', () => handleError(existing), { once: true })
      return
    }
    const script = document.createElement('script')
    script.dataset.tripPilotAmap = 'true'
    script.async = true
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(config.key)}`
    script.addEventListener('load', () => handleLoad(script), { once: true })
    script.addEventListener('error', () => handleError(script), { once: true })
    document.head.appendChild(script)
  }).finally(() => {
    amapPromise = null
  })
  return amapPromise
}
