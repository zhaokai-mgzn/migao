'use client'

import { useRef, useEffect, useState, useMemo } from 'react'
import { Send, Loader2, StopCircle, ImagePlus, X, Plus } from 'lucide-react'
import NextImage from 'next/image'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/store/chat'
import { chatApi } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import { toast } from 'sonner'

interface PendingImage {
  url: string
  name: string
  file?: File          // 本地预览用
  localPreview?: string // blob URL
}

const MAX_IMAGES = 3
const MAX_FILE_SIZE = 5 * 1024 * 1024 // 5MB
const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']

export default function MessageInput() {
  const { currentSessionId, sessions, isStreaming, sendMessage, stopStreaming, createSession } =
    useChatStore()
  const [input, setInput] = useState('')
  const [images, setImages] = useState<PendingImage[]>([])
  const [isUploading, setIsUploading] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // 当前会话状态：closed 时禁用输入
  const currentSession = useMemo(
    () => sessions.find(s => s.session_id === currentSessionId),
    [sessions, currentSessionId]
  )
  const isSessionClosed = currentSession?.status === 'closed'

  const handleNewSession = () => {
    createSession()
  }

  // 自动调整高度
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, 128) + 'px'
    }
  }, [input])

  // 清理 blob URLs
  useEffect(() => {
    return () => {
      images.forEach((img) => {
        if (img.localPreview) URL.revokeObjectURL(img.localPreview)
      })
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    if (fileInputRef.current) fileInputRef.current.value = ''
    if (files.length === 0) return

    // 验证数量
    const remaining = MAX_IMAGES - images.length
    if (remaining <= 0) {
      toast.error(`最多上传 ${MAX_IMAGES} 张图片`)
      return
    }
    const filesToUpload = files.slice(0, remaining)

    // 验证类型和大小
    for (const file of filesToUpload) {
      if (!ACCEPTED_TYPES.includes(file.type)) {
        toast.error(`不支持的文件类型: ${file.name}`)
        return
      }
      if (file.size > MAX_FILE_SIZE) {
        toast.error(`文件 ${file.name} 超过 5MB 限制`)
        return
      }
    }

    // 上传
    setIsUploading(true)
    try {
      const token = useAuthStore.getState().accessToken || ''
      const result = await chatApi.uploadChatImages(filesToUpload, token)
      if (result.success && result.data?.files) {
        const newImages: PendingImage[] = result.data.files.map((f, i) => ({
          url: f.url,
          name: f.name,
          localPreview: URL.createObjectURL(filesToUpload[i]),
        }))
        setImages((prev) => [...prev, ...newImages].slice(0, MAX_IMAGES))
      }
    } catch (err) {
      console.error('图片上传失败:', err)
      toast.error('图片上传失败，请稍后重试')
    } finally {
      setIsUploading(false)
    }
  }

  const removeImage = (index: number) => {
    setImages((prev) => {
      const removed = prev[index]
      if (removed.localPreview) URL.revokeObjectURL(removed.localPreview)
      return prev.filter((_, i) => i !== index)
    })
  }

  const handleSend = () => {
    if ((!input.trim() && images.length === 0) || isStreaming || isUploading || !currentSessionId) return
    if (isSessionClosed) {
      toast.error('会话已结束，请创建新对话')
      return
    }
    const imageUrls = images.length > 0 ? images.map((img) => img.url) : undefined
    sendMessage(input || ' ', imageUrls)
    setInput('')
    // 清理图片
    images.forEach((img) => {
      if (img.localPreview) URL.revokeObjectURL(img.localPreview)
    })
    setImages([])
    // 重置高度
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const canSend = (input.trim() || images.length > 0) && !isUploading

  if (!currentSessionId) return null

  return (
    <div className="px-4 py-3 bg-white border-t border-gray-200">
      <div className="max-w-3xl mx-auto">
        {/* 图片预览区 */}
        {images.length > 0 && (
          <div className="flex gap-2 mb-2 px-1">
            {images.map((img, index) => (
              <div
                key={index}
                className="relative group w-20 h-20 rounded-lg overflow-hidden border border-gray-200 bg-gray-50 flex-shrink-0"
              >
                <NextImage
                  src={img.localPreview || img.url}
                  alt={img.name}
                  width={80}
                  height={80}
                  className="w-full h-full object-cover"
                  unoptimized
                />
                <button
                  onClick={() => removeImage(index)}
                  className="absolute -top-0 -right-0 w-5 h-5 bg-black/60 text-white rounded-bl-md flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
            {isUploading && (
              <div className="w-20 h-20 rounded-lg border border-dashed border-gray-300 bg-gray-50 flex items-center justify-center flex-shrink-0">
                <Loader2 className="w-5 h-5 text-gray-400 animate-spin" />
              </div>
            )}
          </div>
        )}

        <div className="relative flex items-end gap-2 bg-gray-50 border border-gray-200 rounded-2xl px-3 py-2 focus-within:border-primary-400 focus-within:ring-1 focus-within:ring-primary-400/20 transition-colors">
          {/* 图片上传按钮 */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isSessionClosed || isStreaming || isUploading || images.length >= MAX_IMAGES}
            className={cn(
              'p-1.5 rounded-lg transition-colors flex-shrink-0',
              isSessionClosed || images.length >= MAX_IMAGES
                ? 'text-gray-300 cursor-not-allowed'
                : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'
            )}
            title={isSessionClosed ? '会话已结束' : images.length >= MAX_IMAGES ? `最多 ${MAX_IMAGES} 张图片` : '添加图片'}
          >
            {isUploading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <ImagePlus className="w-5 h-5" />
            )}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/gif,image/webp"
            multiple
            className="hidden"
            onChange={handleFileSelect}
          />

          {isSessionClosed ? (
            <>
              <textarea
                ref={textareaRef}
                value=""
                readOnly
                disabled
                placeholder="会话已结束，请创建新对话"
                rows={1}
                className="flex-1 bg-transparent border-0 resize-none max-h-32 px-1 py-1.5 text-sm focus:outline-none focus:ring-0 disabled:opacity-50 placeholder:text-gray-400"
              />
              <button
                onClick={handleNewSession}
                className="p-2 rounded-xl bg-primary-600 text-white hover:bg-primary-700 transition-colors flex-shrink-0 text-sm font-medium whitespace-nowrap"
              >
                <Plus className="w-4 h-4 inline mr-1" />
                新建对话
              </button>
            </>
          ) : (
            <>
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
                disabled={isStreaming}
                rows={1}
                className="flex-1 bg-transparent border-0 resize-none max-h-32 px-1 py-1.5 text-sm focus:outline-none focus:ring-0 disabled:opacity-50 placeholder:text-gray-400"
              />

              {isStreaming ? (
                <button
                  onClick={stopStreaming}
                  className="p-2 rounded-xl bg-red-500 text-white hover:bg-red-600 transition-colors flex-shrink-0"
                  title="停止生成"
                >
                  <StopCircle className="w-5 h-5" />
                </button>
              ) : (
                <button
                  onClick={handleSend}
                  disabled={!canSend}
                  className={cn(
                    'p-2 rounded-xl transition-colors flex-shrink-0',
                    canSend
                      ? 'bg-primary-600 text-white hover:bg-primary-700'
                      : 'bg-gray-200 text-gray-400 cursor-not-allowed'
                  )}
                  title="发送"
                >
                  <Send className="w-5 h-5" />
                </button>
              )}
            </>
          )}
        </div>
        <p className="text-[10px] text-gray-400 mt-1.5 text-center">
          AI 生成内容仅供参考
        </p>
      </div>
    </div>
  )
}
