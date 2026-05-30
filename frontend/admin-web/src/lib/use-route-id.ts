'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'

/**
 * 在 Next.js 静态导出 + CDN 回写场景下，useParams() 返回的是预渲染时的占位
 * 值（'_'），并不是 URL 中真实的动态段。该 hook 在客户端从
 * window.location.pathname 解析真实 ID，避免以 `_` 作为参数发起 API 请求。
 *
 * 路由形如 /products/{id}/、/orders/{id}/、/products/{id}/edit/ 等：
 * - 默认取过滤后路径段的倒数第一段；
 * - 若该段是已知后缀（如 'edit'），则向前回退一段。
 */
const KNOWN_SUFFIX_SEGMENTS = new Set(['edit', 'new', 'create', 'ship'])

function extractIdFromPathname(pathname: string): string {
  const segments = pathname.split('/').filter(Boolean)
  if (segments.length === 0) return ''
  let idx = segments.length - 1
  while (idx >= 0 && KNOWN_SUFFIX_SEGMENTS.has(segments[idx])) {
    idx -= 1
  }
  return idx >= 0 ? segments[idx] : ''
}

export function useRouteId(paramKey: string = 'id'): string {
  const params = useParams()
  const initial = (() => {
    const raw = params?.[paramKey]
    const value = Array.isArray(raw) ? raw[0] : raw
    return typeof value === 'string' && value !== '_' ? value : ''
  })()

  const [routeId, setRouteId] = useState<string>(initial)

  useEffect(() => {
    if (typeof window === 'undefined') return
    const fromUrl = extractIdFromPathname(window.location.pathname)
    if (fromUrl && fromUrl !== '_') {
      setRouteId(fromUrl)
      return
    }
    const raw = params?.[paramKey]
    const value = Array.isArray(raw) ? raw[0] : raw
    if (typeof value === 'string' && value !== '_') {
      setRouteId(value)
    }
  }, [params, paramKey])

  return routeId
}
