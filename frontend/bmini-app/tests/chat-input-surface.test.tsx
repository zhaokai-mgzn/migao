// case_ids: BM-044
/**
 * B 端「问黄金策」输入条的 **H5 形态**判据（issue #6476 建；**issue #6596 改判**）
 *
 * ## 治的形态
 *
 * ① issue #6476（三处独立病灶：placeholder 空承诺 / 样式没落到内层原生控件 / 行高对不齐）
 * ② 🔴 **issue #6596 改判**：用户 2026-10-09 裁定「**默认按住说话**，语音和键盘 icon 可以切换」
 *    —— 而「按住说话」在 H5 上必须是**真能按的**：本单用浏览器 `getUserMedia` + `MediaRecorder`
 *    把 H5 录音**做出来**（后端 `POST /api/chat/transcribe` 已支持 webm/opus 与 mp4）。
 *    ⇒ 「H5 不承诺录音」这条从「**不许写**按住说话」收窄成「**做不到才不写**」：
 *     · 浏览器**有** `MediaRecorder` ⇒ 语音模式可用（「按住说话」可按住，走浏览器录音链路）；
 *     · 浏览器**确实没有** ⇒ 回落文字模式（输入框 + 键盘措辞 placeholder），
 *       **绝不**渲染一个按不动的「按住说话」（#5650 的教训不变）。
 *
 * ## 判据
 *
 * | # | 断言 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | H5 **无** `MediaRecorder` ⇒ 键盘措辞 placeholder、且**不出现**「按住说话」 | 摆出按不动的按钮 ⇒ 具名红 |
 * | 2 | H5 **有** `MediaRecorder` ⇒ `isVoiceSupported()` 为真、按住走浏览器录音链路 | 能力探测漏了 H5 / 假绿（探测恒真）⇒ 红 |
 * | 3 | 小程序（录音可用）placeholder 保留「两种输入方式」的双语义 | 一刀切成键盘措辞 ⇒ 红 |
 * | 4 | 源码层：输入态样式必须落到**内层原生控件**（含 `resize` / `::placeholder` / 单行行盒） | 删掉内层规则（H5 又回浏览器默认）⇒ 红 |
 *
 * ## 边界（照实登记）
 *
 * - 第 4 条是**源码层形态守卫**（扫 SCSS，注释先剔除）：它保证「规则还在」，
 *   不保证「浏览器里必然生效」—— 后者由 `#6476` 的真机读数承担（那一步没法进 CI）。
 * - 第 2 条只证明**能力探测**在（`MediaRecorder` 在 ⇒ 入口可按住）；
 *   「录出来的音频真的能被后端转写」由 `frontend/bmini-app/tests/voice-browser-recorder.test.ts`
 *   的真实 `MediaRecorder` 桩（mime 选择 / blob URL / 权限拒绝文案）承担。
 * - 不判颜色观感（`$text-secondary` 的对比度依据在 C 端 scss 注释里），只判这个 token 被用到。
 */
import React from 'react'
import fs from 'fs'
import path from 'path'
import '@testing-library/jest-dom'
import { render, screen, fireEvent } from '@testing-library/react'
import Taro from '@tarojs/taro'
import MessageInput from '../src/components/chat/MessageInput'
import { isVoiceSupported, startRecording } from '../src/utils/voice'
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

const mockVoiceSupported = isVoiceSupported as jest.Mock
const mockStartRecording = startRecording as jest.Mock

const SCSS_PATH = path.resolve(__dirname, '../src/components/chat/MessageInput.scss')
/** 语音不可达那条腿的键盘措辞（`Textarea` 常驻，不再承诺语音） */
const KEYBOARD_PLACEHOLDER = '打字问黄金策，比如「今天经营怎么样？」'
const VOICE_PLACEHOLDER = '发消息或按住说话'

/** 在指定编译目标下跑（`isH5()` 读的是 `process.env.TARO_ENV`） */
function withTaroEnv<T>(env: string, fn: () => T): T {
  const bag = process.env as unknown as Record<string, string | undefined>
  const prev = bag.TARO_ENV
  bag.TARO_ENV = env
  try {
    return fn()
  } finally {
    if (prev === undefined) delete bag.TARO_ENV
    else bag.TARO_ENV = prev
  }
}

/** 剔除注释后的 SCSS 代码（注释里出现同名 token 不算数） */
function scssCode(): string {
  return fs
    .readFileSync(SCSS_PATH, 'utf-8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((line) => !line.trim().startsWith('//'))
    .join('\n')
}

beforeEach(() => {
  jest.clearAllMocks()
})

describe('B 端输入条 — 语音可达性按**浏览器能力**分流（issue #6596 改判 #6476）', () => {
  it('H5 且浏览器**没有** MediaRecorder：回落文字模式 —— 键盘措辞、且不出现按不动的「按住说话」', () => {
    mockVoiceSupported.mockReturnValue(false)
    withTaroEnv('h5', () => {
      render(<MessageInput onSend={jest.fn()} isStreaming={false} />)
      expect(screen.getByPlaceholderText(KEYBOARD_PLACEHOLDER)).toBeInTheDocument()
      // 🔴 关键：**不出现**按不动的「按住说话」（#6596 之后 h5 真能录，只有真没有 API 时才回落）
      expect(document.querySelector('.message-input__hold')).toBeNull()
      // 切换键仍在（点了给「为什么不可用 + 怎么办」的显式解释，不是静默消失）
      const toggle = screen.getByLabelText('切换到语音输入')
      expect(Array.from(toggle.classList)).toContain('message-input__mode-toggle--disabled')
      fireEvent.click(toggle)
      expect(Taro.showToast).toHaveBeenCalledWith(
        expect.objectContaining({ title: H5_VOICE_UNAVAILABLE_HINT }),
      )
    })
  })

  it('H5 且浏览器**有** MediaRecorder：语音模式可用 —— 首屏是能按的「按住说话」，且按住真的开始录音', () => {
    mockVoiceSupported.mockReturnValue(true)
    withTaroEnv('h5', () => {
      render(<MessageInput onSend={jest.fn()} isStreaming={false} />)
      const btn = screen.getByLabelText('按住说话')
      fireEvent.touchStart(btn, { touches: [{ clientY: 200 }] })
      expect(mockStartRecording).toHaveBeenCalledTimes(1)
      expect(screen.getByText('正在说话，松开发送')).toBeInTheDocument()
    })
  })

  it('小程序（录音可用）：键盘模式 placeholder 保留「打字 or 说话」的双语义', () => {
    mockVoiceSupported.mockReturnValue(true)
    withTaroEnv('weapp', () => {
      render(<MessageInput onSend={jest.fn()} isStreaming={false} />)
      fireEvent.click(screen.getByLabelText('切换到键盘输入'))
      expect(screen.getByPlaceholderText(VOICE_PLACEHOLDER)).toBeInTheDocument()
      expect(screen.queryByPlaceholderText(KEYBOARD_PLACEHOLDER)).toBeNull()
    })
  })
})

describe('B 端输入条 — 样式必须落到真控件（类级元守卫，issue #6476）', () => {
  it('`MessageInput.scss` 的输入态规则覆盖内层原生 textarea（字号/字体/占位符色/缩放手柄/行盒）', () => {
    const code = scssCode()
    // 从 `&__textarea` 一直切到 `&__attach`（`&__placeholder` 是这一段的最后一块）
    const block = code.slice(code.indexOf('&__textarea'), code.indexOf('&__attach'))

    // 内层选择器本身（没有它，下面几条在 H5 里全都落不到文字上）
    // ⚠️ 必须是 `.taro-textarea`（Taro 给内层原生控件挂的 class），**不能**写 `textarea` 标签选择器：
    //    H5 构建会把它改写成自定义元素 `<taro-textarea-core>`（= 又打回包裹元素，静默无效）。
    //    这条反陷阱断言是初版漏掉的 —— 初版写 `textarea {` 也能过，而实测内层仍是浏览器默认。
    expect(block).toContain('.taro-textarea {')
    expect(block).not.toMatch(/^\s*textarea\s*\{/m)
    expect(block).toContain('font-family: inherit')
    expect(block).toContain('font-size: inherit')
    expect(block).toContain('resize: none')
    expect(block).toContain('::placeholder')
    expect(block).toContain('color: $text-secondary')
    // 单行行盒（> 40px：原值小于行盒 ⇒ 单行时与动作行对不齐）
    expect(block).toContain('min-height: 42px')
  })
})
