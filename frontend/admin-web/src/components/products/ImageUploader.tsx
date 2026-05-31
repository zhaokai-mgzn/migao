'use client'

import { useState, useRef, useCallback } from 'react'
import { Upload, X, GripVertical, Loader2, ImageIcon } from 'lucide-react'
import Image from 'next/image'
import { cn } from '@/lib/utils'
import { fileApi } from '@/lib/api'
import { toast } from 'sonner'

interface ImageUploaderProps {
  value: string[]
  onChange: (urls: string[]) => void
  max?: number
  multiple?: boolean
  label?: string
  hint?: string
  /** 显示主图序号角标（拖拽排序时识别封面） */
  showOrderBadge?: boolean
  /** 删除前要求确认 */
  confirmRemove?: boolean
  /** 允许的 MIME 类型，默认 image/jpeg, image/png, image/webp */
  accept?: string[]
  /** 单文件最大字节数，默认 5MB */
  maxSizeBytes?: number
}

const DEFAULT_ACCEPT = ['image/jpeg', 'image/png', 'image/webp']
const DEFAULT_MAX_SIZE = 5 * 1024 * 1024

function formatAcceptHint(types: string[]): string {
  return types
    .map((t) => t.replace('image/', '').toUpperCase())
    .join(' / ')
}

export default function ImageUploader({
  value = [],
  onChange,
  max = 1,
  multiple = false,
  label,
  hint,
  showOrderBadge = false,
  confirmRemove = false,
  accept = DEFAULT_ACCEPT,
  maxSizeBytes = DEFAULT_MAX_SIZE,
}: ImageUploaderProps) {
  const [uploading, setUploading] = useState(false)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const acceptAttr = accept.join(',')
  const maxSizeMB = Math.round((maxSizeBytes / 1024 / 1024) * 10) / 10

  const handleFileSelect = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return

    const remaining = max - value.length
    if (remaining <= 0) {
      toast.error(`最多只能上传 ${max} 张图片`)
      return
    }

    const filesToUpload = Array.from(files).slice(0, remaining)
    setUploading(true)

    try {
      const uploadPromises = filesToUpload.map(async (file) => {
        // 严格 MIME 校验（jpg/png/webp）
        const lowerType = file.type.toLowerCase()
        if (!accept.includes(lowerType)) {
          toast.error(`${file.name} 格式不支持，仅允许 ${formatAcceptHint(accept)}`)
          return null
        }
        // 大小校验
        if (file.size > maxSizeBytes) {
          toast.error(`${file.name} 超过 ${maxSizeMB}MB 大小限制`)
          return null
        }
        try {
          const res = await fileApi.uploadFile(file, 'products')
          return res.data.data.url
        } catch {
          toast.error(`${file.name} 上传失败`)
          return null
        }
      })

      const results = await Promise.all(uploadPromises)
      const successUrls = results.filter((url): url is string => url !== null)
      if (successUrls.length > 0) {
        onChange([...value, ...successUrls])
      }
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }, [value, max, onChange, accept, maxSizeBytes, maxSizeMB])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    handleFileSelect(e.dataTransfer.files)
  }, [handleFileSelect])

  const handleRemove = (index: number) => {
    if (confirmRemove) {
      const isCover = index === 0 && showOrderBadge
      const tip = isCover
        ? '确定要删除封面图吗？删除后第 2 张将自动成为封面。'
        : '确定要删除这张图片吗？'
      if (!window.confirm(tip)) return
    }
    const newUrls = [...value]
    newUrls.splice(index, 1)
    onChange(newUrls)
  }

  // ============ 拖拽排序 ============
  const handleDragStart = (index: number) => setDragIndex(index)

  const handleDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault()
    if (dragIndex !== null && dragIndex !== index) {
      setDragOverIndex(index)
    }
  }

  const handleDragEnd = () => {
    if (dragIndex !== null && dragOverIndex !== null && dragIndex !== dragOverIndex) {
      const newUrls = [...value]
      const [removed] = newUrls.splice(dragIndex, 1)
      newUrls.splice(dragOverIndex, 0, removed)
      onChange(newUrls)
    }
    setDragIndex(null)
    setDragOverIndex(null)
  }

  const renderBadge = (index: number) => {
    if (!showOrderBadge) {
      // 单图模式保留旧的"主图"标
      if (index === 0 && !multiple) {
        return (
          <span className="absolute bottom-0 left-0 right-0 bg-black/55 text-white text-[11px] text-center py-0.5">
            主图
          </span>
        )
      }
      return null
    }
    // 多图主图模式：序号 + 封面标识
    const isCover = index === 0
    return (
      <span
        className={cn(
          'absolute top-1 left-1 inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded text-[11px] font-medium leading-none',
          isCover
            ? 'bg-amber-500 text-white shadow-sm'
            : 'bg-black/60 text-white'
        )}
      >
        {isCover ? `1·封面` : index + 1}
      </span>
    )
  }

  return (
    <div className="w-full">
      {label && (
        <label className="block text-sm font-medium text-gray-700 mb-1.5">
          {label}
        </label>
      )}

      <div className="flex flex-wrap gap-3">
        {/* 已上传图片 */}
        {value.map((url, index) => (
          <div
            key={`${url}-${index}`}
            draggable={multiple}
            onDragStart={() => handleDragStart(index)}
            onDragOver={(e) => handleDragOver(e, index)}
            onDragEnd={handleDragEnd}
            className={cn(
              'relative group w-24 h-24 rounded-lg border-2 border-gray-200 overflow-hidden bg-gray-50',
              dragOverIndex === index && 'border-primary-500 border-dashed',
              dragIndex === index && 'opacity-50',
              multiple && 'cursor-grab active:cursor-grabbing'
            )}
          >
            {url && typeof url === 'string' && url.trim() !== '' ? (
              <Image
                src={url}
                alt={`图片 ${index + 1}`}
                width={96}
                height={96}
                className="w-full h-full object-cover cursor-pointer"
                onClick={() => setPreviewUrl(url)}
                unoptimized
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-gray-300">
                <ImageIcon className="w-6 h-6" />
              </div>
            )}
            {multiple && (
              <div className="absolute top-1 right-7 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
                <GripVertical className="w-4 h-4 text-white drop-shadow" />
              </div>
            )}
            {renderBadge(index)}
            <button
              type="button"
              onClick={() => handleRemove(index)}
              className="absolute top-1 right-1 p-0.5 bg-black/55 rounded-full text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-500"
              title="删除"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}

        {/* 上传按钮 */}
        {value.length < max && (
          <div
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); e.stopPropagation() }}
            onDrop={handleDrop}
            className={cn(
              'w-24 h-24 rounded-lg border-2 border-dashed border-gray-300 flex flex-col items-center justify-center gap-1 cursor-pointer transition-colors',
              'hover:border-primary-500 hover:bg-primary-50/50',
              uploading && 'pointer-events-none opacity-60'
            )}
          >
            {uploading ? (
              <Loader2 className="w-5 h-5 text-primary-600 animate-spin" />
            ) : (
              <>
                <Upload className="w-5 h-5 text-gray-400" />
                <span className="text-xs text-gray-500">
                  {showOrderBadge && value.length === 0 ? '上传封面' : '上传图片'}
                </span>
                {showOrderBadge && (
                  <span className="text-[10px] text-gray-400 leading-none">
                    {value.length}/{max}
                  </span>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {hint && (
        <p className="mt-1.5 text-xs text-gray-500">{hint}</p>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept={acceptAttr}
        multiple={multiple && max > 1}
        className="hidden"
        onChange={(e) => handleFileSelect(e.target.files)}
      />

      {/* 预览 */}
      {previewUrl && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
          onClick={() => setPreviewUrl(null)}
        >
          <div className="relative max-w-4xl max-h-[90vh]">
            {previewUrl && typeof previewUrl === 'string' && previewUrl.trim() !== '' && (
              <Image src={previewUrl} alt="预览" width={1200} height={900} className="max-w-full max-h-[85vh] object-contain rounded-lg" unoptimized />
            )}
            <button
              onClick={() => setPreviewUrl(null)}
              className="absolute -top-3 -right-3 p-1.5 bg-white rounded-full shadow-lg text-gray-600 hover:text-gray-900"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
