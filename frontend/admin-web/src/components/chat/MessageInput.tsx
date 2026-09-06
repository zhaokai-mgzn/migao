'use client'

import { useRef, useEffect, useState, useMemo } from 'react'
import { ArrowUp, Loader2, Square, ImagePlus, X, Plus, AudioLines } from 'lucide-react'
import NextImage from 'next/image'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/store/chat'
import { chatApi } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import { useVoiceRecorder } from '@/hooks/useVoiceRecorder'
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
  const [isDragOver, setIsDragOver] = useState(false)
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

  // AI 回复结束后自动聚焦输入框
  const prevStreamingRef = useRef(isStreaming)
  useEffect(() => {
    if (prevStreamingRef.current && !isStreaming && !isSessionClosed) {
      textareaRef.current?.focus()
    }
    prevStreamingRef.current = isStreaming
  }, [isStreaming, isSessionClosed])

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
    await handleFiles(files)
  }

  /** 校验并上传图片附件（点击选择与拖拽共用） */
  const handleFiles = async (files: File[]) => {
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

  // ═══════ 拖拽上传（UI-009）═══════
  const handleDragOver = (e: React.DragEvent) => {
    if (isSessionClosed || isStreaming || isUploading) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
    setIsDragOver(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    if (isSessionClosed || isStreaming || isUploading) return
    const files = Array.from(e.dataTransfer.files || [])
    void handleFiles(files)
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
    // 发送后自动聚焦输入框，保持连续对话体验
    textareaRef.current?.focus()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // 语音输入
  const handleTranscribed = (text: string) => {
    setInput((prev) => (prev ? prev + text : text))
    // 自动聚焦输入框以便用户编辑
    textareaRef.current?.focus()
  }
  const voice = useVoiceRecorder(handleTranscribed)

  const canSend = (input.trim() || images.length > 0) && !isUploading && voice.state !== 'transcribing'

  /** 录音时长格式化 m:ss（录音状态条用） */
  const formatDuration = (seconds: number) => {
    const m = Math.floor(seconds / 60)
    return `${m}:${String(seconds % 60).padStart(2, '0')}`
  }

  if (!currentSessionId) return null

  return (
    <div className="px-4 py-3 bg-white border-t border-neutral-200/80">
      <div className="max-w-3xl mx-auto">
        <div
          role="region"
          aria-label="消息输入区"
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={cn(
            'relative flex flex-col gap-1.5 bg-white border rounded-2xl px-3 py-2 shadow-sm transition-all',
            isDragOver
              ? 'border-primary-400 ring-2 ring-primary-400/15'
              : 'border-neutral-200 focus-within:border-primary-300 focus-within:ring-2 focus-within:ring-primary-400/15'
          )}
        >
          {/* 拖拽高亮遮罩 */}
          {isDragOver && (
            <div className="absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-primary-500/10 border-2 border-dashed border-primary-400 pointer-events-none">
              <span className="text-sm font-medium text-primary-600 bg-white/80 px-3 py-1 rounded-full shadow-sm">
                松开上传图片
              </span>
            </div>
          )}

          {/* 录音状态条（容器内，替代旧 placeholder 文案 hack，UI-025） */}
          {voice.state === 'recording' && (
            <div
              role="status"
              className="flex items-center gap-1.5 px-1 pt-0.5 text-xs font-medium text-red-500"
            >
              <span className="relative flex h-2 w-2 flex-shrink-0">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500" />
              </span>
              <span>正在录音 {formatDuration(voice.duration)} · 点击停止，Esc 取消</span>
            </div>
          )}

          {/* 图片预览区（内嵌容器内顶部，UI-025） */}
          {(images.length > 0 || isUploading) && (
            <div className="flex gap-2 px-1">
              {images.map((img, index) => (
                <div
                  key={index}
                  className="relative w-20 h-20 rounded-lg overflow-hidden border border-neutral-200 bg-neutral-50 flex-shrink-0"
                >
                  <NextImage
                    src={img.localPreview || img.url}
                    alt={img.name}
                    width={80}
                    height={80}
                    className="w-full h-full object-cover"
                    unoptimized
                  />
                  {/* 删除角标常显（弃 hover 才显，避免触屏不可达），收进缩略图内右上避免溢出裁切 */}
                  <button
                    onClick={() => removeImage(index)}
                    aria-label="删除图片"
                    className="absolute top-1 right-1 w-5 h-5 bg-black/60 text-white rounded-full flex items-center justify-center transition-opacity"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
              {isUploading && (
                <div className="w-20 h-20 rounded-lg border border-dashed border-neutral-300 bg-neutral-50 flex items-center justify-center flex-shrink-0">
                  <Loader2 className="w-5 h-5 text-neutral-400 animate-spin" />
                </div>
              )}
            </div>
          )}

          <div className="flex items-end gap-2">
          {/* 语音输入按钮 */}
          <button
            onClick={
              voice.state === 'recording'
                ? voice.stopRecording
                : voice.state === 'transcribing'
                  ? undefined
                  : voice.startRecording
            }
            onContextMenu={(e) => {
              if (voice.state === 'recording') {
                e.preventDefault()
                voice.cancelRecording()
              }
            }}
            disabled={
              isSessionClosed ||
              isStreaming ||
              voice.state === 'transcribing'
            }
            className={cn(
              'p-1.5 rounded-lg transition-all flex-shrink-0',
              isSessionClosed || voice.state === 'transcribing'
                ? 'text-neutral-300 cursor-not-allowed'
                : voice.state === 'recording'
                  ? 'text-red-500 bg-red-50 shadow-[0_0_0_2px_rgba(239,68,68,0.2)]'
                  : 'text-neutral-400 hover:text-neutral-600 hover:bg-neutral-50'
            )}
            title={
              voice.state === 'recording'
                ? '点击停止录音（右键取消）'
                : voice.state === 'transcribing'
                  ? '转写中...'
                  : '语音输入'
            }
          >
            {voice.state === 'transcribing' ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <AudioLines className="w-5 h-5" />
            )}
          </button>

          {/* 图片上传按钮 */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isSessionClosed || isStreaming || isUploading || images.length >= MAX_IMAGES}
            className={cn(
              'p-1.5 rounded-lg transition-colors flex-shrink-0',
              isSessionClosed || images.length >= MAX_IMAGES
                ? 'text-neutral-300 cursor-not-allowed'
                : 'text-neutral-400 hover:text-neutral-600 hover:bg-neutral-50'
            )}
            title={isSessionClosed ? '会话已结束' : images.length >= MAX_IMAGES ? `最多 ${MAX_IMAGES} 张图片` : '添加图片'}
          >
            {/* 上传中按钮置灰但不换图标（进度提示在预览块，UI-025） */}
            <ImagePlus className="w-5 h-5" />
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
                className="flex-1 bg-transparent border-0 resize-none max-h-32 px-1 py-1.5 text-sm focus:outline-none focus:ring-0 disabled:opacity-50 placeholder:text-neutral-400"
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
                id="chat-message-input"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  // Escape 取消录音
                  if (e.key === 'Escape' && voice.state === 'recording') {
                    e.preventDefault()
                    voice.cancelRecording()
                    return
                  }
                  handleKeyDown(e)
                }}
                placeholder={
                  voice.state === 'transcribing'
                    ? '转写中...'
                    : '输入消息... (Enter 发送, Shift+Enter 换行)'
                }
                disabled={isStreaming || voice.state === 'transcribing'}
                rows={1}
                className="flex-1 bg-transparent border-0 resize-none max-h-32 px-1 py-1.5 text-sm focus:outline-none focus:ring-0 disabled:opacity-50 placeholder:text-neutral-400"
              />

              {isStreaming ? (
                <button
                  onClick={stopStreaming}
                  className="p-2 rounded-xl bg-red-500 text-white hover:bg-red-600 transition-colors flex-shrink-0"
                  title="停止生成"
                >
                  <Square className="w-5 h-5" />
                </button>
              ) : (
                <button
                  onClick={handleSend}
                  disabled={!canSend}
                  className={cn(
                    'p-2 rounded-xl transition-all flex-shrink-0',
                    canSend
                      ? 'bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow-md active:scale-95'
                      : 'bg-neutral-100 text-neutral-400 cursor-not-allowed'
                  )}
                  title="发送"
                >
                  <ArrowUp className="w-5 h-5" />
                </button>
              )}
            </>
          )}
          </div>
        </div>
        <p className="text-[10px] text-neutral-400/70 mt-1.5 text-center">
          AI 生成内容仅供参考
        </p>
      </div>
    </div>
  )
}
