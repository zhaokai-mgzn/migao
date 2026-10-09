// case_ids: UI-007, UI-013
/**
 * B 端「问黄金策」输入条测试 — 单行 + 键盘/语音切换（issue #6596）
 *
 * 覆盖（UI-007 行为保持 + #6596 结构改判）：
 * - 单行 `[键盘/语音切换][输入框 或「按住说话」][加图][发送]`：**默认语音模式**（中间是「按住说话」）；
 *   点切换图标 ⇒ 输入框；再点 ⇒ 回「按住说话」（结构判据另见 `tests/chat-input-bar-layout.test.ts`）
 * - 按住语音键开始录音（录音条出现）、松开转写直接发送、上滑取消（行为一条没动）
 * - 自适应主动作键：草稿空 = 语音口 / 有草稿 = 发送 / 流式中 = 停止
 * - 添图统一进草稿（预览可删），纯图消息（UI-013）协议不变
 * - 录音不可用时：**浏览器（h5）**保留切换键但点了给显式提示（issue #5650：不许静默消失、
 *   不许「点了没反应」）；**其它未识别目标**不渲染语音入口
 * - 语音转写去向仍是「松开直接发送」（`docs/design/agent-input-bar-unified-design.md` D1 的 B 端既定行为）
 *
 * ## 判据与文案解耦
 *
 * 文案随平台分流（见 `tests/chat-input-surface.test.tsx`）⇒ 行为判据一律用 `aria-label` 定位，
 * 只有专门判文案的用例才写文案字面量。
 */
import React from 'react'
import '@testing-library/jest-dom'
import { render, screen, fireEvent, act } from '@testing-library/react'
import Taro from '@tarojs/taro'
import MessageInput from '../src/components/chat/MessageInput'
import { startRecording, stopAndTranscribe, isVoiceSupported } from '../src/utils/voice'
import { chooseImages, uploadImages } from '../src/utils/imageUpload'
import { H5_VOICE_UNAVAILABLE_HINT } from '../src/utils/platform'

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

/** 切到键盘输入（#6596 起首屏是语音模式；打字前必须先切） */
function toKeyboardMode() {
  fireEvent.click(screen.getByLabelText('切换到键盘输入'))
}

/**
 * 打字：先切键盘模式，再用 `aria-label` 定位输入框 —— 与 placeholder **文案解耦**
 * （文案随平台分流，见 issue #6476；行为判据不该跟着文案抖）
 */
function typeText(text: string) {
  toKeyboardMode()
  fireEvent.change(screen.getByLabelText('消息输入框'), { target: { value: text } })
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

describe('MessageInput — 单行 + 键盘/语音切换（issue #6596）', () => {
  it('默认语音模式：中间是「按住说话」，没有输入框；切换键在', () => {
    renderInput()
    expect(screen.getByLabelText('按住说话')).toBeInTheDocument()
    expect(screen.queryByLabelText('消息输入框')).toBeNull()
    expect(screen.getByLabelText('切换到键盘输入')).toBeInTheDocument()
  })

  it('点键盘图标 ⇒ 输入框（placeholder「发消息或按住说话」）且「按住说话」消失；再点 ⇒ 变回', () => {
    renderInput()
    toKeyboardMode()
    expect(screen.getByLabelText('消息输入框')).toBeInTheDocument()
    expect(screen.queryByLabelText('按住说话')).toBeNull()
    expect(screen.getByPlaceholderText('发消息或按住说话')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('切换到语音输入'))
    expect(screen.queryByLabelText('消息输入框')).toBeNull()
    expect(screen.getByLabelText('按住说话')).toBeInTheDocument()
  })
})

describe('MessageInput — 自适应主动作键', () => {
  it('草稿为空：显示 [切换][按住说话][添图]，无发送键', () => {
    renderInput()
    expect(screen.getByLabelText('添加图片')).toBeInTheDocument()
    expect(screen.getByLabelText('按住说话')).toBeInTheDocument()
    expect(screen.queryByLabelText('发送')).not.toBeInTheDocument()
  })

  it('输入文字后语音键位变为发送键；点发送 → onSend 并清空', () => {
    const { props } = renderInput()
    typeText('你好')

    expect(screen.queryByLabelText('按住说话')).not.toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('发送'))

    expect(props.onSend).toHaveBeenCalledWith('你好')
    expect(screen.getByLabelText('消息输入框')).toHaveValue('')
  })

  it('清空文字后发送键消失，仍留在键盘模式（再点切换键回语音）', () => {
    renderInput()
    typeText('你好')
    expect(screen.queryByLabelText('按住说话')).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('消息输入框'), { target: { value: '' } })
    expect(screen.queryByLabelText('发送')).not.toBeInTheDocument()
    // 模式切换是**显式**的（用户裁定「语音和键盘 icon 可以切换」）⇒ 清空文字不自动跳回语音
    expect(screen.getByLabelText('消息输入框')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('切换到语音输入'))
    expect(screen.getByLabelText('按住说话')).toBeInTheDocument()
  })

  it('流式中：主动作键为停止（onStop），且语音口已失效（按了不录）', () => {
    const { props } = renderInput({ isStreaming: true })
    expect(screen.getByLabelText('按住说话（当前不可用）')).toBeInTheDocument()
    expect(screen.queryByLabelText('按住说话')).not.toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('停止生成'))
    expect(props.onStop).toHaveBeenCalledTimes(1)
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

  it('录音链路抛错（如麦克风未授权）→ toast 那道可行动错误，不发送', async () => {
    mockStopAndTranscribe.mockRejectedValue(new Error('没有麦克风权限：请在浏览器设置里允许后重试'))
    const { props } = renderInput()

    const btn = holdVoice()
    await act(async () => {
      fireEvent.touchEnd(btn, { changedTouches: [{ clientY: 200 }] })
    })

    expect(props.onSend).not.toHaveBeenCalled()
    expect(mockToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: '没有麦克风权限：请在浏览器设置里允许后重试' })
    )
  })

  it('无可发会话（disabled）时按住不开始录音', () => {
    const { container } = renderInput({ disabled: true })
    const hold = container.querySelector('.message-input__hold')
    // 反空跑 + 业务数据：禁用态这个键必须带 `--disabled` 修饰类（取不到 / 类名不对 ⇒ 当场红）
    expect(hold?.className).toContain('message-input__hold--disabled')
    fireEvent.touchStart(hold as HTMLElement, { touches: [{ clientY: 200 }] })
    expect(mockStartRecording).not.toHaveBeenCalled()
  })
})

describe('MessageInput — 录音不可用时的显式出路（issue #5650）', () => {
  it('h5 不支持录音：切换键保留可见，点了给显式提示，键盘路径完整可用', () => {
    ;(isVoiceSupported as jest.Mock).mockReturnValue(false)
    const prevEnv = process.env.TARO_ENV
    const envBag = process.env as unknown as Record<string, string | undefined>
    envBag.TARO_ENV = 'h5'
    try {
      const { props } = renderInput()

      // 不渲染按不动的「按住说话」（#6596：做不到就不摆出来）
      expect(screen.queryByLabelText('按住说话')).toBeNull()

      const voiceBtn = screen.getByLabelText('切换到语音输入')
      expect(voiceBtn).toBeInTheDocument()
      // 降透明度（`.message-input__icon-btn--disabled` 的观感口径），但**仍然可点** —— 点了给解释
      expect(Array.from(voiceBtn.classList)).toContain('message-input__mode-toggle--disabled')

      fireEvent.click(voiceBtn)
      expect(mockToast).toHaveBeenCalledWith({ title: H5_VOICE_UNAVAILABLE_HINT, icon: 'none' })
      expect(mockStartRecording).not.toHaveBeenCalled()

      // 回落文字模式：键盘路径完整可用
      expect(screen.getByLabelText('消息输入框')).toBeInTheDocument()
      fireEvent.change(screen.getByLabelText('消息输入框'), { target: { value: '你好' } })
      fireEvent.click(screen.getByLabelText('发送'))
      expect(props.onSend).toHaveBeenCalledWith('你好')
    } finally {
      if (prevEnv === undefined) delete envBag.TARO_ENV
      else envBag.TARO_ENV = prevEnv
    }
  })

  it('非浏览器目标（编译目标未识别）不支持录音：不渲染「按住说话」，切换键给可行动解释', () => {
    ;(isVoiceSupported as jest.Mock).mockReturnValue(false)
    renderInput()
    // 不摆按不动的「按住说话」（#5650 的底线）
    expect(document.querySelector('.message-input__hold')).toBeNull()
    // 切换键仍在，点了给一句可行动的解释（不是静默消失、也不是「点了没反应」）
    fireEvent.click(screen.getByLabelText('切换到语音输入'))
    expect(mockToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: H5_VOICE_UNAVAILABLE_HINT }),
    )
    expect(screen.getByLabelText('消息输入框')).toBeInTheDocument()
  })
})

describe('MessageInput — 添图统一草稿语义（纯图消息 UI-013）', () => {
  it('选图进草稿：预览出现，发送键同时出现（语音口仍在，两种输入都可用）；点发送 → 上传后发纯图消息', async () => {
    mockChoose.mockResolvedValue(['/tmp/a.jpg'])
    mockUpload.mockResolvedValue([{ id: 'f1', url: 'https://cdn/x/a.jpg', name: 'a.jpg', size: 10 }])
    const { props } = renderInput()

    fireEvent.click(screen.getByLabelText('添加图片'))
    await act(async () => {})

    expect(mockChoose).toHaveBeenCalledTimes(1)
    // 有草稿 ⇒ 发送键出现；语音口与发送键**同处一行**、两者都可用（用户裁定「放一行」）
    expect(screen.getByLabelText('发送')).toBeInTheDocument()
    expect(screen.getByLabelText('按住说话')).toBeInTheDocument()
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

  it('删除草稿图后草稿为空，发送键消失、「按住说话」恢复可按', async () => {
    mockChoose.mockResolvedValue(['/tmp/a.jpg'])
    renderInput()

    fireEvent.click(screen.getByLabelText('添加图片'))
    await act(async () => {})
    expect(screen.getByLabelText('发送')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('删除图片'))
    expect(screen.queryByLabelText('删除图片')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('发送')).not.toBeInTheDocument()
    expect(screen.getByLabelText('按住说话')).toBeInTheDocument()
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
