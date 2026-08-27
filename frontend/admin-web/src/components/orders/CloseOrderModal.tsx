'use client'

import { useEffect, useState } from 'react'
import { X, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'
import Button from '@/components/ui/Button'

export interface CloseOrderModalProps {
  open: boolean
  onClose: () => void
  onConfirm: (reason: string) => void
  loading?: boolean
}

const PRESET_REASONS = ['缺货', '过期未付款', '协商一致']
const OTHER_KEY = '备注其它原因'

export default function CloseOrderModal({ open, onClose, onConfirm, loading }: CloseOrderModalProps) {
  const [selected, setSelected] = useState<string>(PRESET_REASONS[0])
  const [otherText, setOtherText] = useState('')

  // 重置状态
  useEffect(() => {
    if (open) {
      setSelected(PRESET_REASONS[0])
      setOtherText('')
    }
  }, [open])

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

  const isOther = selected === OTHER_KEY

  const handleConfirm = () => {
    const reason = isOther ? otherText.trim() : selected
    if (!reason) return
    onConfirm(reason)
  }

  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0 bg-black/45 transition-opacity"
        onClick={loading ? undefined : onClose}
      />
      <div className="absolute inset-0 flex items-center justify-center p-4 overflow-y-auto">
        <div
          className="relative bg-white rounded-lg shadow-xl w-full max-w-[480px] animate-in fade-in zoom-in-95 duration-200"
          onClick={(e) => e.stopPropagation()}
        >
          {/* 标题 */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
            <h3 className="text-lg font-semibold text-gray-900">关闭订单</h3>
            <button
              type="button"
              onClick={onClose}
              disabled={loading}
              className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors disabled:opacity-50"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* 警告区 */}
          <div className="px-6 pt-5">
            <div className="flex items-start gap-2 mb-5">
              <AlertTriangle className="w-5 h-5 text-amber-500 mt-0.5 flex-shrink-0" />
              <p className="text-sm text-gray-700 leading-relaxed">
                确定关闭当前订单吗？关闭订单不可恢复。
              </p>
            </div>

            {/* 关闭原因 */}
            <div className="mb-2">
              <div className="text-sm text-gray-700 mb-3">关闭原因</div>
              <div className="space-y-2.5">
                {PRESET_REASONS.map((reason) => (
                  <label
                    key={reason}
                    className="flex items-center gap-2 cursor-pointer text-sm text-gray-700"
                  >
                    <input
                      type="radio"
                      name="close-reason"
                      value={reason}
                      checked={selected === reason}
                      onChange={() => setSelected(reason)}
                      className="w-4 h-4 border-gray-300 text-primary-600 focus:ring-primary-500"
                    />
                    {reason}
                  </label>
                ))}
                <label
                  className="flex items-center gap-2 cursor-pointer text-sm text-gray-700"
                >
                  <input
                    type="radio"
                    name="close-reason"
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
                    placeholder="请输入关闭原因"
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
            <Button
              onClick={handleConfirm}
              loading={loading}
              disabled={isOther && !otherText.trim()}
            >
              确定
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
