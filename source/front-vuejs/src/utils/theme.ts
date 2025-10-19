const STORAGE_KEY = 'ui:theme'

function getSystemPrefersDark(): boolean {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
}

export function getCurrentTheme(): 'light' | 'dark' {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved === 'light' || saved === 'dark') {
    return saved
  }
  return getSystemPrefersDark() ? 'dark' : 'light'
}

export function applyTheme(theme?: 'light' | 'dark'): 'light' | 'dark' {
  const next = theme ?? getCurrentTheme()
  document.documentElement.setAttribute('data-theme', next)
  localStorage.setItem(STORAGE_KEY, next)
  window.dispatchEvent(new CustomEvent('themechange', { detail: { theme: next } }))
  return next
}

export function toggleTheme(): 'light' | 'dark' {
  const current = getCurrentTheme()
  const next = current === 'dark' ? 'light' : 'dark'
  return applyTheme(next)
}

export function watchSystemThemeChanges(callback: (theme: 'light' | 'dark') => void): () => void {
  const media = window.matchMedia('(prefers-color-scheme: dark)')
  const handler = () => {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (!saved) {
      callback(applyTheme())
    }
  }
  media.addEventListener?.('change', handler)
  return () => media.removeEventListener?.('change', handler)
}
