/**
 * SSE 流式客户端
 *
 * 微信小程序不支持原生 EventSource，使用 wx.request + enableChunkedTransfer
 * 解析后端 ai-agent-service 的 SSE 事件格式
 *
 * 后端事件类型（来自 sse.py）：
 * - event: text        data: {"content": "..."}
 * - event: tool_call   data: {"tool": "...", "args": {...}}
 * - event: tool_result data: {"tool": "...", "result": {...}}
 * - event: card        data: {"type": "...", "data": {...}}
 * - event: loading     data: {"content": "..."}
 * - event: done        data: {"session_id": "...", "message_id": "..."}
 * - event: error       data: {"message": "...", "code": "..."}
 * - : heartbeat        (注释行心跳)
 */

import Taro from '@tarojs/taro'
import { getToken } from './auth'
import { AI_API_BASE_URL, REQUEST_CONFIG } from './constants'
import type {
  SSETextEvent,
  SSEToolCallEvent,
  SSEToolResultEvent,
  SSECardEvent,
  SSEDoneEvent,
  SSEErrorEvent,
  SSELoadingEvent,
} from '../types'

export interface SSECallbacks {
  /** 文本内容（流式逐段） */
  onText?: (data: SSETextEvent) => void
  /** 工具调用开始 */
  onToolCall?: (data: SSEToolCallEvent) => void
  /** 工具调用结果 */
  onToolResult?: (data: SSEToolResultEvent) => void
  /** 卡片数据 */
  onCard?: (data: SSECardEvent) => void
  /** 加载状态 */
  onLoading?: (data: SSELoadingEvent) => void
  /** 流式完成 */
  onDone?: (data: SSEDoneEvent) => void
  /** 错误 */
  onError?: (error: SSEErrorEvent) => void
}

/**
 * SSE 客户端
 *
 * 使用 wx.request 的 enableChunkedTransfer 接收流式数据。
 * 小程序的 Taro.request 底层会透传此参数给 wx.request。
 *
 * 如果运行环境不支持 chunked transfer（如旧版微信基础库），
 * 会降级为等待完整响应后一次性解析。
 */
export class SSEClient {
  private baseURL: string
  private requestTask: Taro.RequestTask<any> | null = null
  private aborted = false

  constructor(baseURL?: string) {
    this.baseURL = baseURL || AI_API_BASE_URL
  }

  /**
   * 发送消息并接收 SSE 流
   */
  sendMessage(
    sessionId: string,
    message: string,
    images: string[] | undefined,
    callbacks: SSECallbacks,
  ): void {
    this.aborted = false

    const token = getToken()
    const url = `${this.baseURL}/api/chat/send`

    let buffer = ''

    // 使用 Taro.request，配合 enableChunkedTransfer
    // @ts-ignore - enableChunkedTransfer 是微信小程序特有参数
    this.requestTask = Taro.request({
      url,
      method: 'POST',
      header: {
        'Content-Type': 'application/json',
        'Authorization': token ? `Bearer ${token}` : '',
        'X-Client-Type': 'wechat_mini',
        'Accept': 'text/event-stream',
      },
      data: {
        session_id: sessionId,
        message,
        ...(images?.length ? { images } : {}),
      },
      timeout: 120000, // SSE 流式请求需要更长超时
      // @ts-ignore - enableChunkedTransfer 是 wx.request 的原生参数
      enableChunkedTransfer: true,
      success: (res) => {
        if (this.aborted) return

        const { statusCode, data } = res

        if (statusCode !== 200) {
          callbacks.onError?.({
            message: `请求失败: ${statusCode}`,
            code: String(statusCode),
          })
          return
        }

        // 处理完整响应（降级模式或一次性返回的情况）
        if (typeof data === 'string') {
          buffer += data
          this.parseSSEBuffer(buffer, callbacks)
        } else if (typeof data === 'object') {
          // 非 SSE 的 JSON 响应（可能是错误）
          const errorData = data as any
          if (errorData.error || !errorData.success) {
            callbacks.onError?.({
              message: errorData.error?.message || errorData.detail || '请求失败',
              code: errorData.error?.code,
            })
          }
        }
      },
      fail: (error) => {
        if (this.aborted) return
        callbacks.onError?.({
          message: error.errMsg || '网络请求失败',
        })
      },
    }) as any

    // 监听 chunked 数据（微信小程序 wx.request 的 onChunkReceived）
    if (this.requestTask && typeof (this.requestTask as any).onChunkReceived === 'function') {
      ;(this.requestTask as any).onChunkReceived((response: { data: ArrayBuffer }) => {
        if (this.aborted) return
        try {
          // ArrayBuffer -> string
          const text = arrayBufferToString(response.data)
          buffer += text
          // 实时解析 SSE 事件
          buffer = this.parseSSEBufferIncremental(buffer, callbacks)
        } catch (e) {
          console.error('解析 SSE chunk 失败:', e)
        }
      })
    }
  }

  /**
   * 增量解析 SSE buffer，返回未处理完的剩余内容
   */
  private parseSSEBufferIncremental(buffer: string, callbacks: SSECallbacks): string {
    const lines = buffer.split('\n')
    // 最后一行可能不完整，保留
    const remaining = lines.pop() || ''

    let currentEvent = ''

    for (const line of lines) {
      const trimmed = line.trim()

      // 心跳（注释行）
      if (trimmed.startsWith(': ') || trimmed === ':') {
        continue
      }

      // 事件类型
      if (trimmed.startsWith('event: ')) {
        currentEvent = trimmed.substring(7).trim()
        continue
      }

      // 数据
      if (trimmed.startsWith('data: ')) {
        const dataStr = trimmed.substring(6)
        this.dispatchEvent(currentEvent, dataStr, callbacks)
        currentEvent = ''
        continue
      }

      // 空行：事件分隔
      if (trimmed === '') {
        currentEvent = ''
      }
    }

    return remaining
  }

  /**
   * 一次性解析整段 SSE 文本（降级模式）
   */
  private parseSSEBuffer(text: string, callbacks: SSECallbacks): void {
    this.parseSSEBufferIncremental(text + '\n', callbacks)
  }

  /**
   * 分发 SSE 事件到对应回调
   */
  private dispatchEvent(
    eventType: string,
    dataStr: string,
    callbacks: SSECallbacks,
  ): void {
    try {
      const data = JSON.parse(dataStr)

      switch (eventType) {
        case 'text':
          callbacks.onText?.(data as SSETextEvent)
          break

        case 'tool_call':
          callbacks.onToolCall?.(data as SSEToolCallEvent)
          break

        case 'tool_result':
          callbacks.onToolResult?.(data as SSEToolResultEvent)
          break

        case 'card':
          callbacks.onCard?.(data as SSECardEvent)
          break

        case 'loading':
          callbacks.onLoading?.(data as SSELoadingEvent)
          break

        case 'done':
          callbacks.onDone?.(data as SSEDoneEvent)
          break

        case 'error':
          callbacks.onError?.(data as SSEErrorEvent)
          break

        case 'message':
          // 兼容通用 message 事件
          if (data.type === 'text' || data.content) {
            callbacks.onText?.({ content: data.content || data.delta || '' })
          } else if (data.type === 'error') {
            callbacks.onError?.({ message: data.message || '未知错误' })
          }
          break

        default:
          // 未知事件类型，如果有 content 字段当作文本处理
          if (data.content) {
            callbacks.onText?.({ content: data.content })
          }
          break
      }
    } catch {
      // 非 JSON 数据，尝试当作纯文本
      if (dataStr.trim()) {
        callbacks.onText?.({ content: dataStr })
      }
    }
  }

  /**
   * 取消当前请求
   */
  abort(): void {
    this.aborted = true
    if (this.requestTask) {
      this.requestTask.abort()
      this.requestTask = null
    }
  }
}

/**
 * ArrayBuffer 转字符串
 */
function arrayBufferToString(buffer: ArrayBuffer): string {
  // 微信小程序环境
  if (typeof TextDecoder !== 'undefined') {
    return new TextDecoder('utf-8').decode(buffer)
  }
  // 降级方案
  const uint8Array = new Uint8Array(buffer)
  let str = ''
  for (let i = 0; i < uint8Array.length; i++) {
    str += String.fromCharCode(uint8Array[i])
  }
  // 处理 UTF-8 多字节
  try {
    return decodeURIComponent(escape(str))
  } catch {
    return str
  }
}

/**
 * 创建 SSEClient 实例的便捷方法
 */
export function createSSEClient(baseURL?: string): SSEClient {
  return new SSEClient(baseURL)
}

export default SSEClient
