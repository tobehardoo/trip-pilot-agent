import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, test } from 'vitest'

describe('production nginx configuration', () => {
  test('allows the AMap v2 loader to evaluate its runtime modules', () => {
    const configPath = resolve(process.cwd(), 'nginx.conf')
    const config = readFileSync(configPath, 'utf8')
    const csp = config.match(/add_header Content-Security-Policy "([^"]+)"/)?.[1]
    const directives = Object.fromEntries(
      (csp ?? '').split(';').map((directive) => {
        const [name, ...values] = directive.trim().split(/\s+/)
        return [name, values]
      }),
    )

    expect(directives['script-src']).toContain("'unsafe-eval'")
    expect(directives['script-src']).toContain('https://restapi.amap.com')
    expect(directives['script-src']).toContain('https://jsapi-service.amap.com')
    expect(directives['worker-src']).toEqual(["'self'", 'blob:'])
    expect(directives['default-src']).toEqual(["'self'"])
  })
})
