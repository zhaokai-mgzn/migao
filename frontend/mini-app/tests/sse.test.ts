/**
 * SSE 流式客户端测试
 *
 * 覆盖: SSE 事件解析、各事件类型分发、取消、降级模式、心跳忽略
 */
import { SSEClient, createSSEClient } from '../src/utils/sse'
import type { SSECallbacks } from '../src/utils/sse'

// Mock auth 模块
jest.mock('../src/utils/auth', () => ({
  getToken: jest.fn(() => 'test-token'),
}))

// Mock Taro.request 以控制 SSE 行为
jest.mock('@tarojs/taro', () => {
  const storage: Record<string, any> = {}
  return {
    __esModule: true,
    default: {
      getStorageSync: jest.fn((key: string) => storage[key] ?? ''),
      setStorageSync: jest.fn((key: string, value: any) => { storage[key] = value }),
      removeStorageSync: jest.fn((key: string) => { delete storage[key] }),
      request: jest.fn(),
      showToast: jest.fn(),
      __clearStorage: () => { Object.keys(storage).forEach(k => delete storage[k]) },
    },
  }
})

import Taro from '@tarojs/taro'

describe('SSEClient', () => {
  let client: SSEClient
  let callbacks: SSECallbacks

  beforeEach(() => {
    jest.clearAllMocks()
    jest.useFakeTimers()
    client = new SSEClient('http://localhost:8001')

    callbacks = {
      onText: jest.fn(),
      onToolCall: jest.fn(),
      onToolResult: jest.fn(),
      onCard: jest.fn(),
      onLoading: jest.fn(),
      onDone: jest.fn(),
      onError: jest.fn(),
    }
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  // ========== 增量 SSE 解析 ==========

  describe('parseSSEBufferIncremental (via sendMessage)', () => {
    it('应解析 text 事件', () => {
      // 模拟 Taro.request 的 success 回调
      ;(Taro.request as jest.Mock).mockImplementation((options: any) => {
        // 触发 success 回调
        setTimeout(() => {
          options.success({
            statusCode: 200,
            data: 'event: text\ndata: {"content":"你好"}\n\n',
          })
        }, 0)
        return { abort: jest.fn(), onChunkReceived: undefined }
      })

      client.sendMessage('session-1', '你好', callbacks)

      // 执行微任务
      jest.runAllTimers()

      expect(callbacks.onText).toHaveBeenCalledWith({ content: '你好' })
    })

    it('应解析 done 事件', () => {
      ;(Taro.request as jest.Mock).mockImplementation((options: any) => {
        setTimeout(() => {
          options.success({
            statusCode: 200,
            data: 'event: done\ndata: {"session_id":"s1","message_id":"m1"}\n\n',
          })
        }, 0)
        return { abort: jest.fn(), onChunkReceived: undefined }
      })

      client.sendMessage('s1', 'test', callbacks)
      jest.runAllTimers()

      expect(callbacks.onDone).toHaveBeenCalledWith({
        session_id: 's1',
        message_id: 'm1',
      })
    })

    it('应解析 tool_call 事件', () => {
      ;(Taro.request as jest.Mock).mockImplementation((options: any) => {
        setTimeout(() => {
          options.success({
            statusCode: 200,
            data: 'event: tool_call\ndata: {"tool":"search_product","args":{"keyword":"窗帘"}}\n\n',
          })
        }, 0)
        return { abort: jest.fn(), onChunkReceived: undefined }
      })

      client.sendMessage('s1', '搜索窗帘', callbacks)
      jest.runAllTimers()

      expect(callbacks.onToolCall).toHaveBeenCalledWith({
        tool: 'search_product',
        args: { keyword: '窗帘' },
      })
    })

    it('应解析 error 事件', () => {
      ;(Taro.request as jest.Mock).mockImplementation((options: any) => {
        setTimeout(() => {
          options.success({
            statusCode: 200,
            data: 'event: error\ndata: {"message":"服务异常","code":"500"}\n\n',
          })
        }, 0)
        return { abort: jest.fn(), onChunkReceived: undefined }
      })

      client.sendMessage('s1', 'test', callbacks)
      jest.runAllTimers()

      expect(callbacks.onError).toHaveBeenCalledWith({
        message: '服务异常',
        code: '500',
      })
    })

    it('应解析 card 事件', () => {
      ;(Taro.request as jest.Mock).mockImplementation((options: any) => {
        setTimeout(() => {
          options.success({
            statusCode: 200,
            data: 'event: card\ndata: {"type":"product_list","data":{"products":[]}}\n\n',
          })
        }, 0)
        return { abort: jest.fn(), onChunkReceived: undefined }
      })

      client.sendMessage('s1', 'test', callbacks)
      jest.runAllTimers()

      expect(callbacks.onCard).toHaveBeenCalledWith({
        type: 'product_list',
        data: { products: [] },
      })
    })

    it('应解析 loading 事件', () => {
      ;(Taro.request as jest.Mock).mockImplementation((options: any) => {
        setTimeout(() => {
          options.success({
            statusCode: 200,
            data: 'event: loading\ndata: {"content":"正在搜索..."}\n\n',
          })
        }, 0)
        return { abort: jest.fn(), onChunkReceived: undefined }
      })

      client.sendMessage('s1', 'test', callbacks)
      jest.runAllTimers()

      expect(callbacks.onLoading).toHaveBeenCalledWith({ content: '正在搜索...' })
    })

    it('应忽略心跳注释行', () => {
      ;(Taro.request as jest.Mock).mockImplementation((options: any) => {
        setTimeout(() => {
          options.success({
            statusCode: 200,
            data: ': heartbeat\nevent: text\ndata: {"content":"hello"}\n\n',
          })
        }, 0)
        return { abort: jest.fn(), onChunkReceived: undefined }
      })

      client.sendMessage('s1', 'test', callbacks)
      jest.runAllTimers()

      expect(callbacks.onText).toHaveBeenCalledWith({ content: 'hello' })
    })

    it('应处理多事件流', () => {
      const sseData = [
        'event: text',
        'data: {"content":"你好"}',
        '',
        'event: text',
        'data: {"content":"，我是AI客服"}',
        '',
        'event: done',
        'data: {"session_id":"s1","message_id":"m1"}',
        '',
      ].join('\n')

      ;(Taro.request as jest.Mock).mockImplementation((options: any) => {
        setTimeout(() => {
          options.success({ statusCode: 200, data: sseData })
        }, 0)
        return { abort: jest.fn(), onChunkReceived: undefined }
      })

      client.sendMessage('s1', 'test', callbacks)
      jest.runAllTimers()

      expect(callbacks.onText).toHaveBeenCalledTimes(2)
      expect(callbacks.onDone).toHaveBeenCalledTimes(1)
    })
  })

  // ========== 错误处理 ==========

  describe('错误处理', () => {
    it('HTTP 非 200 应触发 onError', () => {
      ;(Taro.request as jest.Mock).mockImplementation((options: any) => {
        setTimeout(() => {
          options.success({ statusCode: 500, data: '' })
        }, 0)
        return { abort: jest.fn(), onChunkReceived: undefined }
      })

      client.sendMessage('s1', 'test', callbacks)
      jest.runAllTimers()

      expect(callbacks.onError).toHaveBeenCalledWith(
        expect.objectContaining({ message: expect.stringContaining('500') }),
      )
    })

    it('请求失败应触发 onError', () => {
      ;(Taro.request as jest.Mock).mockImplementation((options: any) => {
        setTimeout(() => {
          options.fail({ errMsg: 'request:fail timeout' })
        }, 0)
        return { abort: jest.fn(), onChunkReceived: undefined }
      })

      client.sendMessage('s1', 'test', callbacks)
      jest.runAllTimers()

      expect(callbacks.onError).toHaveBeenCalledWith(
        expect.objectContaining({ message: expect.stringContaining('timeout') }),
      )
    })

    it('JSON 响应错误应触发 onError', () => {
      ;(Taro.request as jest.Mock).mockImplementation((options: any) => {
        setTimeout(() => {
          options.success({
            statusCode: 200,
            data: { success: false, error: { message: '会话不存在' } },
          })
        }, 0)
        return { abort: jest.fn(), onChunkReceived: undefined }
      })

      client.sendMessage('s1', 'test', callbacks)
      jest.runAllTimers()

      expect(callbacks.onError).toHaveBeenCalledWith(
        expect.objectContaining({ message: '会话不存在' }),
      )
    })
  })

  // ========== 取消请求 ==========

  describe('abort', () => {
    it('abort 后不应再触发回调', () => {
      const abortFn = jest.fn()

      ;(Taro.request as jest.Mock).mockImplementation((options: any) => {
        setTimeout(() => {
          options.success({
            statusCode: 200,
            data: 'event: text\ndata: {"content":"hello"}\n\n',
          })
        }, 100)
        return { abort: abortFn, onChunkReceived: undefined }
      })

      client.sendMessage('s1', 'test', callbacks)
      client.abort()

      jest.runAllTimers()

      // 因为 aborted = true，回调不应触发
      expect(callbacks.onText).not.toHaveBeenCalled()
      expect(abortFn).toHaveBeenCalled()
    })
  })

  // ========== 工厂函数 ==========

  describe('createSSEClient', () => {
    it('应创建 SSEClient 实例', () => {
      const instance = createSSEClient('http://test.com')
      expect(instance).toBeInstanceOf(SSEClient)
    })

    it('无参数时使用默认 baseURL', () => {
      const instance = createSSEClient()
      expect(instance).toBeInstanceOf(SSEClient)
    })
  })
})
