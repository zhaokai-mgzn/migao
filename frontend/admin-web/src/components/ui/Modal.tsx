'use client'

import { cn } from '@/lib/utils'
import { X } from 'lucide-react'
import { useEffect } from 'react'
import Button from './Button'

interface ModalProps {
  open: boolean
  onClose: () => void
  title?: string
  children: React.ReactNode
  footer?: React.ReactNode
  width?: string | number
  closable?: boolean
  maskClosable?: boolean
  destroyOnClose?: boolean
}

const Modal = ({
  open,
  onClose,
  title,
  children,
  footer,
  width = 520,
  closable = true,
  maskClosable = true,
}: ModalProps) => {
  // 处理 ESC 键关闭
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) {
        onClose()
      }
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [open, onClose])

  // 阻止背景滚动
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

  const widthStyle = typeof width === 'number' ? `${width}px` : width

  return (
    <div className="fixed inset-0 z-50">
      {/* 遮罩层 */}
      <div
        className="absolute inset-0 bg-black/45 transition-opacity"
        onClick={maskClosable ? onClose : undefined}
      />

      {/* 模态框 */}
      <div className="absolute inset-0 flex items-center justify-center p-4 overflow-y-auto">
        <div
          role="dialog"
          aria-modal="true"
          aria-label={title || '对话框'}
          className="relative bg-white rounded-2xl shadow-modal w-full max-h-full flex flex-col animate-in fade-in zoom-in-95 duration-200"
          style={{ maxWidth: widthStyle }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* 头部（常驻一屏内，超高时不被顶出视口） */}
          {title && (
            <div className="flex items-center justify-between px-6 py-4 border-b border-neutral-200 shrink-0">
              <h3 className="text-lg font-semibold text-neutral-900">{title}</h3>
              {closable && (
                <button
                  onClick={onClose}
                  className="p-1 text-neutral-400 hover:text-neutral-600 hover:bg-neutral-100 rounded transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              )}
            </div>
          )}

          {/* 内容（超高时内部滚动，保证标题与底部按钮同屏可见） */}
          <div data-testid="modal-body" className="px-6 py-4 overflow-y-auto min-h-0 flex-1">{children}</div>

          {/* 底部（常驻一屏内） */}
          {footer !== undefined ? (
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-neutral-200 shrink-0">
              {footer}
            </div>
          ) : (
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-neutral-200 shrink-0">
              <Button variant="secondary" onClick={onClose}>
                取消
              </Button>
              <Button onClick={onClose}>确定</Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default Modal
