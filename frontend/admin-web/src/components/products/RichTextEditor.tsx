'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import {
  Bold,
  Italic,
  Underline,
  Heading2,
  Heading3,
  List,
  ListOrdered,
  Link as LinkIcon,
  Image as ImageIcon,
  Undo2,
  Redo2,
  Type,
  Loader2,
} from 'lucide-react'
import { cn, resolveImageUrl } from '@/lib/utils'
import { fileApi } from '@/lib/api'
import { toast } from 'sonner'

interface RichTextEditorProps {
  value: string
  onChange: (html: string) => void
  placeholder?: string
  /** 编辑器最小高度，默认 300 */
  minHeight?: number
  /** 上传目录，默认 products/desc */
  uploadDir?: string
}

interface ToolButton {
  key: string
  title: string
  icon: React.ComponentType<{ className?: string }>
  command?: string
  arg?: string
  custom?: () => void
  isActive?: () => boolean
}

/**
 * 轻量富文本编辑器（contentEditable + execCommand）
 * 功能：加粗 / 斜体 / 下划线 / H2 / H3 / 段落 / 有序无序列表 / 链接 / 图片 / 撤销 / 重做
 *
 * 注：execCommand 已被标记为 legacy，但浏览器仍广泛支持，对一个轻量描述编辑器足够。
 *     如未来需要更复杂能力，可平滑替换为 TipTap。
 */
export default function RichTextEditor({
  value,
  onChange,
  placeholder = '请输入内容...',
  minHeight = 300,
  uploadDir = 'products/desc',
}: RichTextEditorProps) {
  const editorRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [, forceTick] = useState(0)
  const isComposingRef = useRef(false)
  const lastValueRef = useRef<string>('')

  // 同步外部 value -> 内部（仅在外部值真正变化且与内部不同时才设置，避免光标跳）
  useEffect(() => {
    if (!editorRef.current) return
    if (value === lastValueRef.current) return
    if (value !== editorRef.current.innerHTML) {
      editorRef.current.innerHTML = value || ''
      lastValueRef.current = value || ''
    }
  }, [value])

  const exec = useCallback((command: string, arg?: string) => {
    editorRef.current?.focus()
    document.execCommand(command, false, arg)
    handleInput()
    forceTick((n) => n + 1)
  }, [])

  const handleInput = useCallback(() => {
    if (!editorRef.current) return
    if (isComposingRef.current) return
    const html = editorRef.current.innerHTML
    lastValueRef.current = html
    onChange(html)
  }, [onChange])

  // 链接插入
  const handleInsertLink = () => {
    const sel = window.getSelection()
    const selectedText = sel?.toString() || ''
    const url = window.prompt('请输入链接地址（http(s)://）', 'https://')
    if (!url) return
    if (!/^https?:\/\//i.test(url)) {
      toast.error('链接必须以 http:// 或 https:// 开头')
      return
    }
    editorRef.current?.focus()
    if (selectedText) {
      document.execCommand('createLink', false, url)
      // 给新生成的链接加上 target=_blank
      const links = editorRef.current?.querySelectorAll('a[href="' + url + '"]')
      links?.forEach((a) => {
        a.setAttribute('target', '_blank')
        a.setAttribute('rel', 'noopener noreferrer')
      })
    } else {
      const linkText = window.prompt('链接显示文字', url) || url
      const html = `<a href="${url}" target="_blank" rel="noopener noreferrer">${linkText}</a>`
      document.execCommand('insertHTML', false, html)
    }
    handleInput()
  }

  // 图片插入（上传到OSS）
  const handlePickImage = () => {
    fileInputRef.current?.click()
  }

  const handleImageFile = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    const file = files[0]
    const allowed = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
    if (!allowed.includes(file.type)) {
      toast.error('仅支持 JPG / PNG / WEBP / GIF 格式')
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error('图片不能超过 5MB')
      return
    }
    setUploading(true)
    try {
      const res = await fileApi.uploadFile(file, uploadDir)
      const url = res.data.data.url
      const renderUrl = resolveImageUrl(url)
      editorRef.current?.focus()
      document.execCommand(
        'insertHTML',
        false,
        `<img src="${renderUrl}" alt="" style="max-width:100%;height:auto;border-radius:6px;" />`
      )
      handleInput()
    } catch {
      toast.error('图片上传失败')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  // 粘贴时去除外部样式（仅保留纯文本 + 基础格式）
  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault()
    const text = e.clipboardData.getData('text/plain')
    document.execCommand('insertText', false, text)
  }

  const isCmdActive = (cmd: string) => {
    try {
      return document.queryCommandState(cmd)
    } catch {
      return false
    }
  }

  const isBlockActive = (tag: string) => {
    try {
      const v = document.queryCommandValue('formatBlock')
      return typeof v === 'string' && v.toLowerCase().replace(/[<>]/g, '') === tag
    } catch {
      return false
    }
  }

  const buttons: (ToolButton | 'divider')[] = [
    { key: 'bold', title: '加粗', icon: Bold, command: 'bold', isActive: () => isCmdActive('bold') },
    { key: 'italic', title: '斜体', icon: Italic, command: 'italic', isActive: () => isCmdActive('italic') },
    { key: 'underline', title: '下划线', icon: Underline, command: 'underline', isActive: () => isCmdActive('underline') },
    'divider',
    { key: 'p', title: '正文', icon: Type, command: 'formatBlock', arg: 'p', isActive: () => isBlockActive('p') },
    { key: 'h2', title: '标题2', icon: Heading2, command: 'formatBlock', arg: 'h2', isActive: () => isBlockActive('h2') },
    { key: 'h3', title: '标题3', icon: Heading3, command: 'formatBlock', arg: 'h3', isActive: () => isBlockActive('h3') },
    'divider',
    { key: 'ul', title: '无序列表', icon: List, command: 'insertUnorderedList', isActive: () => isCmdActive('insertUnorderedList') },
    { key: 'ol', title: '有序列表', icon: ListOrdered, command: 'insertOrderedList', isActive: () => isCmdActive('insertOrderedList') },
    'divider',
    { key: 'link', title: '插入链接', icon: LinkIcon, custom: handleInsertLink },
    { key: 'image', title: '插入图片', icon: ImageIcon, custom: handlePickImage },
    'divider',
    { key: 'undo', title: '撤销', icon: Undo2, command: 'undo' },
    { key: 'redo', title: '重做', icon: Redo2, command: 'redo' },
  ]

  // 监听选区变化以更新工具栏激活态
  useEffect(() => {
    const onSel = () => {
      if (!editorRef.current) return
      if (document.activeElement === editorRef.current) {
        forceTick((n) => n + 1)
      }
    }
    document.addEventListener('selectionchange', onSel)
    return () => document.removeEventListener('selectionchange', onSel)
  }, [])

  return (
    <div className="rich-text-editor border border-gray-300 rounded-lg overflow-hidden bg-white focus-within:border-primary-500 focus-within:ring-2 focus-within:ring-primary-500/15 transition-all">
      {/* 工具栏 */}
      <div className="flex flex-wrap items-center gap-0.5 px-2 py-1.5 border-b border-gray-200 bg-gray-50">
        {buttons.map((b, i) =>
          b === 'divider' ? (
            <span key={`d-${i}`} className="mx-1 h-5 w-px bg-gray-300" />
          ) : (
            <button
              key={b.key}
              type="button"
              title={b.title}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                if (b.custom) b.custom()
                else if (b.command) exec(b.command, b.arg)
              }}
              className={cn(
                'inline-flex items-center justify-center w-7 h-7 rounded text-gray-600 hover:bg-white hover:text-primary-600 transition-colors',
                b.isActive?.() && 'bg-primary-100 text-primary-700'
              )}
            >
              <b.icon className="w-4 h-4" />
            </button>
          )
        )}
        {uploading && (
          <span className="ml-2 inline-flex items-center gap-1 text-xs text-gray-500">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> 图片上传中...
          </span>
        )}
      </div>

      {/* 编辑区 */}
      <div
        ref={editorRef}
        contentEditable
        suppressContentEditableWarning
        data-placeholder={placeholder}
        onInput={handleInput}
        onCompositionStart={() => { isComposingRef.current = true }}
        onCompositionEnd={() => { isComposingRef.current = false; handleInput() }}
        onPaste={handlePaste}
        className="rt-editor-content px-4 py-3 outline-none text-sm text-gray-800 leading-relaxed overflow-auto"
        style={{ minHeight }}
      />

      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/gif"
        className="hidden"
        onChange={(e) => handleImageFile(e.target.files)}
      />

      {/* 局部样式：placeholder / 标题层级 / 列表样式 */}
      <style jsx>{`
        .rt-editor-content:empty::before {
          content: attr(data-placeholder);
          color: #9ca3af;
          pointer-events: none;
        }
        .rt-editor-content :global(h2) {
          font-size: 18px;
          font-weight: 600;
          margin: 12px 0 6px;
          color: #111827;
        }
        .rt-editor-content :global(h3) {
          font-size: 15px;
          font-weight: 600;
          margin: 10px 0 4px;
          color: #1f2937;
        }
        .rt-editor-content :global(p) {
          margin: 4px 0;
        }
        .rt-editor-content :global(ul) {
          list-style: disc;
          padding-left: 24px;
          margin: 6px 0;
        }
        .rt-editor-content :global(ol) {
          list-style: decimal;
          padding-left: 24px;
          margin: 6px 0;
        }
        .rt-editor-content :global(a) {
          color: #2563eb;
          text-decoration: underline;
        }
        .rt-editor-content :global(img) {
          max-width: 100%;
          height: auto;
          border-radius: 6px;
          margin: 6px 0;
        }
      `}</style>
    </div>
  )
}
