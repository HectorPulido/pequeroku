export interface ApiRequestOptions extends RequestInit {
  noLoader?: boolean
  noAuthRedirect?: boolean
  suppressAuthRedirect?: boolean
  noAuthAlert?: boolean
}

export interface ContainerSummary {
  id: string
  name: string
  status: string
  username: string
  container_type_name?: string
  created_at: string
}

export interface ContainerType {
  id: number
  container_type_name?: string
  name?: string
  credits_cost?: number
  memory_mb?: number
  vcpus?: number
  disk_gib?: number
}

export interface UserData {
  username?: string
  is_superuser?: boolean
  has_quota?: boolean
  quota?: { credits_left?: number } | null
  [key: string]: unknown
}

export function getCSRF(): string {
  const match = document.cookie.match(/csrftoken=([^;]+)/)
  return match ? match[1] : ''
}

export function signatureFrom(data: ContainerSummary[] | null | undefined): string {
  const norm = (data ?? [])
    .map((c) => ({
      id: c.id,
      status: c.status,
      created_at: c.created_at,
      name: c.name
    }))
    .sort((a, b) => String(a.id).localeCompare(String(b.id)))
  return JSON.stringify(norm)
}

export function isSmallScreen(): boolean {
  return matchMedia('(max-width: 768px)').matches
}

export function makeApi(base: string) {
  return async function api<T = unknown>(
    path: string,
    opts: ApiRequestOptions = {},
    overrideHeaders = true
  ): Promise<T> {
    const requestInit: ApiRequestOptions = { ...opts }
    if (overrideHeaders) {
      requestInit.headers = {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRF(),
        ...(opts.headers ?? {})
      }
    }

    const response = await fetch(base + path, requestInit)
    const text = await response.text()

    if (response.status === 401 || response.status === 403) {
      const suppressRedirect = Boolean(opts.noAuthRedirect || opts.suppressAuthRedirect)
      const suppressAlert = Boolean(opts.noAuthAlert || suppressRedirect)
      if (!suppressAlert) {
        window.dispatchEvent(
          new CustomEvent('notify:alert', {
            detail: { message: 'Sesión expirada', type: 'warning' }
          })
        )
      }
      if (suppressRedirect) {
        window.dispatchEvent(
          new CustomEvent('auth:unauthorized', {
            detail: { status: response.status }
          })
        )
        const error = new Error(text || response.statusText || 'Unauthorized') as Error & {
          status?: number
        }
        error.status = response.status
        throw error
      }
      window.location.href = '/'
      return {} as T
    }

    if (!response.ok) {
      const message = text || response.statusText
      window.dispatchEvent(
        new CustomEvent('notify:alert', {
          detail: { message, type: 'error' }
        })
      )
      throw new Error(message)
    }

    try {
      return (text ? JSON.parse(text) : {}) as T
    } catch (error) {
      return { raw: text } as T
    }
  }
}
