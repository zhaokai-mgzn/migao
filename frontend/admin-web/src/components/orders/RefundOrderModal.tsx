'use client'

import { useEffect, useState } from 'react'
import { X, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import Button from '@/components/ui/Button'
import type { Order } from '@/types'

export interface RefundOrderModalProps {
  open: boolean
  onClose: () => void
  onConfirm: (data: { refundAmount: number; refundReason: string }) => void
  loading?: boolean
  order?: Order | null
}

const PRESET_REASONS = ['质量问题', '客户退货', '协商一致']
const OTHER_KEY = '其它原因'

/**
 * 退款弹窗 — 输入退款金额（默认=实收）和退款原因。
 * 提交后调用后端 PUT /api/admin/orders/{id}/refund（由调用方处理）。
 */
export default function RefundOrderModal({ open, onClose, onConfirm, loading, order }: RefundOrderModalProps) {
  const [amountText, setAmountText] = useState<string>('')
  const [selected, setSelected] = useState<string>(PRESET_REASONS[0])
  const [otherText, setOtherText] = useState('')

  // 打开时重置为默认值（默认退款金额 = 实收）
  useEffect(() => {
    if (open) {
      const def = order?.actualAmount ?? 0
      setAmountText(def > 0 ? String(def) : '')
      setSelected(PRESET_REASONS[0])
      setOtherText('')
    }
  }, [open, order?.actualAmount])

  // ESC 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // 锁定背景滚动
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => {
      document.body.style.overflow = ''
    }
  }, [open])

  if (!open) return null

  const amount = parseFloat(amountText)
  const amountValid = !Number.isNaN(amount) && amount > 0
  const isOther = selected === OTHER_KEY
  const reason = isOther ? otherText.trim() : selected

  const handleConfirm = () => {
    if (!amountValid) return
    onConfirm({ refundAmount: amount, refundReason: reason || '退款' })
  }

  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0 bg-black/45 transition-opacity"
        onClick={loading ? undefined : onClose}
      />
      <div className="absolute inset-0 flex items-center justify-center p-4 overflow-y-auto">
        <div
          role="dialog"
          aria-modal="true"
          aria-label="处理退款"
          className="relative bg-white rounded-lg shadow-xl w-full max-w-[480px] animate-in fade-in zoom-in-95 duration-200"
          onClick={(e) => e.stopPropagation()}
        >
          {/* 标题 */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
            <h3 className="text-lg font-semibold text-gray-900">处理退款</h3>
            <button
              type="button"
              onClick={onClose}
              disabled={loading}
              className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors disabled:opacity-50"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* 内容 */}
          <div className="px-6 pt-5">
            <div className="flex items-start gap-2 mb-5">
              <AlertTriangle className="w-5 h-5 text-amber-500 mt-0.5 flex-shrink-0" />
              <p className="text-sm text-gray-700 leading-relaxed">
                退款订单：{order?.orderNo || '-'}。退款后订单保持原状态，退款金额记录在订单上。
              </p>
            </div>

            {/* 退款金额 */}
            <div className="mb-5">
              <label htmlFor="refund-amount" className="block text-sm text-gray-700 mb-2">
                退款金额
              </label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">¥</span>
                <input
                  id="refund-amount"
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={amountText}
                  onChange={(e) => setAmountText(e.target.value)}
                  placeholder="请输入退款金额"
                  className={cn(
                    'w-full pl-7 pr-3 h-10 text-sm rounded border border-gray-300 bg-white',
                    'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15'
                  )}
                />
              </div>
              {order?.actualAmount ? (
                <p className="text-xs text-gray-400 mt-1.5">默认退款金额 = 实收款 ¥{order.actualAmount}</p>
              ) : null}
            </div>

            {/* 退款原因 */}
            <div className="mb-2">
              <div className="text-sm text-gray-700 mb-3">退款原因</div>
              <div className="space-y-2.5">
                {PRESET_REASONS.map((reason) => (
                  <label
                    key={reason}
                    className="flex items-center gap-2 cursor-pointer text-sm text-gray-700"
                  >
                    <input
                      type="radio"
                      name="refund-reason"
                      value={reason}
                      checked={selected === reason}
                      onChange={() => setSelected(reason)}
                      className="w-4 h-4 border-gray-300 text-primary-600 focus:ring-primary-500"
                    />
                    {reason}
                  </label>
                ))}
                <label className="flex items-center gap-2 cursor-pointer text-sm text-gray-700">
                  <input
                    type="radio"
                    name="refund-reason"
                    value={OTHER_KEY}
                    checked={isOther}
                    onChange={() => setSelected(OTHER_KEY)}
                    className="w-4 h-4 border-gray-300 text-primary-600 focus:ring-primary-500"
                  />
                  {OTHER_KEY}
                </label>
                {isOther && (
                  <textarea
                    value={otherText}
                    onChange={(e) => setOtherText(e.target.value)}
                    rows={3}
                    placeholder="请输入退款原因"
                    className={cn(
                      'mt-2 w-full px-3 py-2 text-sm rounded border border-gray-300 bg-white',
                      'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15',
                      'resize-none'
                    )}
                  />
                )}
              </div>
            </div>
          </div>

          {/* 底部 */}
          <div className="flex items-center justify-end gap-3 px-6 py-4 mt-2 border-t border-gray-200">
            <Button variant="secondary" onClick={onClose} disabled={loading}>
              取消
            </Button>
            <Button onClick={handleConfirm} loading={loading} disabled={!amountValid}>
              确定
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
