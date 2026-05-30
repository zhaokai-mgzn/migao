'use client'

import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'
import Button from '@/components/ui/Button'

export interface RemarkModalProps {
  open: boolean
  onClose: () => void
  onConfirm: (content: string) => void
  loading?: boolean
}

export default function RemarkModal({ open, onClose, onConfirm, loading }: RemarkModalProps) {
  const [content, setContent] = useState('')

  // 打开时重置
  useEffect(() => {
    if (open) setContent('')
  }, [open])

  // ESC 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // 背景滚动锁定
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

  const handleConfirm = () => {
    const text = content.trim()
    if (!text) return
    onConfirm(text)
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
            <h3 className="text-lg font-semibold text-gray-900">添加备注</h3>
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
          <div className="px-6 py-5">
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={4}
              placeholder="请输入备注内容"
              className={cn(
                'w-full px-3 py-2 text-sm rounded border border-gray-300 bg-white',
                'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15',
                'resize-none'
              )}
            />
          </div>

          {/* 底部 */}
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200">
            <Button variant="secondary" onClick={onClose} disabled={loading}>
              取消
            </Button>
            <Button onClick={handleConfirm} loading={loading} disabled={!content.trim()}>
              确认
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
