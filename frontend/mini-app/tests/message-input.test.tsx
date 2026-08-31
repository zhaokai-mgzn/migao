// case_ids: UI-007
/**
 * 小布 C 端输入条测试 — 默认语音模式（按住说话/松开发送）+ 键盘模式切换
 *
 * 覆盖：默认按住说话、⌨️/🎤 模式切换、按住→开始录音、松开→转写发送、
 * 上滑取消、转写失败不发送、流式/无会话禁录、键盘模式发送与停止。
 */
import React from 'react'
import '@testing-library/jest-dom'
import { render, screen, fireEvent, act } from '@testing-library/react'
import Taro from '@tarojs/taro'
import MessageInput from '../src/components/chat/MessageInput'
import { startRecording, stopAndTranscribe } from '../src/utils/voice'

jest.mock('../src/utils/voice', () => ({
  startRecording: jest.fn(),
  stopAndTranscribe: jest.fn(),
}))

jest.mock('../src/utils/imageUpload', () => ({
  chooseImages: jest.fn(),
  uploadImages: jest.fn(),
}))

const mockStartRecording = startRecording as jest.Mock
const mockStopAndTranscribe = stopAndTranscribe as jest.Mock
const mockToast = Taro.showToast as jest.Mock

function renderInput(overrides: Partial<React.ComponentProps<typeof MessageInput>> = {}) {
  const props = {
    onSend: jest.fn(),
    onStop: jest.fn(),
    isStreaming: false,
    disabled: false,
    ...overrides,
  }
  return { ...render(<MessageInput {...props} />), props }
}

/** 按住说话按钮的触摸序列（起点 y=200，不上滑） */
function holdAndRelease(clientY = 200) {
  const btn = screen.getByText('按住 说话')
  fireEvent.touchStart(btn, { touches: [{ clientY: 200 }] })
  fireEvent.touchEnd(btn, { changedTouches: [{ clientY }] })
}

beforeEach(() => {
  jest.clearAllMocks()
})

describe('MessageInput — 语音/键盘双模式', () => {
  it('默认语音模式：渲染「按住 说话」，无 textarea，切换键为 ⌨️', () => {
    renderInput()
    expect(screen.getByText('按住 说话')).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('输入您的问题...')).not.toBeInTheDocument()
    expect(screen.getByText('⌨️')).toBeInTheDocument()
  })

  it('点击 ⌨️ 切到键盘模式（textarea 出现），再点 🎤 切回语音', () => {
    renderInput()
    fireEvent.click(screen.getByText('⌨️'))
    expect(screen.getByPlaceholderText('输入您的问题...')).toBeInTheDocument()
    expect(screen.queryByText('按住 说话')).not.toBeInTheDocument()
    expect(screen.getByText('🎤')).toBeInTheDocument()

    fireEvent.click(screen.getByText('🎤'))
    expect(screen.getByText('按住 说话')).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('输入您的问题...')).not.toBeInTheDocument()
  })

  it('按住开始录音，松开转写后直接发送文本', async () => {
    mockStopAndTranscribe.mockResolvedValue({ text: '我要查订单', durationMs: 1200 })
    const { props } = renderInput()

    const btn = screen.getByText('按住 说话')
    fireEvent.touchStart(btn, { touches: [{ clientY: 200 }] })
    expect(mockStartRecording).toHaveBeenCalledTimes(1)

    await act(async () => {
      fireEvent.touchEnd(btn, { changedTouches: [{ clientY: 200 }] })
    })

    expect(mockStopAndTranscribe).toHaveBeenCalledTimes(1)
    expect(props.onSend).toHaveBeenCalledWith('我要查订单')
  })

  it('上滑超过阈值松开 → 取消，不转写不发送', async () => {
    const { props } = renderInput()

    const btn = screen.getByText('按住 说话')
    fireEvent.touchStart(btn, { touches: [{ clientY: 200 }] })
    fireEvent.touchMove(btn, { touches: [{ clientY: 100 }] }) // 上滑 100px
    await act(async () => {
      fireEvent.touchEnd(btn, { changedTouches: [{ clientY: 100 }] })
    })

    expect(mockStopAndTranscribe).not.toHaveBeenCalled()
    expect(props.onSend).not.toHaveBeenCalled()
  })

  it('转写失败（null）→ toast「未听清」，不发送', async () => {
    mockStopAndTranscribe.mockResolvedValue(null)
    const { props } = renderInput()

    await act(async () => {
      holdAndRelease()
    })

    expect(props.onSend).not.toHaveBeenCalled()
    expect(mockToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: '未听清，请重试' })
    )
  })

  it('流式输出中按住不开始录音', () => {
    renderInput({ isStreaming: true })
    fireEvent.touchStart(screen.getByText('按住 说话'), { touches: [{ clientY: 200 }] })
    expect(mockStartRecording).not.toHaveBeenCalled()
  })

  it('无可发会话（disabled）时按住不开始录音', () => {
    renderInput({ disabled: true })
    fireEvent.touchStart(screen.getByText('按住 说话'), { touches: [{ clientY: 200 }] })
    expect(mockStartRecording).not.toHaveBeenCalled()
  })

  it('键盘模式：输入文字点发送 → onSend，发送后清空', () => {
    const { props } = renderInput()
    fireEvent.click(screen.getByText('⌨️'))

    const textarea = screen.getByPlaceholderText('输入您的问题...')
    fireEvent.change(textarea, { target: { value: '你好' } })
    fireEvent.click(screen.getByText('↑'))

    expect(props.onSend).toHaveBeenCalledWith('你好')
    expect(textarea).toHaveValue('')
  })

  it('键盘模式流式中显示停止按钮，点击触发 onStop', () => {
    const { props } = renderInput({ isStreaming: true })
    fireEvent.click(screen.getByText('⌨️'))

    const stopBtn = screen.getByText('■')
    fireEvent.click(stopBtn)
    expect(props.onStop).toHaveBeenCalled()
  })
})
