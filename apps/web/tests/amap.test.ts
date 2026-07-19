import { afterEach, expect, test, vi } from 'vitest'

import { getAMapConfig, loadAMap, type AMapNamespace } from '../src/lib/amap'

afterEach(() => {
  delete window.AMap
  delete window._AMapSecurityConfig
  document.querySelectorAll('script[data-trip-pilot-amap]').forEach((script) => script.remove())
  vi.unstubAllEnvs()
})

test('loads the browser-only AMap key and applies the security code before the SDK resolves', async () => {
  const loading = loadAMap({ key: 'browser-js-key', securityJsCode: 'browser-security-code' })
  const script = document.querySelector<HTMLScriptElement>('script[data-trip-pilot-amap]')

  expect(script?.src).toContain('key=browser-js-key')
  expect(window._AMapSecurityConfig).toEqual({ securityJsCode: 'browser-security-code' })

  const namespace = {} as AMapNamespace
  window.AMap = namespace
  script?.dispatchEvent(new Event('load'))
  await expect(loading).resolves.toBe(namespace)
  delete window.AMap
})

test('treats a JS key without its security code as incomplete browser credentials', () => {
  vi.stubEnv('VITE_AMAP_WEB_JS_KEY', 'browser-js-key')
  vi.stubEnv('VITE_AMAP_SECURITY_CODE', '')

  expect(getAMapConfig()).toBeNull()
})

test('removes a failed script so a later attempt can load a fresh SDK', async () => {
  const firstAttempt = loadAMap({ key: 'first-browser-key', securityJsCode: 'first-security-code' })
  const failedScript = document.querySelector<HTMLScriptElement>('script[data-trip-pilot-amap]')
  failedScript?.dispatchEvent(new Event('error'))

  await expect(firstAttempt).rejects.toThrow('AMap SDK failed to load')
  expect(document.querySelector('script[data-trip-pilot-amap]')).toBeNull()

  const secondAttempt = loadAMap({ key: 'second-browser-key', securityJsCode: 'second-security-code' })
  const replacementScript = document.querySelector<HTMLScriptElement>('script[data-trip-pilot-amap]')
  expect(replacementScript).not.toBe(failedScript)
  window.AMap = {} as AMapNamespace
  replacementScript?.dispatchEvent(new Event('load'))
  await expect(secondAttempt).resolves.toBe(window.AMap)
})
