// case_ids: UI-007, UI-013
/**
 * 小布 C 端输入条测试 — 单容器双语义（textarea 常驻 + 右下按住说话）
 *
 * 覆盖（UI-007 修订后交互结构，松开直接发送行为保持）：
 * - textarea 常驻（placeholder「发消息或按住说话」），无键盘/语音模式切换键
 * - 按住语音键开始录音（录音条出现）、松开转写直接发送、上滑取消
 * - 自适应主动作键：草稿空=按住说话、有草稿=发送、流式中=停止
 * - 添图统一进草稿（预览可删），纯图消息（UI-013）协议不变
 * - H5 不支持录音时语音键隐藏，键盘路径完整可用
 */
import React from 'react'
import '@testing-library/jest-dom'
import { render, screen, fireEvent, act } from '@testing-library/react'
import Taro from '@tarojs/taro'
import MessageInput from '../src/components/chat/MessageInput'
import { startRecording, stopAndTranscribe, isVoiceSupported } from '../src/utils/voice'
import { chooseImages, uploadImages } from '../src/utils/imageUpload'

jest.mock('../src/utils/voice', () => ({
  startRecording: jest.fn(),
  stopAndTranscribe: jest.fn(),
  isVoiceSupported: jest.fn(() => true),
}))

jest.mock('../src/utils/imageUpload', () => ({
  chooseImages: jest.fn(),
  uploadImages: jest.fn(),
}))

const mockStartRecording = startRecording as jest.Mock
const mockStopAndTranscribe = stopAndTranscribe as jest.Mock
const mockChoose = chooseImages as jest.Mock
const mockUpload = uploadImages as jest.Mock
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

function typeText(text: string) {
  fireEvent.change(screen.getByPlaceholderText('发消息或按住说话'), { target: { value: text } })
}

/** 按住语音键（起点 y=200）并返回按钮元素 */
function holdVoice() {
  const btn = screen.getByLabelText('按住说话')
  fireEvent.touchStart(btn, { touches: [{ clientY: 200 }] })
  return btn
}

beforeEach(() => {
  jest.clearAllMocks()
  ;(isVoiceSupported as jest.Mock).mockReturnValue(true)
})

describe('MessageInput — 单容器（textarea 常驻，无模式切换）', () => {
  it('textarea 常驻：placeholder「发消息或按住说话」，无键盘/语音切换键', () => {
    renderInput()
    expect(screen.getByPlaceholderText('发消息或按住说话')).toBeInTheDocument()
    expect(screen.queryByText('🎤')).not.toBeInTheDocument()
    expect(screen.queryByText('⌨️')).not.toBeInTheDocument()
  })

  it('草稿为空：右下显示 [添图][按住说话]，无发送键', () => {
    renderInput()
    expect(screen.getByLabelText('添加图片')).toBeInTheDocument()
    expect(screen.getByLabelText('按住说话')).toBeInTheDocument()
    expect(screen.queryByLabelText('发送')).not.toBeInTheDocument()
  })

  it('H5 不支持录音：无语音键，textarea 常驻且键盘路径完整', () => {
    ;(isVoiceSupported as jest.Mock).mockReturnValue(false)
    const { props } = renderInput()
    expect(screen.queryByLabelText('按住说话')).not.toBeInTheDocument()
    typeText('你好')
    fireEvent.click(screen.getByLabelText('发送'))
    expect(props.onSend).toHaveBeenCalledWith('你好')
  })
})

describe('MessageInput — 语音（按住说话，松开直接发送行为保持）', () => {
  it('按住开始录音（录音条出现），松开转写后直接发送文本', async () => {
    mockStopAndTranscribe.mockResolvedValue({ text: '我要查订单', durationMs: 1200 })
    const { props } = renderInput()

    const btn = holdVoice()
    expect(mockStartRecording).toHaveBeenCalledTimes(1)
    expect(screen.getByText('正在说话，松开发送')).toBeInTheDocument()

    await act(async () => {
      fireEvent.touchEnd(btn, { changedTouches: [{ clientY: 200 }] })
    })

    expect(mockStopAndTranscribe).toHaveBeenCalledTimes(1)
    expect(props.onSend).toHaveBeenCalledWith('我要查订单')
    // 录音条随录音结束消失
    expect(screen.queryByText('正在说话，松开发送')).not.toBeInTheDocument()
  })

  it('上滑超过阈值：录音条变取消提示，松开不转写不发送', async () => {
    const { props } = renderInput()

    const btn = holdVoice()
    fireEvent.touchMove(btn, { touches: [{ clientY: 100 }] }) // 上滑 100px
    expect(screen.getByText('松开手指，取消发送')).toBeInTheDocument()

    await act(async () => {
      fireEvent.touchEnd(btn, { changedTouches: [{ clientY: 100 }] })
    })

    expect(mockStopAndTranscribe).not.toHaveBeenCalled()
    expect(props.onSend).not.toHaveBeenCalled()
  })

  it('转写失败（null）→ toast「未听清」，不发送', async () => {
    mockStopAndTranscribe.mockResolvedValue(null)
    const { props } = renderInput()

    const btn = holdVoice()
    await act(async () => {
      fireEvent.touchEnd(btn, { changedTouches: [{ clientY: 200 }] })
    })

    expect(props.onSend).not.toHaveBeenCalled()
    expect(mockToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: '未听清，请重试' })
    )
  })

  it('无可发会话（disabled）时按住不开始录音', () => {
    renderInput({ disabled: true })
    fireEvent.touchStart(screen.getByLabelText('按住说话'), { touches: [{ clientY: 200 }] })
    expect(mockStartRecording).not.toHaveBeenCalled()
  })
})

describe('MessageInput — 自适应主动作键', () => {
  it('输入文字后语音键位变为发送键；点发送 → onSend 并清空', () => {
    const { props } = renderInput()
    typeText('你好')

    expect(screen.queryByLabelText('按住说话')).not.toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('发送'))

    expect(props.onSend).toHaveBeenCalledWith('你好')
    expect(screen.getByPlaceholderText('发消息或按住说话')).toHaveValue('')
  })

  it('清空文字后恢复按住说话键', () => {
    renderInput()
    typeText('你好')
    expect(screen.queryByLabelText('按住说话')).not.toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('发消息或按住说话'), { target: { value: '' } })
    expect(screen.getByLabelText('按住说话')).toBeInTheDocument()
  })

  it('流式中：主动作键为停止（onStop），且无语音键无法录音', () => {
    const { props } = renderInput({ isStreaming: true })
    expect(screen.queryByLabelText('按住说话')).not.toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('停止生成'))
    expect(props.onStop).toHaveBeenCalledTimes(1)
  })
})

describe('MessageInput — 添图统一草稿语义（纯图消息 UI-013）', () => {
  it('选图进草稿：预览出现，语音键变发送；点发送 → 上传后发纯图消息', async () => {
    mockChoose.mockResolvedValue(['/tmp/a.jpg'])
    mockUpload.mockResolvedValue([{ id: 'f1', url: 'https://cdn/x/a.jpg', name: 'a.jpg', size: 10 }])
    const { props } = renderInput()

    fireEvent.click(screen.getByLabelText('添加图片'))
    await act(async () => {})

    expect(mockChoose).toHaveBeenCalledTimes(1)
    expect(screen.queryByLabelText('按住说话')).not.toBeInTheDocument()
    expect(screen.getByLabelText('删除图片')).toBeInTheDocument()

    await act(async () => {
      fireEvent.click(screen.getByLabelText('发送'))
    })

    expect(mockUpload).toHaveBeenCalledWith(['/tmp/a.jpg'])
    expect(props.onSend).toHaveBeenCalledWith('', ['https://cdn/x/a.jpg'])
  })

  it('有文字有图：发送同时携带文本与图片', async () => {
    mockChoose.mockResolvedValue(['/tmp/a.jpg'])
    mockUpload.mockResolvedValue([{ url: 'https://cdn/x/a.jpg' }])
    const { props } = renderInput()

    typeText('这款窗帘有吗')
    fireEvent.click(screen.getByLabelText('添加图片'))
    await act(async () => {})

    await act(async () => {
      fireEvent.click(screen.getByLabelText('发送'))
    })

    expect(props.onSend).toHaveBeenCalledWith('这款窗帘有吗', ['https://cdn/x/a.jpg'])
  })

  it('删除草稿图后恢复语音键，草稿为空', async () => {
    mockChoose.mockResolvedValue(['/tmp/a.jpg'])
    renderInput()

    fireEvent.click(screen.getByLabelText('添加图片'))
    await act(async () => {})
    expect(screen.queryByLabelText('按住说话')).not.toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('删除图片'))
    expect(screen.getByLabelText('按住说话')).toBeInTheDocument()
    expect(screen.queryByLabelText('删除图片')).not.toBeInTheDocument()
  })

  it('取消选图：不产生草稿，不发送', async () => {
    mockChoose.mockResolvedValue([])
    const { props } = renderInput()

    fireEvent.click(screen.getByLabelText('添加图片'))
    await act(async () => {})

    expect(screen.getByLabelText('按住说话')).toBeInTheDocument()
    expect(props.onSend).not.toHaveBeenCalled()
  })
})
