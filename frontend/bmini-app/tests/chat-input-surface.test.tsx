// case_ids: BM-44
/**
 * B 端「问米宝」输入条的 **H5 形态**判据（issue #6476）
 *
 * ## 治的形态（用户 2026-10-07 逐字）
 *
 * > 「输入框中有一行小字叫发消息或按住说话的样式不对」
 *
 * 真栈 + 真浏览器实测（读数见 issue #6476），三条**互相独立**的病灶：
 *
 * 1. **文案空承诺**：H5 里浏览器没有录音实现（`utils/voice.ts` 是 stub，语音键按 #5650 保留可见但禁用），
 *    这行小字却写着「按住说话」—— 它承诺的动作用户做不到。
 * 2. **样式没落到真控件**：Taro H5 的 class 落在**包裹元素** `<taro-textarea-core>` 上，
 *    真正绘制文字的是**内层**原生 `<textarea class="taro-textarea">`。
 *    实测内层跑的是**浏览器默认**：`font-family: monospace` / `font-size: 13.33px` /
 *    `::placeholder` 默认灰 / `resize: both`（截图右下那条原生斜线）。
 * 3. **行高对不齐**：`min-height: 40px` 小于单行行盒 42px（C 端已修过同一个数，B 端漏）。
 *
 * ## 判据
 *
 * | # | 断言 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | H5（无录音）placeholder 是键盘措辞、且**不含**「按住说话」 | 回硬编码那一句 ⇒ 具名红 |
 * | 2 | 小程序（录音可用）placeholder 保留「两种输入方式」的双语义 | 一刀切成键盘措辞 ⇒ 红 |
 * | 3 | 源码层：输入态样式必须落到**内层原生控件**（含 `resize` / `::placeholder` / 单行行盒） | 删掉内层规则（H5 又回浏览器默认）⇒ 红 |
 *
 * ## 边界（照实登记）
 *
 * - 第 3 条是**源码层形态守卫**（扫 SCSS，注释先剔除）：它保证「规则还在」，
 *   不保证「浏览器里必然生效」—— 后者由 `#6476` 的真机读数承担（那一步没法进 CI，见 PR body 的未覆盖登记）。
 * - 不判颜色观感（`$text-secondary` 的对比度依据在 C 端 scss 注释里），只判这个 token 被用到。
 */
import React from 'react'
import fs from 'fs'
import path from 'path'
import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import MessageInput from '../src/components/chat/MessageInput'
import { isVoiceSupported } from '../src/utils/voice'

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

const SCSS_PATH = path.resolve(__dirname, '../src/components/chat/MessageInput.scss')
/** H5 那条腿的键盘措辞（与 C 端口径同形：语音不可用就不承诺语音） */
const H5_PLACEHOLDER = '打字问米宝，比如「今天经营怎么样？」'
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

describe('B 端输入条 — placeholder 按平台分流（issue #6476）', () => {
  it('H5（浏览器无录音）：placeholder 是键盘措辞，不出现「按住说话」', () => {
    mockVoiceSupported.mockReturnValue(false)
    withTaroEnv('h5', () => {
      render(<MessageInput onSend={jest.fn()} isStreaming={false} />)
      expect(screen.getByPlaceholderText(H5_PLACEHOLDER)).toBeInTheDocument()
      expect(screen.queryByPlaceholderText(/按住说话/)).toBeNull()
    })
  })

  it('小程序（录音可用）：placeholder 保留「打字 or 说话」的双语义', () => {
    mockVoiceSupported.mockReturnValue(true)
    render(<MessageInput onSend={jest.fn()} isStreaming={false} />)
    expect(screen.getByPlaceholderText(VOICE_PLACEHOLDER)).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(H5_PLACEHOLDER)).toBeNull()
  })
})

describe('B 端输入条 — 样式必须落到真控件（类级元守卫，issue #6476）', () => {
  it('`MessageInput.scss` 的输入态规则覆盖内层原生 textarea（字号/字体/占位符色/缩放手柄/行盒）', () => {
    const code = scssCode()
    const block = code.slice(code.indexOf('&__textarea'), code.indexOf('&__actions'))

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
