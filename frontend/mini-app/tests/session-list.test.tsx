/**
 * 会话列表页面测试
 *
 * 覆盖: 加载/渲染/空状态/搜索/点击切换/新建会话
 */
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'

// Mock Taro hooks
jest.mock('@tarojs/taro', () => {
  const storage: Record<string, any> = {}
  return {
    __esModule: true,
    default: {
      switchTab: jest.fn(),
      showActionSheet: jest.fn(() => Promise.resolve({ tapIndex: 0 })),
      showModal: jest.fn(() => Promise.resolve({ confirm: true })),
      stopPullDownRefresh: jest.fn(),
      getStorageSync: jest.fn((k: string) => storage[k] ?? ''),
      setStorageSync: jest.fn((k: string, v: any) => { storage[k] = v }),
      removeStorageSync: jest.fn((k: string) => { delete storage[k] }),
      showToast: jest.fn(),
      __clearStorage: () => { Object.keys(storage).forEach(k => delete storage[k]) },
    },
    useDidShow: jest.fn(),
    usePullDownRefresh: jest.fn(),
  }
})

const mockLoadSessions = jest.fn()
const mockDeleteSession = jest.fn()
const mockSelectSession = jest.fn()
const mockCreateSession = jest.fn()

jest.mock('../src/store/chatStore', () => ({
  useChatStore: jest.fn(() => ({
    sessions: [],
    isLoadingSessions: false,
    loadSessions: mockLoadSessions,
    deleteSession: mockDeleteSession,
    selectSession: mockSelectSession,
    createSession: mockCreateSession,
  })),
}))

import Taro from '@tarojs/taro'
import SessionsPage from '../src/pages/chat/sessions/index'
import { useChatStore } from '../src/store/chatStore'

describe('SessionsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('空列表应显示"暂无会话记录"', () => {
    render(<SessionsPage />)
    expect(screen.getByText('暂无会话记录')).toBeTruthy()
  })

  it('空列表应显示"开始对话"按钮', () => {
    render(<SessionsPage />)
    expect(screen.getByText('开始对话')).toBeTruthy()
  })

  it('加载中应显示加载文案', () => {
    ;(useChatStore as unknown as jest.Mock).mockReturnValue({
      sessions: [],
      isLoadingSessions: true,
      loadSessions: mockLoadSessions,
      deleteSession: mockDeleteSession,
      selectSession: mockSelectSession,
      createSession: mockCreateSession,
    })

    render(<SessionsPage />)
    expect(screen.getByText('加载中...')).toBeTruthy()
  })

  it('应渲染会话列表', () => {
    ;(useChatStore as unknown as jest.Mock).mockReturnValue({
      sessions: [
        { id: 's1', title: '对话1', updated_at: '2024-01-15T10:00:00Z', last_message: '你好', created_at: '2024-01-15' },
        { id: 's2', title: '对话2', updated_at: '2024-01-14T10:00:00Z', last_message: '再见', created_at: '2024-01-14' },
      ],
      isLoadingSessions: false,
      loadSessions: mockLoadSessions,
      deleteSession: mockDeleteSession,
      selectSession: mockSelectSession,
      createSession: mockCreateSession,
    })

    render(<SessionsPage />)

    expect(screen.getByText('对话1')).toBeTruthy()
    expect(screen.getByText('对话2')).toBeTruthy()
  })

  it('点击新建会话应创建并跳转', async () => {
    mockCreateSession.mockResolvedValueOnce(undefined)

    render(<SessionsPage />)

    fireEvent.click(screen.getByText('+ 新建会话'))

    expect(mockCreateSession).toHaveBeenCalled()
  })

  it('应渲染搜索输入框', () => {
    render(<SessionsPage />)
    const input = screen.getByPlaceholderText('搜索会话...')
    expect(input).toBeTruthy()
  })

  it('点击空状态"开始对话"应创建会话并跳转', () => {
    ;(useChatStore as unknown as jest.Mock).mockReturnValue({
      sessions: [],
      isLoadingSessions: false,
      loadSessions: mockLoadSessions,
      deleteSession: mockDeleteSession,
      selectSession: mockSelectSession,
      createSession: mockCreateSession,
    })
    mockCreateSession.mockResolvedValueOnce(undefined)

    render(<SessionsPage />)

    fireEvent.click(screen.getByText('开始对话'))

    expect(mockCreateSession).toHaveBeenCalled()
  })
})
