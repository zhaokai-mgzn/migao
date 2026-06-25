import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cn, resolveImageUrl } from '@/lib/utils'

// ────────────────────────────────────────────
// resolveImageUrl
// ────────────────────────────────────────────

const OSS_DOMAIN = 'https://youke-admin-dev.oss-cn-hangzhou.aliyuncs.com'
const API_BASE = 'https://api.migaozn.com'

describe('resolveImageUrl', () => {
  beforeEach(() => {
    vi.stubEnv('NEXT_PUBLIC_OSS_DOMAIN', OSS_DOMAIN)
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', API_BASE)
  })
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  // ── 空值 / 非字符串 ──
  it('returns empty string for null/undefined/empty', () => {
    expect(resolveImageUrl(null)).toBe('')
    expect(resolveImageUrl(undefined)).toBe('')
    expect(resolveImageUrl('')).toBe('')
    expect(resolveImageUrl('   ')).toBe('')
  })

  // ── data: / blob: 透传 ──
  it('passes through data: and blob: URLs', () => {
    expect(resolveImageUrl('data:image/png;base64,abc')).toBe('data:image/png;base64,abc')
    expect(resolveImageUrl('blob:http://localhost/123')).toBe('blob:http://localhost/123')
  })

  // ── 已匹配 OSS 域名的完整 URL 直接返回 ──
  it('returns matching OSS URL unchanged', () => {
    const url = `${OSS_DOMAIN}/products/2026/06/01/abc.jpg`
    expect(resolveImageUrl(url)).toBe(url)
  })

  // ── 核心场景：错误域名 → 提取 path 用 OSS 域名重建 ──
  it('normalizes CDN domain (merchant.migaozn.com) to OSS domain', () => {
    expect(resolveImageUrl('https://merchant.migaozn.com/products/2026/06/01/abc.jpg'))
      .toBe(`${OSS_DOMAIN}/products/2026/06/01/abc.jpg`)
  })

  it('normalizes old bucket domain (mgzn-admin) to current OSS domain', () => {
    expect(resolveImageUrl('https://mgzn-admin.oss-cn-hangzhou.aliyuncs.com/products/abc.jpg'))
      .toBe(`${OSS_DOMAIN}/products/abc.jpg`)
  })

  it('normalizes old project bucket domain to current OSS domain', () => {
    expect(resolveImageUrl('https://ai-customer-service-admin-dev.oss-cn-hangzhou.aliyuncs.com/products/abc.jpg'))
      .toBe(`${OSS_DOMAIN}/products/abc.jpg`)
  })

  it('preserves query string when normalizing', () => {
    expect(resolveImageUrl('https://merchant.migaozn.com/products/abc.jpg?x-oss-process=resize'))
      .toBe(`${OSS_DOMAIN}/products/abc.jpg?x-oss-process=resize`)
  })

  // ── 绝对路径（/api/files/...）拼接 API base ──
  it('prepends API base URL for absolute paths', () => {
    expect(resolveImageUrl('/api/files/static/products/abc.jpg'))
      .toBe(`${API_BASE}/api/files/static/products/abc.jpg`)
  })

  // ── 裸 object key 拼接 OSS 域名 ──
  it('prepends OSS domain for bare object keys', () => {
    expect(resolveImageUrl('products/2026/06/01/abc.jpg'))
      .toBe(`${OSS_DOMAIN}/products/2026/06/01/abc.jpg`)
  })

  // ── 协议相对 URL 直接返回 ──
  it('returns protocol-relative URLs unchanged', () => {
    expect(resolveImageUrl('//example.com/img.jpg')).toBe('//example.com/img.jpg')
  })

  // ── OSS 域名为空时的降级行为 ──
  it('falls back to API base URL when OSS domain is empty', () => {
    vi.stubEnv('NEXT_PUBLIC_OSS_DOMAIN', '')
    expect(resolveImageUrl('products/abc.jpg'))
      .toBe(`${API_BASE}/products/abc.jpg`)
  })

  // ── 未知 HTTPS 域名也做规范化 ──
  it('normalizes unknown HTTPS domain to OSS domain', () => {
    expect(resolveImageUrl('https://some-random-cdn.com/images/product.jpg'))
      .toBe(`${OSS_DOMAIN}/images/product.jpg`)
  })
})

describe('cn (classnames utility)', () => {
  it('should merge single class string', () => {
    expect(cn('text-red-500')).toBe('text-red-500')
  })

  it('should merge multiple class strings', () => {
    expect(cn('text-red-500', 'bg-blue-500')).toBe('text-red-500 bg-blue-500')
  })

  it('should handle conditional classes', () => {
    expect(cn('base', false && 'hidden', 'visible')).toBe('base visible')
  })

  it('should handle undefined and null values', () => {
    expect(cn('base', undefined, null, 'end')).toBe('base end')
  })

  it('should handle empty string', () => {
    expect(cn('')).toBe('')
  })

  it('should handle no arguments', () => {
    expect(cn()).toBe('')
  })

  it('should merge conflicting Tailwind classes (last wins)', () => {
    expect(cn('text-red-500', 'text-blue-500')).toBe('text-blue-500')
  })

  it('should merge conflicting padding classes', () => {
    expect(cn('p-4', 'p-2')).toBe('p-2')
  })

  it('should handle object syntax from clsx', () => {
    expect(cn({ 'text-red-500': true, 'bg-blue-500': false })).toBe('text-red-500')
  })

  it('should handle array syntax', () => {
    expect(cn(['text-red-500', 'bg-blue-500'])).toBe('text-red-500 bg-blue-500')
  })

  it('should handle mixed types', () => {
    const result = cn('base', { active: true, disabled: false }, ['extra'])
    expect(result).toBe('base active extra')
  })
})
