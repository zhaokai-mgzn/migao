'use client'

import { useState, useRef, useCallback } from 'react'
import { Upload, X, GripVertical, Image as ImageIcon, Loader2 } from 'lucide-react'
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
}

export default function ImageUploader({
  value = [],
  onChange,
  max = 1,
  multiple = false,
  label,
  hint,
}: ImageUploaderProps) {
  const [uploading, setUploading] = useState(false)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

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
        // Validate file type
        if (!file.type.startsWith('image/')) {
          toast.error(`${file.name} 不是有效的图片文件`)
          return null
        }
        // Validate file size (max 5MB)
        if (file.size > 5 * 1024 * 1024) {
          toast.error(`${file.name} 超过 5MB 大小限制`)
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
  }, [value, max, onChange])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    handleFileSelect(e.dataTransfer.files)
  }, [handleFileSelect])

  const handleRemove = (index: number) => {
    const newUrls = [...value]
    newUrls.splice(index, 1)
    onChange(newUrls)
  }

  // Drag & drop reorder
  const handleDragStart = (index: number) => {
    setDragIndex(index)
  }

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

  return (
    <div className="w-full">
      {label && (
        <label className="block text-sm font-medium text-gray-700 mb-1.5">
          {label}
        </label>
      )}

      <div className="flex flex-wrap gap-3">
        {/* Existing images */}
        {value.map((url, index) => (
          <div
            key={`${url}-${index}`}
            draggable={multiple}
            onDragStart={() => handleDragStart(index)}
            onDragOver={(e) => handleDragOver(e, index)}
            onDragEnd={handleDragEnd}
            className={cn(
              'relative group w-24 h-24 rounded-lg border-2 border-gray-200 overflow-hidden',
              dragOverIndex === index && 'border-primary-500 border-dashed',
              multiple && 'cursor-grab active:cursor-grabbing'
            )}
          >
            <Image
              src={url}
              alt={`图片 ${index + 1}`}
              width={96}
              height={96}
              className="w-full h-full object-cover cursor-pointer"
              onClick={() => setPreviewUrl(url)}
              unoptimized
            />
            {multiple && (
              <div className="absolute top-1 left-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <GripVertical className="w-4 h-4 text-white drop-shadow" />
              </div>
            )}
            <button
              type="button"
              onClick={() => handleRemove(index)}
              className="absolute top-1 right-1 p-0.5 bg-black/50 rounded-full text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-black/70"
            >
              <X className="w-3.5 h-3.5" />
            </button>
            {index === 0 && !multiple && (
              <span className="absolute bottom-0 left-0 right-0 bg-black/50 text-white text-xs text-center py-0.5">
                主图
              </span>
            )}
          </div>
        ))}

        {/* Upload button */}
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
              <div className="w-5 h-5 border-2 border-primary-600 border-t-transparent rounded-full animate-spin" />
            ) : (
              <>
                <Upload className="w-5 h-5 text-gray-400" />
                <span className="text-xs text-gray-500">上传图片</span>
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
        accept="image/*"
        multiple={multiple && max > 1}
        className="hidden"
        onChange={(e) => handleFileSelect(e.target.files)}
      />

      {/* Preview modal */}
      {previewUrl && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
          onClick={() => setPreviewUrl(null)}
        >
          <div className="relative max-w-4xl max-h-[90vh]">
            <Image src={previewUrl} alt="预览" width={1200} height={900} className="max-w-full max-h-[85vh] object-contain rounded-lg" unoptimized />
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
