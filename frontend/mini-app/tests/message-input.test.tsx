// case_ids: UI-007, UI-013
/**
 * 小布 C 端输入条测试 — 单容器双语义（textarea 常驻 + 右下按住说话）
 *
 * 覆盖（UI-007 修订后交互结构，松开直接发送行为保持）：
 * - textarea 常驻（语音优先 placeholder「按住说话，也可以打字」），无键盘/语音模式切换键
 * - 语音优先（v2）：空态主键 = 带文字标签的宽胶囊「按住 说话」；首访一次性可关闭引导
 * - 按住语音键开始录音（录音条出现）、松开转写直接发送、上滑取消
 * - 自适应主动作键：草稿空=按住说话、有草稿=发送、流式中=停止
 * - 添图统一进草稿（预览可删），纯图消息（UI-013）协议不变
 * - H5 不支持录音时语音键隐藏，键盘路径完整可用
 * - 单行条布局结构契约（加图/输入框/主动作键同一行，类名与 aria-label 不变）
 */
import React from 'react'
import fs from 'fs'
import path from 'path'
import '@testing-library/jest-dom'
import { render, screen, fireEvent, act } from '@testing-library/react'
import Taro from '@tarojs/taro'
import MessageInput from '../src/components/chat/MessageInput'
import { startRecording, stopRecording, stopAndTranscribe, isVoiceSupported } from '../src/utils/voice'
import { chooseImages, uploadImages } from '../src/utils/imageUpload'

jest.mock('../src/utils/voice', () => ({
  startRecording: jest.fn(),
  stopRecording: jest.fn(() => Promise.resolve('/tmp/record.mp3')),
  stopAndTranscribe: jest.fn(),
  isVoiceSupported: jest.fn(() => true),
  MIN_RECORDING_MS: 800,
}))

jest.mock('../src/utils/imageUpload', () => ({
  chooseImages: jest.fn(),
  uploadImages: jest.fn(),
}))

const mockStartRecording = startRecording as jest.Mock
const mockStopRecording = stopRecording as jest.Mock
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

/** 语音可用（小程序/真机）：语音优先 placeholder；语音不可用（H5）：纯键盘措辞 */
const PLACEHOLDER_VOICE = '按住说话，也可以打字'
const PLACEHOLDER_TEXT = '打字告诉我您想找什么'
/** 一次性语音引导已读标记（与 MessageInput.tsx 同源 key） */
const VOICE_HINT_KEY = 'voice_hint_seen'
/** 组件样式源文件（jsdom 不排版：SCSS 只能做「静态守卫」式断言，真实几何走模拟器探针） */
const SCSS_PATH = path.join(__dirname, '..', 'src', 'components', 'chat', 'MessageInput.scss')
// 剥掉 `//` 行注释再断言：注释里会出现被禁止写法/旧 token 名（解释性文字不算违约）
const readScss = () => fs.readFileSync(SCSS_PATH, 'utf8').replace(/\/\/[^\n]*/g, '')

function typeText(text: string) {
  fireEvent.change(
    screen.getByPlaceholderText(new RegExp(`${PLACEHOLDER_VOICE}|${PLACEHOLDER_TEXT}`)),
    { target: { value: text } }
  )
}

/** 按住语音键（起点 y=200）并返回按钮元素 */
function holdVoice() {
  const btn = screen.getByLabelText('按住说话')
  fireEvent.touchStart(btn, { touches: [{ clientY: 200 }] })
  return btn
}

beforeEach(() => {
  jest.clearAllMocks()
  ;(Taro as any).__clearStorage()
  ;(isVoiceSupported as jest.Mock).mockReturnValue(true)
})

describe('MessageInput — 单容器（textarea 常驻，无模式切换）', () => {
  it('textarea 常驻：语音优先 placeholder，无键盘/语音切换键', () => {
    renderInput()
    expect(screen.getByPlaceholderText(PLACEHOLDER_VOICE)).toBeInTheDocument()
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
  // 语音守卫（<0.8s 不发转写）依赖 Date.now() 差值：fake timers 可在 touchStart/touchEnd
  // 之间精确推进时间，模拟「正常时长录音」（与 request.test.ts 同款 proven 模式）
  beforeEach(() => {
    jest.useFakeTimers()
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  it('按住开始录音（录音条出现），松开转写后直接发送文本', async () => {
    mockStopAndTranscribe.mockResolvedValue({ status: 'ok', text: '我要查订单', durationMs: 1200 })
    const { props } = renderInput()

    const btn = holdVoice()
    expect(mockStartRecording).toHaveBeenCalledTimes(1)
    expect(screen.getByText('正在说话，松开发送')).toBeInTheDocument()

    jest.advanceTimersByTime(1000) // 正常时长（≥800ms）通过守卫
    await act(async () => {
      fireEvent.touchEnd(btn, { changedTouches: [{ clientY: 200 }] })
    })

    expect(mockStopAndTranscribe).toHaveBeenCalledTimes(1)
    expect(props.onSend).toHaveBeenCalledWith('我要查订单')
    // 录音条随录音结束消失
    expect(screen.queryByText('正在说话，松开发送')).not.toBeInTheDocument()
  })

  it('短按/误触（<0.8s）：不发转写、toast「未检测到声音，已取消转写」', async () => {
    const { props } = renderInput()

    const btn = holdVoice()
    // 不推进时间：touchStart→touchEnd 间隔 ~0ms < 800ms ⇒ 守卫拦截
    await act(async () => {
      fireEvent.touchEnd(btn, { changedTouches: [{ clientY: 200 }] })
    })

    expect(mockStopAndTranscribe).not.toHaveBeenCalled()
    expect(props.onSend).not.toHaveBeenCalled()
    // 仍需停止录音器（避免录满 60s 阻塞下一次录音）
    expect(mockStopRecording).toHaveBeenCalledTimes(1)
    expect(mockToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: '未检测到声音，已取消转写' })
    )
  })

  it('守卫拦截（文件过小等 stopAndTranscribe 返回 blocked）：不发送、toast「未检测到声音」', async () => {
    mockStopAndTranscribe.mockResolvedValue({ status: 'blocked' })
    const { props } = renderInput()

    const btn = holdVoice()
    jest.advanceTimersByTime(1000) // 时长正常，文件大小守卫仍拦截
    await act(async () => {
      fireEvent.touchEnd(btn, { changedTouches: [{ clientY: 200 }] })
    })

    expect(props.onSend).not.toHaveBeenCalled()
    expect(mockToast).toHaveBeenCalledWith(
      expect.objectContaining({ title: '未检测到声音，已取消转写' })
    )
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

  it('转写失败（failed）→ toast「未听清」，不发送', async () => {
    mockStopAndTranscribe.mockResolvedValue({ status: 'failed' })
    const { props } = renderInput()

    const btn = holdVoice()
    jest.advanceTimersByTime(1000)
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
    expect(screen.getByPlaceholderText(PLACEHOLDER_VOICE)).toHaveValue('')
  })

  it('清空文字后恢复按住说话键', () => {
    renderInput()
    typeText('你好')
    expect(screen.queryByLabelText('按住说话')).not.toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText(PLACEHOLDER_VOICE), { target: { value: '' } })
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

/**
 * 布局结构契约（单行输入条）
 *
 * ⚠️ 边界（migao-dev-flow §15.3）：jsdom 不排版，**真实几何**（三元素垂直中心差 ≤2px、
 * 容器高度、底部内边距）由模拟器探针取证，见 issue/PR 的 evidence。本组只锁
 * 「DOM 结构 + 类名 + SCSS 关键声明」这类 jsdom 能确定性判定、且回归时必然变红的东西。
 */
describe('MessageInput — 单行条布局结构契约', () => {
  function renderDom() {
    const { container } = renderInput()
    return container
  }

  it('加图键 / 输入框 / 主动作键同处一行容器 .message-input__row', () => {
    const container = renderDom()
    const row = container.querySelector('.message-input__row')
    expect(row).not.toBeNull()

    const attach = screen.getByLabelText('添加图片')
    const textarea = screen.getByPlaceholderText(PLACEHOLDER_VOICE)
    const main = screen.getByLabelText('按住说话')

    // 三者同层：都在同一 flex 行容器内（旧结构里动作组另起一行）
    expect(row!.contains(attach)).toBe(true)
    expect(row!.contains(textarea)).toBe(true)
    expect(row!.contains(main)).toBe(true)
  })

  it('左→右顺序为 加图 → 输入框 → 主动作键', () => {
    const container = renderDom()
    const ordered = [
      screen.getByLabelText('添加图片'),
      container.querySelector('.message-input__field')!,
      screen.getByLabelText('按住说话'),
    ]
    expect(ordered[1]).not.toBeNull()
    for (let i = 1; i < ordered.length; i++) {
      // compareDocumentPosition 位掩码：后一个元素必须排在前一个之后（文档序 = 视觉行序）
      expect(
        ordered[i - 1].compareDocumentPosition(ordered[i]) & Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy()
    }
  })

  it('动作组只承载主动作键（加图键不再与其同组，双语义切换不破坏单行结构）', () => {
    const container = renderDom()
    const actions = container.querySelector('.message-input__actions')!
    const btns = actions.querySelectorAll('.message-input__icon-btn')
    expect(btns.length).toBe(1)
    expect(btns[0]).toBe(screen.getByLabelText('按住说话'))

    // 有草稿 → 键位切发送，但仍在同一行容器内、位置不变
    typeText('你好')
    const send = screen.getByLabelText('发送')
    expect(container.querySelector('.message-input__row')!.contains(send)).toBe(true)
    expect(
      container.querySelector('.message-input__actions')!.querySelectorAll('.message-input__icon-btn').length
    ).toBe(1)
    expect(screen.queryByLabelText('按住说话')).not.toBeInTheDocument()
  })

  it('SCSS 静态守卫：底部内边距 = 基础 + 安全区（不再被 env() 覆盖为 0）', () => {
    const scss = readScss()
    expect(scss).toMatch(/padding-bottom:\s*calc\([^)]*env\(safe-area-inset-bottom\)/)
    // 回归形态：单项 padding-bottom 直接等于 env() ⇒ 基础内边距被覆盖成 0（输入条贴底边）
    expect(scss).not.toMatch(/padding-bottom:\s*env\(safe-area-inset-bottom\)\s*;/)
  })

  it('SCSS 静态守卫：输入行横排且按钮贴底（多行 autoHeight 时按钮对齐底边）', () => {
    const scss = readScss()
    const row = scss.match(/&__row\s*\{([^}]*)\}/)
    expect(row).not.toBeNull()
    expect(row![1]).toMatch(/display:\s*flex/)
    expect(row![1]).toMatch(/align-items:\s*flex-end/)
    // 输入框包裹层撑满剩余宽度，且与触摸键等高（单行时文案垂直居中）
    const field = scss.match(/&__field\s*\{([^}]*)\}/)
    expect(field).not.toBeNull()
    expect(field![1]).toMatch(/flex:\s*1/)
    expect(field![1]).toMatch(/min-height:\s*88px/)
  })

  it('SCSS 静态守卫：独立复核残余缺陷的修复不被回退（可点性/可读性/间距）', () => {
    const scss = readScss()
    // ① 图标键要有实底（裸线性图标不像可点按钮），且触摸热区保持 88px
    const iconBtn = scss.match(/&__icon-btn\s*\{([^}]*)\}/)
    expect(iconBtn![1]).toMatch(/background:\s*\$primary-light/)
    expect(iconBtn![1]).not.toMatch(/background:\s*transparent/)
    expect(iconBtn![1]).toMatch(/width:\s*88px/)
    // ② 占位文案对比度：不得回退到 $text-tertiary（在 $bg-secondary 上仅 ~2.3:1）
    const placeholder = scss.match(/&__placeholder\s*\{([^}]*)\}/)
    expect(placeholder![1]).toMatch(/\$text-secondary/)
    expect(placeholder![1]).not.toMatch(/\$text-tertiary/)
    // ③ 长句行尾与动作键之间保留固定间距
    const field = scss.match(/&__field\s*\{([^}]*)\}/)
    expect(field![1]).toMatch(/padding-right:\s*\$space-md/)
    // ④ 触摸键不贴容器左右边缘（横向内边距 > 纵向）
    const container = scss.match(/&__container\s*\{([^}]*)\}/)
    expect(container![1]).toMatch(/padding:\s*\$space-sm\s+\$space-md/)
  })
})

/**
 * 语音优先（v2，2026-09-14 产品要求）
 *
 * 目标：空态让人一眼看出"按住说话"是主要输入方式；打字退居次要但不被惩罚。
 * 边界（保持 #2953 评审决策）：仍是单容器 + textarea 常驻，**不加模式切换键**，
 * 绝不复用已退役的 `.message-input__hold-btn` / `__mode-btn` / `__btn`
 * （e2e harness 有断言这三个类不存在的负向探针）。
 */
describe('MessageInput — 语音优先（空态宽胶囊 + 一次性引导）', () => {
  it('空态主键是带文字标签的宽胶囊「按住 说话」（不是裸波形图标）', () => {
    const { container } = renderInput()
    const voice = screen.getByLabelText('按住说话')

    expect(voice.className).toContain('message-input__icon-btn--wide')
    const label = container.querySelector('.message-input__voice-label')
    expect(label).not.toBeNull()
    expect(label!.textContent).toBe('按住 说话')
    // 图标 + 文字 + 按钮底三者齐备：label 与 icon 同在语音键内
    expect(voice.querySelector('.message-input__icon')).not.toBeNull()
  })

  it('有草稿 → 主键切成发送圆键（不再宽胶囊，无双主操作）', () => {
    const { container } = renderInput()
    typeText('你好')

    const send = screen.getByLabelText('发送')
    expect(send.className).not.toContain('--wide')
    expect(container.querySelector('.message-input__voice-label')).toBeNull()
    expect(screen.queryByLabelText('按住说话')).not.toBeInTheDocument()
  })

  it('语音优先 placeholder：可用时语音在前，H5 不可用时回落纯键盘措辞且无语音入口', () => {
    const first = renderInput()
    expect(screen.getByPlaceholderText(PLACEHOLDER_VOICE)).toBeInTheDocument()
    first.unmount()

    ;(isVoiceSupported as jest.Mock).mockReturnValue(false)
    renderInput()
    expect(screen.getByPlaceholderText(PLACEHOLDER_TEXT)).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(PLACEHOLDER_VOICE)).not.toBeInTheDocument()
    expect(screen.queryByLabelText('按住说话')).not.toBeInTheDocument()
    // 键盘路径仍完整
    typeText('你好')
    expect(screen.getByLabelText('发送')).toBeInTheDocument()
  })

  it('一次性引导：首访出现并立即落「已读」（只出现一次）', () => {
    renderInput()
    expect(screen.getByText('说话更省事，按住就能说')).toBeInTheDocument()
    expect(Taro.setStorageSync).toHaveBeenCalledWith(VOICE_HINT_KEY, true)
    expect((Taro as any).__getStorage()[VOICE_HINT_KEY]).toBe(true)
  })

  it('引导已读后不再出现（第二次进入会话不再打扰）', () => {
    ;(Taro as any).setStorageSync(VOICE_HINT_KEY, true)
    renderInput()
    expect(screen.queryByText('说话更省事，按住就能说')).not.toBeInTheDocument()
  })

  it('引导可点 × 立即关闭（不残留、不影响输入条）', () => {
    const { unmount } = renderInput()
    fireEvent.click(screen.getByLabelText('关闭提示'))
    expect(screen.queryByText('说话更省事，按住就能说')).not.toBeInTheDocument()
    expect(screen.getByLabelText('按住说话')).toBeInTheDocument()
    unmount()

    // 整行也可点关闭（56px 关闭键偏小，整行命中面积兜底）
    ;(Taro as any).__clearStorage()
    renderInput()
    fireEvent.click(screen.getByText('说话更省事，按住就能说'))
    expect(screen.queryByText('说话更省事，按住就能说')).not.toBeInTheDocument()
  })

  it('语音不可用（H5）时不给语音引导（不做空承诺）', () => {
    ;(isVoiceSupported as jest.Mock).mockReturnValue(false)
    renderInput()
    expect(screen.queryByText('说话更省事，按住就能说')).not.toBeInTheDocument()
  })

  it('无模式切换键：已退役类名与切换入口都不存在（与 e2e 负向探针同源）', () => {
    const { container } = renderInput()
    expect(container.querySelector('.message-input__hold-btn')).toBeNull()
    expect(container.querySelector('.message-input__mode-btn')).toBeNull()
    expect(container.querySelector('.message-input__btn')).toBeNull()
    expect(screen.queryByLabelText('切换到键盘')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('切换到语音')).not.toBeInTheDocument()
    // 单一容器不变：语音/发送键与 textarea 同在 .message-input__row
    expect(container.querySelector('.message-input__row')!.contains(screen.getByLabelText('按住说话'))).toBe(true)
  })

  it('SCSS 静态守卫：宽胶囊与文字标签样式存在（语音优先可见性不被回退）', () => {
    const scss = readScss()
    const wide = scss.match(/&--wide\s*\{([^}]*)\}/)
    expect(wide).not.toBeNull()
    expect(wide![1]).toMatch(/width:\s*auto/)
    expect(wide![1]).toMatch(/border-radius:\s*44px/)
    const label = scss.match(/&__voice-label\s*\{([^}]*)\}/)
    expect(label).not.toBeNull()
    expect(label![1]).toMatch(/font-size:\s*28px/)
  })
})
