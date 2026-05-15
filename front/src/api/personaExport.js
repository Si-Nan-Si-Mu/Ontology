import { apiUrl } from './http.js'

/**
 * 下载按 subject_id 聚合的人格子图导出（JSON 或纯文本）。
 * @param {string} subjectId Person.subject_id
 * @param {'json' | 'text'} format
 */
export async function downloadPersonaExport(subjectId, format) {
  const sid = (subjectId || '').trim()
  if (!sid) throw new Error('缺少 subject_id')
  const q = format === 'text' ? 'text' : 'json'
  const url = apiUrl(`/api/v1/person/${encodeURIComponent(sid)}/persona-export?format=${q}`)
  const res = await fetch(url)
  if (!res.ok) {
    const t = await res.text()
    throw new Error(`${res.status}: ${t.slice(0, 200)}`)
  }
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') || ''
  let name = q === 'text' ? 'persona.txt' : 'persona.json'
  const star = /filename\*=UTF-8''([^;\s]+)/i.exec(cd)
  if (star) {
    try {
      name = decodeURIComponent(star[1])
    } catch {
      /* keep default */
    }
  } else {
    const plain = /filename="([^"]+)"/i.exec(cd)
    if (plain) name = plain[1]
  }
  const a = document.createElement('a')
  const href = URL.createObjectURL(blob)
  a.href = href
  a.download = name
  a.click()
  URL.revokeObjectURL(href)
}
