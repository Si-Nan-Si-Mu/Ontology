/**
 * API 基址：生产/直连后端时设置 VITE_API_ORIGIN（如 http://127.0.0.1:8000）。
 * 开发环境留空则走 Vite 代理（同源 /api、/docs 等）。
 */
const configuredOrigin = (import.meta.env.VITE_API_ORIGIN || '').replace(/\/$/, '')

export function apiUrl(path) {
  const p = path.startsWith('/') ? path : `/${path}`
  if (configuredOrigin) return `${configuredOrigin}${p}`
  return p
}

/** 浏览器中展示文档、OpenAPI 等链接用的「对外可见」基址 */
export function publicApiBase() {
  if (configuredOrigin) return configuredOrigin
  if (typeof window !== 'undefined') return window.location.origin
  return ''
}

export async function apiFetch(path, options = {}) {
  const { headers: extraHeaders, signal, ...rest } = options
  const res = await fetch(apiUrl(path), {
    ...rest,
    signal,
    headers: {
      Accept: 'application/json',
      ...extraHeaders,
    },
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text.slice(0, 200)}`)
  }
  const ct = res.headers.get('content-type')
  if (ct?.includes('application/json')) return res.json()
  return res.text()
}
