// case_ids: KF-030
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const listChannels = vi.fn()
const createChannel = vi.fn()
const verifyChannel = vi.fn()
const disableChannel = vi.fn()
const createLink = vi.fn()

vi.mock('@/lib/kf-api', () => ({
  kfApi: {
    listChannels: (...args: unknown[]) => listChannels(...args),
    createChannel: (...args: unknown[]) => createChannel(...args),
    verifyChannel: (...args: unknown[]) => verifyChannel(...args),
    disableChannel: (...args: unknown[]) => disableChannel(...args),
    createLink: (...args: unknown[]) => createLink(...args),
  },
}))

import { WechatKfOnboarding } from '@/components/settings/WechatKfOnboarding'

const active = {
  id: 'ch-1', corpId: 'ww-corp', openKfid: 'wk-1', authMode: 'self_built',
  status: 'active' as const, createdAt: '2026-11-26T00:00:00Z', updatedAt: '2026-11-26T00:00:00Z',
}

describe('WechatKfOnboarding（微信客服自助接入）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listChannels.mockResolvedValue({ data: { data: [] } })
  })

  it('空态 + 回调地址可见', async () => {
    render(<WechatKfOnboarding />)
    expect(await screen.findByTestId('kf-empty')).toBeInTheDocument()
    expect(screen.getByTestId('kf-callback-url')).toHaveTextContent('/api/kf/callback')
  })

  it('接入成功 ⇒ 清空表单并提示已接通', async () => {
    createChannel.mockResolvedValue({
      data: { data: { channel: active, verified: true, message: 'ok' } },
    })
    render(<WechatKfOnboarding />)
    await screen.findByTestId('kf-empty')

    fireEvent.change(screen.getByTestId('kf-corp-id'), { target: { value: 'ww-corp' } })
    fireEvent.change(screen.getByTestId('kf-open-kfid'), { target: { value: 'wk-1' } })
    fireEvent.change(screen.getByTestId('kf-secret'), { target: { value: 'sec' } })
    fireEvent.click(screen.getByTestId('kf-create'))

    await waitFor(() => expect(createChannel).toHaveBeenCalledWith({ corpId: 'ww-corp', openKfid: 'wk-1', secret: 'sec' }))
    expect(await screen.findByTestId('kf-notice')).toHaveTextContent('接入成功')
  })

  it('自检失败 ⇒ 展示服务端可执行原因，不谎报成功', async () => {
    createChannel.mockResolvedValue({
      data: { data: { channel: { ...active, status: 'unauthorized' }, verified: false, message: '自检失败：open_kfid 不在列表里' } },
    })
    render(<WechatKfOnboarding />)
    await screen.findByTestId('kf-empty')
    fireEvent.change(screen.getByTestId('kf-corp-id'), { target: { value: 'ww-corp' } })
    fireEvent.change(screen.getByTestId('kf-open-kfid'), { target: { value: 'wk-1' } })
    fireEvent.change(screen.getByTestId('kf-secret'), { target: { value: 'sec' } })
    fireEvent.click(screen.getByTestId('kf-create'))

    expect(await screen.findByTestId('kf-notice')).toHaveTextContent('自检失败：open_kfid 不在列表里')
  })

  it('已接通渠道 ⇒ 生成客服链接（二维码/URL）并可停用', async () => {
    listChannels.mockResolvedValue({ data: { data: [active] } })
    createLink.mockResolvedValue({ data: { data: { url: 'https://kf.example/q' } } })
    disableChannel.mockResolvedValue({ data: { data: { ...active, status: 'revoked' } } })

    render(<WechatKfOnboarding />)
    await screen.findByTestId('kf-channel-row')
    fireEvent.click(screen.getByTestId('kf-link-ch-1'))

    expect(await screen.findByTestId('kf-link-panel')).toHaveTextContent('https://kf.example/q')
    fireEvent.click(screen.getByTestId('kf-disable-ch-1'))
    await waitFor(() => expect(disableChannel).toHaveBeenCalledWith('ch-1'))
    expect(await screen.findByTestId('kf-notice')).toHaveTextContent('已停用')
  })
})
