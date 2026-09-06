// case_ids: UI-009, UI-025
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import MessageInput from '@/components/chat/MessageInput'
import { useChatStore } from '@/store/chat'
import { chatApi } from '@/lib/api'
import { toast } from 'sonner'

// 语音录制 hook 的可控 mock（vi.hoisted 供 vi.mock factory 引用）
const voiceMocks = vi.hoisted(() => ({
  voice: {
    state: 'idle' as string,
    startRecording: vi.fn(),
    stopRecording: vi.fn(),
    cancelRecording: vi.fn(),
    duration: 0,
  },
}))

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
  useVoiceRecorder: vi.fn(() => voiceMocks.voice),
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

// jsdom 无 URL.createObjectURL，组件上传成功后生成 localPreview 需要它；删除草稿图需 revokeObjectURL
Object.defineProperty(URL, 'createObjectURL', {
  writable: true,
  value: vi.fn(() => 'blob:mock-preview'),
})
Object.defineProperty(URL, 'revokeObjectURL', {
  writable: true,
  value: vi.fn(),
})

describe('MessageInput', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    voiceMocks.voice.state = 'idle'
    voiceMocks.voice.duration = 0
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
// UI-025 输入条统一重设计（issue #2952，设计文档 §4.2/§4.4）
// ═══════════════════════════════════════════════════════════════
describe('MessageInput 输入条统一（UI-025）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    voiceMocks.voice.state = 'idle'
    voiceMocks.voice.duration = 0
  })

  it('发送键为 ArrowUp 同形图标（与 C 端 ↑ 一致）', () => {
    render(<MessageInput />)
    expect(screen.getByTitle('发送').querySelector('.lucide-arrow-up')).toBeInTheDocument()
  })

  it('流式中主动作键为 Square 停止图标（与 C 端 ■ 一致）', () => {
    vi.mocked(useChatStore).mockReturnValueOnce({
      currentSessionId: 'sess_test_001',
      sessions: [{ session_id: 'sess_test_001', status: 'active', title: 'Test' }],
      isStreaming: true,
      sendMessage: vi.fn(),
      stopStreaming: vi.fn(),
      createSession: vi.fn(),
    } as any)
    render(<MessageInput />)
    expect(screen.getByTitle('停止生成').querySelector('.lucide-square')).toBeInTheDocument()
  })

  it('语音键为 AudioLines 音波线稿（弃用 Mic）', () => {
    render(<MessageInput />)
    expect(screen.getByTitle('语音输入').querySelector('.lucide-audio-lines')).toBeInTheDocument()
  })

  it('录音中：容器内状态条显示时长与取消提示，placeholder 不被占用', () => {
    voiceMocks.voice.state = 'recording'
    voiceMocks.voice.duration = 7
    render(<MessageInput />)

    expect(screen.getByText(/正在录音/)).toBeInTheDocument()
    expect(screen.getByText(/0:07/)).toBeInTheDocument()
    expect(screen.getByText(/Esc 取消/)).toBeInTheDocument()
    // placeholder 恢复「输入消息…」短句（e2e 选择器依赖此前缀）
    expect(screen.getByPlaceholderText(/输入消息/)).toBeInTheDocument()
  })

  it('转写中 placeholder「转写中...」保持不变', () => {
    voiceMocks.voice.state = 'transcribing'
    render(<MessageInput />)
    expect(screen.getByPlaceholderText(/转写中/)).toBeInTheDocument()
  })

  it('上传中添图键置灰但不换图标（ImagePlus 常驻，进度在预览块）', async () => {
    let resolveUpload!: (v: any) => void
    vi.mocked(chatApi.uploadChatImages).mockReturnValueOnce(
      new Promise((r) => {
        resolveUpload = r
      })
    )
    render(<MessageInput />)

    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    Object.defineProperty(input, 'files', {
      value: [new File(['fake-image-content'], 'photo.png', { type: 'image/png' })],
    })
    fireEvent.change(input)

    const btn = screen.getByTitle('添加图片')
    expect(btn).toBeDisabled()
    expect(btn.querySelector('.lucide-image-plus')).toBeInTheDocument()

    resolveUpload({
      success: true,
      data: {
        files: [{ id: 'f1', url: 'https://cdn.test/f1.png', name: 'photo.png', size: 1024 }],
      },
    })
    await waitFor(() => expect(screen.getByAltText('photo.png')).toBeInTheDocument())
  })

  it('图片预览缩略图内嵌在输入容器内，删除角标常显可点', async () => {
    vi.mocked(chatApi.uploadChatImages).mockResolvedValue({
      success: true,
      data: {
        files: [{ id: 'f1', url: 'https://cdn.test/f1.png', name: 'photo.png', size: 1024 }],
      },
    })
    render(<MessageInput />)
    const zone = screen.getByRole('region', { name: '消息输入区' })
    fireEvent.drop(zone, {
      dataTransfer: { files: [new File(['fake-image-content'], 'photo.png', { type: 'image/png' })] },
    })

    await waitFor(() => {
      // 预览在「消息输入区」容器内（旧版在容器外）
      expect(within(zone).getByAltText('photo.png')).toBeInTheDocument()
    })
    expect(screen.getByLabelText('删除图片')).toBeInTheDocument()
  })

  it('点击删除图片角标可移除草稿图', async () => {
    vi.mocked(chatApi.uploadChatImages).mockResolvedValue({
      success: true,
      data: {
        files: [{ id: 'f1', url: 'https://cdn.test/f1.png', name: 'photo.png', size: 1024 }],
      },
    })
    render(<MessageInput />)
    const zone = screen.getByRole('region', { name: '消息输入区' })
    fireEvent.drop(zone, {
      dataTransfer: { files: [new File(['fake-image-content'], 'photo.png', { type: 'image/png' })] },
    })
    await waitFor(() => expect(within(zone).getByAltText('photo.png')).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText('删除图片'))
    expect(screen.queryByAltText('photo.png')).not.toBeInTheDocument()
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
    voiceMocks.voice.state = 'idle'
    voiceMocks.voice.duration = 0
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
