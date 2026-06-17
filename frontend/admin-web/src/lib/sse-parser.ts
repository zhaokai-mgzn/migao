/**
 * SSE (Server-Sent Events) 解析器
 * 
 * 负责解析 SSE 流数据，将协议解析与状态管理分离
 */

export interface SSEEvent {
  event: string
  data: any
}

export type SSEEventHandler = (event: SSEEvent) => void

export class SSEParser {
  private buffer: string = ''
  private currentEventType: string = ''
  private handler: SSEEventHandler

  constructor(handler: SSEEventHandler) {
    this.handler = handler
  }

  /**
   * 解析新的数据块
   * @param chunk - 从流中读取的数据块
   */
  parse(chunk: string): void {
    this.buffer += chunk
    const lines = this.buffer.split('\n')
    this.buffer = lines.pop() || ''

    for (const line of lines) {
      this.processLine(line)
    }
  }

  /**
   * 处理单行数据
   */
  private processLine(line: string): void {
    const trimmedLine = line.trim()

    if (trimmedLine.startsWith('event: ')) {
      this.currentEventType = trimmedLine.substring(7).trim()
      return
    }

    if (trimmedLine.startsWith('data: ')) {
      const dataStr = trimmedLine.substring(6)
      this.emitEvent(dataStr)
      this.currentEventType = ''
      return
    }

    // 空行分隔事件，重置
    if (trimmedLine === '') {
      this.currentEventType = ''
    }
  }

  /**
   * 触发事件
   */
  private emitEvent(dataStr: string): void {
    try {
      const data = JSON.parse(dataStr)
      this.handler({
        event: this.currentEventType,
        data,
      })
    } catch (e) {
      // 非 JSON 数据，直接传递原始字符串
      this.handler({
        event: this.currentEventType,
        data: dataStr,
      })
    }
  }

  /**
   * 重置解析器状态
   */
  reset(): void {
    this.buffer = ''
    this.currentEventType = ''
  }
}

/**
 * 解析 SSE 事件数据
 * @param dataStr - JSON 字符串或原始数据
 * @returns 解析后的数据对象或原始字符串
 */
export function parseSSEData(dataStr: string): any {
  try {
    return JSON.parse(dataStr)
  } catch (e) {
    return dataStr
  }
}
