import { afterEach, beforeAll, vi } from 'vitest'

beforeAll(() => {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query.includes('max-width') ? false : false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn()
  }))

  if (!('open' in window)) {
    vi.stubGlobal('open', vi.fn())
  }

  if (!('scrollTo' in window)) {
    Object.defineProperty(window, 'scrollTo', {
      value: vi.fn(),
      writable: true
    })
  }
})

afterEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
})
