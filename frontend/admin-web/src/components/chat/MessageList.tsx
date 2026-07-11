'use client'

import { useEffect, useRef, useCallback } from 'react'
import {
  Bot,
  User,
  Loader2,
  Copy,
  Check,
  X,
} from 'lucide-react'
import NextImage from 'next/image'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/store/chat'
import { useAuthStore } from '@/store/auth'
import { chatApi } from '@/lib/api'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import dayjs from 'dayjs'
import { useState } from 'react'
import type { ChatMessage, ChatCard } from '@/types'

import ToolResultCard from './ToolResultCard'
import InteractiveMessage from './InteractiveMessage'
import WelcomePanel from './WelcomePanel'

export default function MessageList() {
  const { messages, isLoadingMessages, currentSessionId, sessions } =
    useChatStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (!currentSessionId) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-gray-400">
        <Bot className="w-16 h-16 mb-4 text-gray-200" />
        <p className="text-lg font-medium text-gray-400">选择或创建一个对话</p>
        <p className="text-sm mt-2 text-gray-300">
          从左侧列表选择已有会话，或点击「新建对话」创建新会话
        </p>
      </div>
    )
  }

  if (isLoadingMessages) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-6 h-6 border-2 border-primary-600 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm text-gray-400">加载消息中...</span>
        </div>
      </div>
    )
  }

  if (messages.length === 0) {
    // 首次访问无历史会话 → 新手引导欢迎面板
    if (sessions.length === 0 && !isLoadingMessages) {
      return <WelcomePanel />
    }
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-gray-400">
        <Bot className="w-16 h-16 mb-4 text-gray-200" />
        <p className="text-lg font-medium text-gray-400">发送消息开始对话</p>
        <p className="text-sm mt-2 text-gray-300">
          AI 助手将帮助您解答问题
        </p>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="flex-1 overflow-y-auto px-4 py-4">
      <div className="w-full space-y-4">
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        <div ref={messagesEndRef} />
      </div>
    </div>
  )
}

function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === 'system') {
    return (
      <div className="flex justify-center">
        <span className="text-xs text-gray-400 bg-gray-100 px-3 py-1 rounded-full">
          {message.content}
        </span>
      </div>
    )
  }

  const isUser = message.role === 'user'
  const isAI = message.role === 'assistant'

  return (
    <div className={cn('flex gap-3', isUser ? 'justify-end' : 'justify-start')}>
      {/* AI 头像 */}
      {isAI && (
        <div className="w-8 h-8 rounded-full bg-primary-100 flex items-center justify-center flex-shrink-0 mt-0.5">
          <Bot className="w-5 h-5 text-primary-600" />
        </div>
      )}

      <div className={cn('flex flex-col max-w-[70%]', isUser ? 'items-end' : 'items-start')}>
        {/* 消息气泡 */}
        <div
          className={cn(
            'rounded-2xl px-4 py-2.5',
            isUser
              ? 'bg-primary-600 text-white rounded-br-md'
              : 'bg-white border border-gray-200 text-gray-800 rounded-bl-md shadow-sm'
          )}
        >
          {isAI ? (
            <AIMessageContent message={message} />
          ) : (
            <>
              <p className="text-sm whitespace-pre-wrap break-words">{message.content}</p>
              {message.images && message.images.length > 0 && (
                <MessageImages images={message.images} />
              )}
            </>
          )}
        </div>

        {/* 工具执行中进度提示 — 隐藏原始工具调用，仅显示人性化状态 */}
        <ToolProgressIndicator message={message} />

        {/* 卡片展示 */}
        {isAI && message.cards && message.cards.length > 0 && (
          <div className="mt-2 w-full space-y-2">
            {message.cards.map((card, index) => (
              <CardRenderer key={index} card={card} />
            ))}
          </div>
        )}

        {/* 交互式组件 */}
        {isAI && message.interactive && !message.isStreaming && (
          <div className="mt-2 w-full">
            <InteractiveMessage
              interactive={message.interactive}
              disabled={message.isStreaming}
            />
          </div>
        )}

        {/* 回复建议 */}
        {isAI && message.suggestions && message.suggestions.length > 0 && !message.isStreaming && (
          <div className="mt-3 w-full">
            <p className="text-xs text-gray-500 mb-1.5 px-1 font-medium">推荐提问：</p>
            <div className="space-y-1">
              {message.suggestions.map((suggestion, index) => (
                <button
                  key={index}
                  onClick={() => {
                    // 埋点：记录建议被点击
                    const token = useAuthStore.getState().accessToken || ''
                    const AI_SERVICE_URL = chatApi.AI_SERVICE_URL
                    fetch(`${AI_SERVICE_URL}/api/chat/suggestion-feedback`, {
                      method: 'POST',
                      headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`,
                      },
                      body: JSON.stringify({
                        session_id: message.session_id || useChatStore.getState().currentSessionId,
                        suggestion,
                        message_id: message.id,
                      }),
                    }).catch(() => { /* fire-and-forget */ })

                    const { sendMessage } = useChatStore.getState()
                    sendMessage(suggestion)
                  }}
                  className="block w-full text-left px-2.5 py-1.5 rounded-lg bg-gradient-to-r from-primary-50 to-primary-100 border border-primary-200 hover:from-primary-100 hover:to-primary-200 transition-colors text-xs text-primary-700 break-words line-clamp-2"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* 时间戳 */}
        {message.created_at && (
          <span className="text-[10px] text-gray-400 mt-1 px-1">
            {dayjs(message.created_at).format('HH:mm')}
          </span>
        )}
      </div>

      {/* 用户头像 */}
      {isUser && (
        <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0 mt-0.5">
          <User className="w-5 h-5 text-gray-600" />
        </div>
      )}
    </div>
  )
}

function AIMessageContent({ message }: { message: ChatMessage }) {
  const [copied, setCopied] = useState(false)
  const isStreamingEmpty = message.isStreaming && !message.content

  // 正在执行中的工具
  const runningTools = (message.tool_calls || []).filter(
    (tc) => tc.status === 'running'
  )
  const hasRunning = runningTools.length > 0

  if (isStreamingEmpty && hasRunning) {
    return (
      <div className="flex items-center gap-2 text-gray-500 text-sm">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span>正在处理您的请求...</span>
      </div>
    )
  }

  if (isStreamingEmpty) {
    return (
      <div className="flex items-center gap-1.5 py-1">
        <span
          className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
          style={{ animationDelay: '0ms' }}
        />
        <span
          className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
          style={{ animationDelay: '150ms' }}
        />
        <span
          className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
          style={{ animationDelay: '300ms' }}
        />
      </div>
    )
  }

  // 清理 AI 回复中的 tool_call 伪代码块（Vision LLM 可能有幻觉输出）
  const cleanContent = (message.content || '').replace(
    /```tool_call[\s\S]*?```/g,
    ''
  ).trim()

  if (!cleanContent && !message.isStreaming) {
    // 用户主动中断 → 显示"对话已中断"
    if (message.wasAborted) {
      return (
        <p className="text-sm text-gray-400 italic">对话已中断</p>
      )
    }
    return (
      <p className="text-sm text-gray-400 italic">（已处理）</p>
    )
  }

  const handleCopy = async () => {
    await navigator.clipboard.writeText(cleanContent).catch((e) => console.error('Clipboard write failed:', e))
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="group relative">
      <div className="prose prose-sm max-w-none text-gray-800 [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_pre]:my-2 [&_code]:text-xs [&_code]:bg-gray-100 [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded [&_table]:text-xs [&_table]:border-collapse [&_th]:border [&_th]:border-gray-300 [&_th]:bg-gray-100 [&_th]:px-2 [&_th]:py-1 [&_td]:border [&_td]:border-gray-300 [&_td]:px-2 [&_td]:py-1">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {cleanContent}
        </ReactMarkdown>
        {message.isStreaming && (
          <span className="inline-block w-1.5 h-4 bg-primary-600 animate-pulse ml-0.5 align-text-bottom" />
        )}
        {message.images && message.images.length > 0 && (
          <MessageImages images={message.images} />
        )}
      </div>
      {/* 复制按钮 — hover 时显示 */}
      {!message.isStreaming && (
        <button
          onClick={handleCopy}
          className="absolute top-0 right-0 opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600"
          title="复制回复内容"
        >
          {copied ? (
            <Check className="w-3.5 h-3.5 text-green-500" />
          ) : (
            <Copy className="w-3.5 h-3.5" />
          )}
        </button>
      )}
    </div>
  )
}

function MessageImages({ images }: { images: string[] }) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)

  const closePreview = useCallback(() => setPreviewUrl(null), [])

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closePreview()
    }
    if (previewUrl) {
      document.addEventListener('keydown', handleEsc)
      return () => document.removeEventListener('keydown', handleEsc)
    }
  }, [previewUrl, closePreview])

  return (
    <>
      <div className="flex flex-wrap gap-1.5 mt-2">
        {images.map((url, idx) => (
          <button
            key={idx}
            onClick={() => setPreviewUrl(url)}
            className="block w-[120px] h-[120px] rounded-lg overflow-hidden border border-white/20 hover:opacity-90 transition-opacity flex-shrink-0"
          >
            <NextImage
              src={url}
              alt={`图片 ${idx + 1}`}
              width={120}
              height={120}
              className="w-full h-full object-cover"
              unoptimized
            />
          </button>
        ))}
      </div>

      {/* 图片预览 Modal */}
      {previewUrl && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70"
          onClick={closePreview}
        >
          <button
            onClick={closePreview}
            className="absolute top-4 right-4 p-2 rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
          >
            <X className="w-6 h-6" />
          </button>
          <NextImage
            src={previewUrl}
            alt="预览"
            width={1200}
            height={900}
            className="max-w-[90vw] max-h-[90vh] object-contain rounded-lg"
            unoptimized
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </>
  )
}

/** 工具执行进度指示器 — 仅显示人性化状态，不暴露工具细节 */
function ToolProgressIndicator({ message }: { message: ChatMessage }) {
  const toolCalls = message.tool_calls || []
  if (toolCalls.length === 0) return null

  const runningCount = toolCalls.filter(tc => tc.status === 'running').length
  const errorCount = toolCalls.filter(tc => tc.status === 'error').length

  // 还在执行中
  if (runningCount > 0) {
    return (
      <div className="mt-2 flex items-center gap-1.5 text-xs text-gray-400">
        <Loader2 className="w-3 h-3 animate-spin" />
        <span>正在处理您的请求...</span>
      </div>
    )
  }

  // 全部完成且有错误 — 静默处理
  if (errorCount > 0) return null

  // 全部完成 — 不显示
  return null
}

function CardRenderer({ card }: { card: ChatCard }) {
  return <ToolResultCard card={card} />
}
