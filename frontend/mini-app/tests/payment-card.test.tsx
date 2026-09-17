/**
 * 收款二维码卡片测试（issue #3990，M3-F-3；issue #4085 第 1 项补发射点）
 *
 * 覆盖：金额展示、微信/支付宝切换、收款方与提示（款项直接支付给商家）、
 * 无收款码时降级提示；数据无码时自取 /chat/payment-qrcodes；
 * **对话内可达**（MessageBubble 的 `case 'payment'` 渲染分支 → 本地真组件）。
 */
// case_ids: ST-011, ST-012
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import PaymentCard from '../src/components/cards/PaymentCard'
import MessageBubble from '../src/components/chat/MessageBubble'
import { getPaymentQrcodes } from '../src/services/productService'

jest.mock('../src/services/productService', () => ({
  getPaymentQrcodes: jest.fn(),
}))

const mockGetPaymentQrcodes = getPaymentQrcodes as jest.Mock

describe('PaymentCard', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('应展示金额、收款码与收款方（款项直接支付给商家）', async () => {
    mockGetPaymentQrcodes.mockResolvedValue({})
    render(
      <PaymentCard
        data={{
          order_no: 'ORD-P001',
          amount: 129.8,
          payment_qrcodes: {
            wechat: { payment_type: 'wechat', image_url: 'https://img/w.png', payee_name: '亿家纺织' },
            alipay: { payment_type: 'alipay', image_url: 'https://img/a.png', payee_name: '亿家纺织' },
          },
        }}
      />,
    )
    expect(screen.getByText(/129\.80/)).toBeTruthy()
    expect(screen.getByText(/亿家纺织/)).toBeTruthy()
    expect(screen.getByText(/款项直接支付给商家/)).toBeTruthy()
    expect(screen.getByText('微信')).toBeTruthy()
    expect(screen.getByText('支付宝')).toBeTruthy()
  })

  it('数据无码时自取 /chat/payment-qrcodes', async () => {
    mockGetPaymentQrcodes.mockResolvedValue({
      wechat: { image_url: 'https://img/w.png', payee_name: '亿家纺织' },
    })
    render(<PaymentCard data={{ amount: 88.0 }} />)
    await waitFor(() => {
      expect(mockGetPaymentQrcodes).toHaveBeenCalled()
    })
    expect(await screen.findByText(/亿家纺织/)).toBeTruthy()
  })

  it('无收款码时展示降级提示', async () => {
    mockGetPaymentQrcodes.mockResolvedValue({})
    render(<PaymentCard data={{ amount: 88.0 }} />)
    expect(await screen.findByText(/暂未设置收款码/)).toBeTruthy()
  })
})

/**
 * 对话内可达（issue #4085 第 1 项）——这条链的**最后一跳**。
 *
 * 病根：PaymentCard 组件一直在、后端 `_detect_card_type` 从来没有 `payment` 发射点、
 * MessageBubble 的 `case 'payment'` 又被 #4016 P14 裁掉 ⇒「交付物在 main ≠ 能力可达」。
 * 本组测试对**真组件**求值（不 mock PaymentCard）：后端下发卡型 `payment` 时，
 * 气泡里必须真的出现收款码内容（有码）或空态提示（无码）——而不是落进
 * default 的「📎 消息内容暂不支持预览」占位灰盒。
 */
describe('MessageBubble 的 payment 卡型渲染分支（issue #4085）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  const bubbleMsg = (data: Record<string, unknown>) => ({
    id: 'm-pay-1',
    role: 'assistant' as const,
    content: '您可以扫码直接付给商家～',
    created_at: new Date().toISOString(),
    cards: [{ type: 'payment', data }],
  })

  it('卡型 payment → 渲染收款码与收款方（不是"暂不支持预览"占位）', async () => {
    mockGetPaymentQrcodes.mockResolvedValue({})
    render(
      <MessageBubble
        message={
          bubbleMsg({
            payment_qrcodes: {
              wechat: { payment_type: 'wechat', image_url: 'https://img/w.png', payee_name: '亿家纺织' },
            },
          }) as any
        }
      />,
    )
    // 「扫码支付」在卡片标题与付款说明里各出现一次 ⇒ 用 getAllByText（内容可见即可）
    expect(screen.getAllByText(/扫码支付/).length).toBeGreaterThan(0)
    expect(screen.getByText(/亿家纺织/)).toBeTruthy()
    expect(screen.queryByText(/暂不支持预览/)).toBeNull()
  })

  it('空 payment_qrcodes → 走空态提示（ST-011「无收款码时展示降级提示」）', async () => {
    mockGetPaymentQrcodes.mockResolvedValue({})
    render(<MessageBubble message={bubbleMsg({ payment_qrcodes: {} }) as any} />)
    expect(await screen.findByText(/暂未设置收款码/)).toBeTruthy()
    expect(screen.queryByText(/暂不支持预览/)).toBeNull()
  })
})
