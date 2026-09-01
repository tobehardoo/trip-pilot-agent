import { describe, expect, test } from 'vitest'

import { mergeTripPilotEnv } from '../vite-env'

describe('Vite environment loading', () => {
  test('lets Web-local values override repository values without dropping backend settings', () => {
    expect(mergeTripPilotEnv(
      { TRAVEL_SERVER_URL: 'http://localhost:8080', VITE_AMAP_WEB_JS_KEY: 'root-key' },
      { VITE_AMAP_WEB_JS_KEY: 'web-key', VITE_AMAP_SECURITY_CODE: 'web-security' },
    )).toEqual({
      TRAVEL_SERVER_URL: 'http://localhost:8080',
      VITE_AMAP_WEB_JS_KEY: 'web-key',
      VITE_AMAP_SECURITY_CODE: 'web-security',
    })
  })
})
