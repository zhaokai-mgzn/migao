import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import MessageInput from '@/components/chat/MessageInput'

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
  default: (props: Record<string, unknown>) => {
    // eslint-disable-next-line @next/next/no-img-element
    return { type: 'img', props: { ...props, alt: props.alt || '' } }
  },
}))

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
