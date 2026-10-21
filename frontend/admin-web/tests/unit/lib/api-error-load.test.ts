// case_ids: OPS-001
import { describe, expect, it } from 'vitest'
import { loadErrorMessage } from '@/lib/api-error'

/**
 * 常驻失败态文案（issue #7373 复盘）：服务端原文优先 + 状态码可核对 + 兜底仍是人话。
 *
 * 与 `extractApiErrorMessage` 的分工：那个用于登录/改密（必须逐字透传、不得改写）；
 * 这个用于列表失败卡片（会一直挂在屏幕上，所以要补「该找谁 / 该做什么」）。
 */
describe('loadErrorMessage', () => {
  const axiosLike = (status: number, error?: Record<string, unknown>) => ({
    isAxiosError: true,
    response: { status, data: error ? { error } : {} },
  })

  it('服务端有 message ⇒ 原样转述（不改写业务文案，也不加协议字样）', () => {
    const text = loadErrorMessage(axiosLike(400, { message: '供应商名称不能为空' }), '供应商加载失败')
    expect(text).toContain('供应商名称不能为空')
  })

  it('500 且服务端无原因 ⇒ 说清「系统出了点问题」（不是「请重试」一句了事）', () => {
    const text = loadErrorMessage(axiosLike(500), '采购单加载失败')
    expect(text).toContain('系统出了点问题')
    expect(text).toContain('技术支持')
  })

  it('🔴 传输层技术语言不上屏（`Request failed with status code` 不许出现在界面）', () => {
    const axiosError = {
      isAxiosError: true,
      message: 'Request failed with status code 500',
      response: { status: 500, data: {} },
    }
    const text = loadErrorMessage(axiosError, '采购单加载失败')
    expect(text).not.toContain('Request failed')
    // 协议细节同样不上屏（issue #6488 R1）：只说处境，不说 HTTP 码
    expect(text).not.toContain('HTTP')
    expect(text).toContain('系统出了点问题')
  })

  it('403 ⇒ 说清找管理员；401 ⇒ 说清重新登录', () => {
    expect(loadErrorMessage(axiosLike(403), '采购单加载失败')).toContain('没有查看权限')
    expect(loadErrorMessage(axiosLike(401), '采购单加载失败')).toContain('重新登录')
  })

  it('断网（没到服务端）⇒ 说网络，不冒充服务端错误', () => {
    const text = loadErrorMessage({ isAxiosError: true, request: {} }, '采购单加载失败')
    expect(text).toContain('网络连不上')
  })

  it('拿不到任何结构 ⇒ 退回本页兜底句（不抛、不留空）', () => {
    expect(loadErrorMessage(null, '供应商加载失败')).toBe('供应商加载失败')
  })
})
