import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { expect, test } from 'vitest'

test('declares an existing favicon', () => {
  const projectRoot = resolve(import.meta.dirname, '..')
  const html = readFileSync(resolve(projectRoot, 'index.html'), 'utf8')

  expect(html).toContain('href="/favicon.svg"')
  expect(existsSync(resolve(projectRoot, 'public/favicon.svg'))).toBe(true)
})
