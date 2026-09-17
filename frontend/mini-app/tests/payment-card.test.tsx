/**
 * 收款二维码卡片测试（issue #3990，M3-F-3）
 *
 * 覆盖：金额展示、微信/支付宝切换、收款方与提示（款项直接支付给商家）、
 * 无收款码时降级提示；数据无码时自取 /chat/payment-qrcodes。
 */
// case_ids: ST-011
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import PaymentCard from '../src/components/cards/PaymentCard'
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
