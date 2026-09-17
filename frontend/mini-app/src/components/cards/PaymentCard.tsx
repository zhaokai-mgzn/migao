/**
 * 收款二维码卡片（issue #3990，M3-F-3）
 * 支付页展示：应付金额 + 微信/支付宝收款码（商家自有，扫码直接付给商家，平台不经手资金）+ 上传凭证引导
 */
import { View, Text, Image } from '@tarojs/components'
import { useEffect, useState } from 'react'
import { getPaymentQrcodes } from '../../services/productService'
import './PaymentCard.scss'

interface PaymentQr {
  payment_type?: string
  image_url?: string
  payee_name?: string
}

interface PaymentCardProps {
  /** 归一化后的支付卡载荷：{amount, order_no, payment_qrcodes: {wechat: {...}, alipay: {...}}} */
  data: Record<string, unknown>
}

function formatAmount(amount: number | string | undefined): string {
  if (amount === undefined || amount === null || Number.isNaN(Number(amount))) return ''
  return Number(amount).toFixed(2)
}

export default function PaymentCard({ data }: PaymentCardProps) {
  const [qrcodes, setQrcodes] = useState<Record<string, PaymentQr>>(
    (data.payment_qrcodes || data.paymentQrcodes || {}) as Record<string, PaymentQr>,
  )

  // 数据里没有收款码时自行拉取（AI_API 代理 /chat/payment-qrcodes，issue #3990）
  useEffect(() => {
    let cancelled = false
    if (Object.keys(qrcodes).length === 0) {
      getPaymentQrcodes()
        .then((res) => {
          if (!cancelled && res && Object.keys(res).length > 0) setQrcodes(res)
        })
        .catch(() => {
          // 拉取失败不阻塞展示（保持注入数据或空态）
        })
    }
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const wechat = qrcodes.wechat as PaymentQr | undefined
  const alipay = qrcodes.alipay as PaymentQr | undefined
  const [active, setActive] = useState<'wechat' | 'alipay'>(
    wechat ? 'wechat' : alipay ? 'alipay' : 'wechat',
  )
  const current: PaymentQr | undefined = active === 'wechat' ? wechat : alipay
  const amount = formatAmount(data.amount as number | string | undefined)
  const orderNo = (data.order_no || data.orderNo || '') as string

  return (
    <View className='payment-card'>
      <View className='payment-card__header'>
        <Text className='payment-card__title'>💳 扫码支付</Text>
        {orderNo && <Text className='payment-card__order-no'>{orderNo}</Text>}
      </View>

      {amount && (
        <View className='payment-card__amount-row'>
          <Text className='payment-card__amount-label'>应付金额</Text>
          <Text className='payment-card__amount'>¥{amount}</Text>
        </View>
      )}

      {(wechat || alipay) && (
        <View className='payment-card__tabs'>
          {wechat && (
            <Text
              className={`payment-card__tab${active === 'wechat' ? ' payment-card__tab--active' : ''}`}
              onClick={() => setActive('wechat')}
            >
              微信
            </Text>
          )}
          {alipay && (
            <Text
              className={`payment-card__tab${active === 'alipay' ? ' payment-card__tab--active' : ''}`}
              onClick={() => setActive('alipay')}
            >
              支付宝
            </Text>
          )}
        </View>
      )}

      {current?.image_url ? (
        <>
          <Image className='payment-card__qr' src={current.image_url} mode='aspectFit' />
          {current.payee_name && (
            <Text className='payment-card__payee'>收款方：{current.payee_name}</Text>
          )}
          <Text className='payment-card__note'>
            请保存二维码后扫码支付，款项直接支付给商家；支付完成后请上传支付凭证，商家确认后为您安排生产
          </Text>
        </>
      ) : (
        <Text className='payment-card__note'>商家暂未设置收款码，请联系客服获取收款方式</Text>
      )}
    </View>
  )
}
