// case_ids: UI-009
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import MessageInput from '@/components/chat/MessageInput'
import { useChatStore } from '@/store/chat'
import { chatApi } from '@/lib/api'
import { toast } from 'sonner'

// Mock stores
vi.mock('@/store/chat', () => ({
  useChatStore: vi.fn(() => ({
    currentSessionId: 'sess_test_001',
    sessions: [
      { session_id: 'sess_test_001', status: 'active', title: 'Test' },
    ],
    isStreaming: false,
    sendMessage: vi.fn(),
    stopStreaming: vi.fn(),
    createSession: vi.fn(),
  })),
}))

vi.mock('@/store/auth', () => ({
  useAuthStore: { getState: vi.fn(() => ({ accessToken: 'mock-token' })) },
}))

vi.mock('@/hooks/useVoiceRecorder', () => ({
  useVoiceRecorder: vi.fn(() => ({
    state: 'idle',
    startRecording: vi.fn(),
    stopRecording: vi.fn(),
    cancelRecording: vi.fn(),
    duration: 0,
  })),
}))

vi.mock('@/lib/api', () => ({
  chatApi: {
    uploadChatImages: vi.fn(),
    transcribeAudio: vi.fn(),
  },
}))

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

vi.mock('next/image', () => ({
  default: ({ src, alt, ...props }: any) =>
    React.createElement('img', { src, alt, ...props }),
}))

// jsdom 无 URL.createObjectURL，组件上传成功后生成 localPreview 需要它
Object.defineProperty(URL, 'createObjectURL', {
  writable: true,
  value: vi.fn(() => 'blob:mock-preview'),
})

describe('MessageInput', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders textarea input placeholder', () => {
    render(<MessageInput />)
    const textarea = screen.getByPlaceholderText(/输入消息/)
    expect(textarea).toBeInTheDocument()
  })

  it('renders send button', () => {
    render(<MessageInput />)
    const sendButton = screen.getByTitle('发送')
    expect(sendButton).toBeInTheDocument()
  })

  it('renders action buttons including send', () => {
    render(<MessageInput />)
    // Send button is always present with title="发送"
    expect(screen.getByTitle('发送')).toBeInTheDocument()
    // Total buttons (some may use lucide-react which can affect JSDOM role detection)
    const buttons = document.querySelectorAll('button')
    expect(buttons.length).toBeGreaterThanOrEqual(2)
  })

  it('renders a textarea that is enabled when session active', () => {
    render(<MessageInput />)
    const textarea = screen.getByPlaceholderText(/输入消息/)
    expect(textarea).not.toBeDisabled()
  })

  it('renders AI disclaimer text', () => {
    render(<MessageInput />)
    expect(screen.getByText('AI 生成内容仅供参考')).toBeInTheDocument()
  })
})

// ═══════════════════════════════════════════════════════════════
// UI-009 拖拽图片上传（附件）
// ═══════════════════════════════════════════════════════════════
describe('MessageInput 拖拽图片上传（UI-009）', () => {
  const makeImageFile = (name = 'photo.png', size = 1024) => {
    const file = new File(['fake-image-content'], name, { type: 'image/png' })
    Object.defineProperty(file, 'size', { value: size })
    return file
  }

  const uploadResolved = {
    success: true,
    data: {
      files: [{ id: 'f1', url: 'https://cdn.test/f1.png', name: 'photo.png', size: 1024 }],
    },
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('拖拽图片到输入区应触发上传并显示预览', async () => {
    const uploadMock = vi.mocked(chatApi.uploadChatImages).mockResolvedValue(uploadResolved)
    render(<MessageInput />)
    const zone = screen.getByRole('region', { name: '消息输入区' })

    fireEvent.drop(zone, { dataTransfer: { files: [makeImageFile()] } })

    await waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByAltText('photo.png')).toBeInTheDocument())
  })

  it('拖拽悬停时显示高亮提示，离开后消失', () => {
    render(<MessageInput />)
    const zone = screen.getByRole('region', { name: '消息输入区' })

    fireEvent.dragOver(zone, { dataTransfer: { types: ['Files'] } })
    expect(screen.getByText('松开上传图片')).toBeInTheDocument()

    fireEvent.dragLeave(zone)
    expect(screen.queryByText('松开上传图片')).not.toBeInTheDocument()
  })

  it('拖拽非图片文件应拒绝并提示', async () => {
    const uploadMock = vi.mocked(chatApi.uploadChatImages)
    render(<MessageInput />)
    const zone = screen.getByRole('region', { name: '消息输入区' })

    const txtFile = new File(['hello'], 'note.txt', { type: 'text/plain' })
    fireEvent.drop(zone, { dataTransfer: { files: [txtFile] } })

    expect(toast.error).toHaveBeenCalledWith('不支持的文件类型: note.txt')
    expect(uploadMock).not.toHaveBeenCalled()
  })

  it('拖拽超过 5MB 的图片应拒绝并提示', async () => {
    const uploadMock = vi.mocked(chatApi.uploadChatImages)
    render(<MessageInput />)
    const zone = screen.getByRole('region', { name: '消息输入区' })

    const bigFile = makeImageFile('big.png', 6 * 1024 * 1024)
    fireEvent.drop(zone, { dataTransfer: { files: [bigFile] } })

    expect(toast.error).toHaveBeenCalledWith('文件 big.png 超过 5MB 限制')
    expect(uploadMock).not.toHaveBeenCalled()
  })

  it('已满 3 张时拖拽应提示上限且不再上传', async () => {
    const uploadMock = vi.mocked(chatApi.uploadChatImages).mockResolvedValue(uploadResolved)
    render(<MessageInput />)
    const zone = screen.getByRole('region', { name: '消息输入区' })

    // 分次拖入（等待每次上传完成，模拟真实交互节奏）
    for (let i = 0; i < 3; i++) {
      fireEvent.drop(zone, { dataTransfer: { files: [makeImageFile(`p${i}.png`)] } })
      await waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(i + 1))
    }

    fireEvent.drop(zone, { dataTransfer: { files: [makeImageFile('p4.png')] } })
    expect(toast.error).toHaveBeenCalledWith('最多上传 3 张图片')
    expect(uploadMock).toHaveBeenCalledTimes(3)
  })

  it('会话已关闭时拖拽不生效', async () => {
    const uploadMock = vi.mocked(chatApi.uploadChatImages).mockResolvedValue(uploadResolved)
    const chatStoreMock = vi.mocked(useChatStore)
    chatStoreMock.mockReturnValueOnce({
      currentSessionId: 'sess_test_001',
      sessions: [{ session_id: 'sess_test_001', status: 'closed', title: 'Test' }],
      isStreaming: false,
      sendMessage: vi.fn(),
      stopStreaming: vi.fn(),
      createSession: vi.fn(),
    })
    render(<MessageInput />)
    const zone = screen.getByRole('region', { name: '消息输入区' })

    fireEvent.drop(zone, { dataTransfer: { files: [makeImageFile()] } })

    expect(uploadMock).not.toHaveBeenCalled()
  })
})
