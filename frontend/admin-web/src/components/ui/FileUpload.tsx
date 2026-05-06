'use client'

import { useState, useRef, useCallback } from 'react'
import { Upload, X, File, Image as ImageIcon, FileText, Loader2 } from 'lucide-react'
import NextImage from 'next/image'
import { cn } from '@/lib/utils'
import { fileApi } from '@/lib/api'
import { toast } from 'sonner'
import type { UploadedFile } from '@/types'

interface FileUploadProps {
  accept?: string
  maxSize?: number          // 最大文件大小(MB)
  maxFiles?: number         // 最大文件数
  value?: UploadedFile[]    // 已上传的文件列表
  onChange?: (files: UploadedFile[]) => void
  multiple?: boolean        // 是否多文件
  directory?: string        // 上传目录
  label?: string
  hint?: string
}

interface UploadingFile {
  id: string
  name: string
  progress: number
  status: 'uploading' | 'success' | 'error'
}

export default function FileUpload({
  accept = 'image/jpeg,image/png,image/gif,image/webp,.pdf,.xlsx,.docx',
  maxSize = 5,
  maxFiles = 1,
  value = [],
  onChange,
  multiple = false,
  directory = 'files',
  label,
  hint,
}: FileUploadProps) {
  const [uploadingFiles, setUploadingFiles] = useState<UploadingFile[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const effectiveMax = multiple ? maxFiles : 1

  const isImageType = (type: string) => type.startsWith('image/')

  const getFileIcon = (type: string) => {
    if (isImageType(type)) return <ImageIcon className="w-8 h-8 text-blue-400" />
    if (type.includes('pdf')) return <FileText className="w-8 h-8 text-red-400" />
    return <File className="w-8 h-8 text-gray-400" />
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const handleFiles = useCallback(async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return

    const remaining = effectiveMax - value.length
    if (remaining <= 0) {
      toast.error(`最多只能上传 ${effectiveMax} 个文件`)
      return
    }

    const filesToUpload = Array.from(fileList).slice(0, remaining)

    // Pre-validate
    for (const file of filesToUpload) {
      if (file.size > maxSize * 1024 * 1024) {
        toast.error(`${file.name} 超过 ${maxSize}MB 大小限制`)
        return
      }
    }

    // Upload each file
    const newUploading: UploadingFile[] = filesToUpload.map((f) => ({
      id: Math.random().toString(36).substring(2, 10),
      name: f.name,
      progress: 0,
      status: 'uploading' as const,
    }))
    setUploadingFiles((prev) => [...prev, ...newUploading])

    const results: UploadedFile[] = []

    for (let i = 0; i < filesToUpload.length; i++) {
      const file = filesToUpload[i]
      const uploadId = newUploading[i].id

      try {
        const res = await fileApi.uploadFile(file, directory, (percent) => {
          setUploadingFiles((prev) =>
            prev.map((u) => (u.id === uploadId ? { ...u, progress: percent } : u))
          )
        })

        const uploaded = res.data.data
        results.push(uploaded)

        setUploadingFiles((prev) =>
          prev.map((u) => (u.id === uploadId ? { ...u, progress: 100, status: 'success' } : u))
        )
      } catch {
        toast.error(`${file.name} 上传失败`)
        setUploadingFiles((prev) =>
          prev.map((u) => (u.id === uploadId ? { ...u, status: 'error' } : u))
        )
      }
    }

    // Clean up uploading states after a short delay
    setTimeout(() => {
      setUploadingFiles((prev) => prev.filter((u) => u.status === 'uploading'))
    }, 1000)

    if (results.length > 0) {
      onChange?.([...value, ...results])
    }

    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [value, effectiveMax, maxSize, directory, onChange])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
    handleFiles(e.dataTransfer.files)
  }, [handleFiles])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
  }, [])

  const handleRemove = (index: number) => {
    const file = value[index]
    const newFiles = [...value]
    newFiles.splice(index, 1)
    onChange?.(newFiles)

    // Optionally delete from server
    if (file.id) {
      fileApi.deleteFile(file.id, file.url).catch(() => {
        // Silent fail for cleanup
      })
    }
  }

  const isUploading = uploadingFiles.some((u) => u.status === 'uploading')

  return (
    <div className="w-full">
      {label && (
        <label className="block text-sm font-medium text-gray-700 mb-1.5">
          {label}
        </label>
      )}

      {/* File list */}
      {value.length > 0 && (
        <div className="space-y-2 mb-3">
          {value.map((file, index) => (
            <div
              key={file.id || index}
              className="flex items-center gap-3 p-2.5 rounded-lg border border-gray-200 bg-gray-50/50 group"
            >
              {/* Thumbnail or icon */}
              {isImageType(file.type) ? (
                <NextImage
                  src={file.url}
                  alt={file.name}
                  width={40}
                  height={40}
                  className="w-10 h-10 rounded object-cover cursor-pointer flex-shrink-0"
                  onClick={() => setPreviewUrl(file.url)}
                  unoptimized
                />
              ) : (
                <div className="w-10 h-10 rounded bg-white border border-gray-200 flex items-center justify-center flex-shrink-0">
                  {getFileIcon(file.type)}
                </div>
              )}

              {/* File info */}
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-900 truncate">{file.name}</p>
                <p className="text-xs text-gray-500">{formatSize(file.size)}</p>
              </div>

              {/* Remove button */}
              <button
                type="button"
                onClick={() => handleRemove(index)}
                className="p-1 text-gray-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Uploading progress */}
      {uploadingFiles.length > 0 && (
        <div className="space-y-2 mb-3">
          {uploadingFiles.map((file) => (
            <div
              key={file.id}
              className="flex items-center gap-3 p-2.5 rounded-lg border border-blue-200 bg-blue-50/50"
            >
              <Loader2 className="w-5 h-5 text-blue-500 animate-spin flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-900 truncate">{file.name}</p>
                <div className="mt-1 w-full bg-blue-100 rounded-full h-1.5">
                  <div
                    className={cn(
                      'h-1.5 rounded-full transition-all duration-300',
                      file.status === 'error' ? 'bg-red-500' : 'bg-blue-500'
                    )}
                    style={{ width: `${file.progress}%` }}
                  />
                </div>
              </div>
              <span className="text-xs text-gray-500 flex-shrink-0">{file.progress}%</span>
            </div>
          ))}
        </div>
      )}

      {/* Drop zone / upload button */}
      {value.length < effectiveMax && (
        <div
          onClick={() => fileInputRef.current?.click()}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={cn(
            'relative rounded-lg border-2 border-dashed p-6 flex flex-col items-center justify-center gap-2 cursor-pointer transition-colors',
            dragOver
              ? 'border-primary-500 bg-primary-50'
              : 'border-gray-300 hover:border-primary-400 hover:bg-gray-50',
            isUploading && 'pointer-events-none opacity-60'
          )}
        >
          {isUploading ? (
            <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
          ) : (
            <>
              <Upload className="w-8 h-8 text-gray-400" />
              <div className="text-center">
                <span className="text-sm font-medium text-primary-600">点击上传</span>
                <span className="text-sm text-gray-500"> 或拖拽文件到此处</span>
              </div>
            </>
          )}
        </div>
      )}

      {hint && (
        <p className="mt-1.5 text-xs text-gray-500">{hint}</p>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept={accept}
        multiple={multiple && effectiveMax > 1}
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />

      {/* Image preview modal */}
      {previewUrl && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
          onClick={() => setPreviewUrl(null)}
        >
          <div className="relative max-w-4xl max-h-[90vh]">
            <NextImage src={previewUrl} alt="预览" width={1200} height={900} className="max-w-full max-h-[85vh] object-contain rounded-lg" unoptimized />
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
