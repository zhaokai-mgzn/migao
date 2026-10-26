// case_ids: UI-064
/**
 * 手机端入口（issue #7198；原落位 issue #5668）—— **顶栏图标 + 按需弹层**，全站唯一入口。
 *
 * ## 为什么在顶栏（用户 2026-10-18 逐字「需要有个更好的位置让用户方便扫码」）
 *
 * 旧形态：一张 112px 二维码大块埋在「企业基础设置 → 企业信息」域中部，扫码要走 3~4 步。
 * 2026-10-18 二次改判（issue #7212，用户逐字「这块直接移除吧，已经迁移到右上角了」）：
 * 设置页那一行**也移除** ⇒ 扫码入口只剩顶栏右上角（任何页面一键弹码）。
 * 二维码**只由 `MobileEntryPanel` 渲染一处**。
 *
 * ## 判据（每条都能单独变红）
 *
 * 1. **默认收起**：顶栏入口在展开前不渲染二维码（`bmini-h5-qr` 取不到）—— 常驻面克制（§31 P1）。
 * 2. **内容逐字等于配置值**：哨兵地址（非线上域名）⇒ 二维码 `<title>` 与可复制链接逐字相等
 *    （硬编码线上地址必红）。
 * 3. **点击外部收起**：弹层不是"打开就关不掉"的常驻块。
 * 4. **未配置不画假码**：`NEXT_PUBLIC_BMINI_H5_URL` 为空时**零 svg**，逐字说明「未配置」。
 * 5. **纯图标按钮可读**：顶栏按钮必须有 `aria-label`（`ui-button-standard.md`：纯图标按钮必须可读）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockToastSuccess = vi.fn()
const mockToastError = vi.fn()
vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}))

import MobileEntryHeader from '@/components/layout/MobileEntry'

// 票据签发端点（issue #7825）：默认成功；具体用例逐格覆盖
const { mockPost } = vi.hoisted(() => ({ mockPost: vi.fn() }))
vi.mock('@/lib/request', () => ({ default: { post: mockPost } }))

const SENTINEL_URL = 'https://bmini-entry.invalid/b/'

const writeText = vi.fn<(value: string) => Promise<void>>()

beforeEach(() => {
  vi.clearAllMocks()
  mockPost.mockResolvedValue({ success: true, data: { ticket: 'ticket-from-server', expiresIn: 120 } })
  vi.stubEnv('NEXT_PUBLIC_BMINI_H5_URL', SENTINEL_URL)
  writeText.mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
  })
})

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('MobileEntryHeader —— 顶栏主入口（跨设备交接是个工具，不是一条配置）', () => {
  it('默认收起：按钮可读（纯图标按钮必须有 aria-label），展开前**不渲染**二维码', () => {
    render(<MobileEntryHeader />)
    expect(screen.getByRole('button', { name: '手机端入口' })).toBeInTheDocument()
    expect(screen.queryByTestId('bmini-h5-qr')).toBeNull()
  })

  it('点击 ⇒ 展开弹层：二维码 = 配置地址 + 一次性票据；可见地址仍是裸地址（哨兵值 ⇒ 硬编码必红）', async () => {
    render(<MobileEntryHeader />)
    fireEvent.click(screen.getByRole('button', { name: '手机端入口' }))
    const qr = await screen.findByTestId('bmini-h5-qr')
    // 二维码内容 = 单一真值地址 + `?qr=<票据>`（issue #7825 扫码即登录）
    expect(qr.querySelector('title')?.textContent).toBe(`${SENTINEL_URL}?qr=ticket-from-server`)
    // 可见的地址块**不带票据**（短期凭证只在码里）
    expect(screen.getByTestId('bmini-h5-url')).toHaveTextContent(SENTINEL_URL)
    expect(mockPost).toHaveBeenCalledWith('/api/auth/qr/ticket')
  })

  it('票据倒计时上屏（服务端 expiresIn 驱动，不自己拍脑袋）', async () => {
    render(<MobileEntryHeader />)
    fireEvent.click(screen.getByRole('button', { name: '手机端入口' }))
    const ttl = await screen.findByTestId('bmini-h5-qr-ttl')
    expect(ttl).toHaveTextContent('扫码免登录')
    expect(ttl).toHaveTextContent('2:00')
  })

  it('签发失败 ⇒ 降级为裸入口（不画」扫了没用」的码）+ 明说扫码后登录', async () => {
    mockPost.mockRejectedValueOnce(new Error('boom'))
    render(<MobileEntryHeader />)
    fireEvent.click(screen.getByRole('button', { name: '手机端入口' }))
    const qr = await screen.findByTestId('bmini-h5-qr')
    expect(qr.querySelector('title')?.textContent).toBe(SENTINEL_URL)
    expect(await screen.findByTestId('bmini-h5-qr-fallback')).toHaveTextContent('扫码后在手机上登录')
  })

  it('票据过期 ⇒ 自动换新码（不要求用户点刷新）', async () => {
    mockPost
      .mockResolvedValueOnce({ success: true, data: { ticket: 'ticket-old', expiresIn: 1 } })
      .mockResolvedValueOnce({ success: true, data: { ticket: 'ticket-new', expiresIn: 120 } })

    render(<MobileEntryHeader />)
    fireEvent.click(screen.getByRole('button', { name: '手机端入口' }))
    const qr = await screen.findByTestId('bmini-h5-qr')
    expect(qr.querySelector('title')?.textContent).toBe(`${SENTINEL_URL}?qr=ticket-old`)

    // 倒计时走到 0 ⇒ 触发第二次签发
    await waitFor(
      () => expect(qr.querySelector('title')?.textContent).toBe(`${SENTINEL_URL}?qr=ticket-new`),
      { timeout: 4000 },
    )
    expect(mockPost).toHaveBeenCalledTimes(2)
  })

  it('点击外部 ⇒ 收起（不是「打开就关不掉」的常驻块）', async () => {
    render(
      <div>
        <MobileEntryHeader />
        <button type="button">外部</button>
      </div>,
    )
    fireEvent.click(screen.getByRole('button', { name: '手机端入口' }))
    expect(await screen.findByTestId('bmini-h5-qr')).toBeInTheDocument()

    fireEvent.mouseDown(screen.getByRole('button', { name: '外部' }))
    expect(screen.queryByTestId('bmini-h5-qr')).toBeNull()
  })

  it('未配置 ⇒ 不画假码：零 svg + 逐字说明「未配置」', async () => {
    vi.stubEnv('NEXT_PUBLIC_BMINI_H5_URL', '')
    render(<MobileEntryHeader />)
    fireEvent.click(screen.getByRole('button', { name: '手机端入口' }))
    const note = await screen.findByTestId('bmini-h5-unconfigured')
    expect(note).toHaveTextContent('尚未开通手机版')
    expect(screen.queryByTestId('bmini-h5-qr')).toBeNull()
    expect(note.querySelector('svg')).toBeNull()
  })
  it('点「复制链接」⇒ 复制的是**配置值**（不是硬编码地址）+ 成功提示', async () => {
    render(<MobileEntryHeader />)
    fireEvent.click(screen.getByRole('button', { name: '手机端入口' }))
    fireEvent.click(await screen.findByRole('button', { name: '复制链接' }))
    expect(writeText).toHaveBeenCalledWith(SENTINEL_URL)
    await waitFor(() => expect(mockToastSuccess).toHaveBeenCalledWith('链接已复制'))
  })
})
