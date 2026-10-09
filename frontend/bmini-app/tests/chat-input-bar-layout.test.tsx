// case_ids: BM-044
/**
 * B 端「问黄金策」输入条 — **单行形态 + 键盘/语音切换 + 底栏不遮输入条**（issue #6596）
 *
 * ## 治的形态（用户 2026-10-09 真机截图 + 逐字）
 *
 * > 「米高对话框的样式比较混乱，**语音按钮和输入框完全被遮挡了**，我建议把输入框，添加图片，
 * >  语音的按钮放一行，然后定义一个格式的宽高，而且默认文字叫按住说话，通过语音对话，
 * >  语音和键盘 icon 可以切换文字输入和语音对话。」
 *
 * 两条**互相独立**的根因：
 * ① 输入条被 `MerchantTabBar`（`position: fixed; bottom: 0` 的**浮层**，issue #6574 引入）压住 ——
 *    `pages/chat/index/index.scss` 的 `.chat-page{height:100vh}` 与输入条都**没有为它留位**；
 * ② B 端输入条是「textarea 一行 + 动作组另一行」两行结构（C 端早已收敛成单行）。
 *
 * ## 用户已裁定的形态（2026-10-09，逐字确认）
 *
 * 单行 = `[键盘/语音切换][输入框 或「按住说话」][加图][发送]`，**固定宽高**（触摸键沿用 88px/44pt）；
 * **默认语音模式**（中间是「按住说话」），点键盘图标 → 文字输入，再点 → 回到「按住说话」。
 *
 * ## 判据
 *
 * | # | 断言 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | 单行：`__row` 是 flex 行，且切换键 / 中间区 / 加图 / 动作键**四个都在 `__row` 内** | 退回「textarea 一行 + 动作组另一行」⇒ 具名红 |
 * | 2 | 固定高度：`__row` 定高（`height: 88px`）且中间区与触摸键**同高**；行内不许 `flex-wrap` | 高度随内容抖动 / 换行 ⇒ 红 |
 * | 3 | 默认语音模式：首屏中间是「按住说话」、**没有**输入框 | 默认变打字（或两条同时出现）⇒ 红 |
 * | 4 | 切换：点键盘图标 ⇒ 输入框出现（placeholder 为键盘措辞）、「按住说话」消失；再点 ⇒ 变回 | 切换键不接线 / 单向切换 ⇒ 红 |
 * | 5 | 🔴 **底栏不遮输入条**：`.chat-page` 底部预留 == 底栏高 `calc(50PX + env(safe-area-inset-bottom))`，且**只补一次**（输入条自己不许再补安全区） | 撤掉预留（用户实测：整条输入条看不见）⇒ 红；两处都补 ⇒ 底部留缝 ⇒ 也红 |
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 判据 1~4 是 **DOM 结构级**（jsdom 不做布局）；判据 5 是**形态级**（扫 SCSS 文本，注释先剔除）。
 *   「真的没被遮住」还差一份**几何读数**：`tests/e2e/specs/bmini/bmini-chat-input-geometry.spec.ts`
 *   （Playwright 量「输入条底边 / 底栏顶边 / 视口高」三个数）—— 它不进本文件，也不进 unit 门禁。
 * - 颜色 / 观感不在判据内。
 */
import React from 'react'
import fs from 'fs'
import path from 'path'
import '@testing-library/jest-dom'
import { render, screen, fireEvent } from '@testing-library/react'
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

const CHAT_PAGE_SCSS = path.resolve(__dirname, '../src/pages/chat/index/index.scss')
const INPUT_SCSS = path.resolve(__dirname, '../src/components/chat/MessageInput.scss')

/** 剔除注释后的 SCSS **代码**（注释里提到某条规则不算落实） */
function scssCode(file: string): string {
  return fs
    .readFileSync(file, 'utf-8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((line) => !line.trim().startsWith('//'))
    .join('\n')
}

/** 取 `&__<name> { … }` 块的**代码文本**（含嵌套）；用「下一个块的起点」收尾，保持纯文本判据 */
function block(code: string, name: string): string {
  const start = code.indexOf(`&__${name}`)
  if (start < 0) return ''
  const rest = code.slice(start)
  const next = rest.slice(1).search(/\n\s*&__/)
  return next < 0 ? rest : rest.slice(0, next + 1)
}

beforeEach(() => {
  jest.clearAllMocks()
  ;(isVoiceSupported as jest.Mock).mockReturnValue(true)
})

describe('B 端输入条 — 单行结构（issue #6596）', () => {
  it('四个控件同处一行：切换键 / 中间区 / 加图 / 主动作键都在 `__row` 内', () => {
    const { container } = render(<MessageInput onSend={jest.fn()} isStreaming={false} />)
    const row = container.querySelector('.message-input__row')
    expect(row).not.toBeNull()

    // 行**内**（不是行外的兄弟节点）
    for (const sel of ['__mode-toggle', '__center', '__attach', '__actions']) {
      expect(row!.querySelector(`.message-input${sel}`)).not.toBeNull()
    }
    // 动作键在**行内**（旧形态把它放在 textarea 的下一个兄弟里 = 第二行 ⇒ 这里取不到）
    expect(row!.querySelector('.message-input__actions')).not.toBeNull()
    // 全仓只有一条 `__row` 规则（再多一条就是又长出一行结构）
    expect(scssCode(INPUT_SCSS).match(/&__row/g)).toHaveLength(1)
  })

  it('固定高度：`__row` 定高 88px（44pt），中间区与触摸键同高，且行内不换行', () => {
    const code = scssCode(INPUT_SCSS)
    const row = block(code, 'row')
    expect(row).not.toBe('')

    // 定高（不是 min-height / auto）：内容变化不抖
    expect(row).toMatch(/height:\s*88px\s*;/)
    expect(row).toContain('flex-wrap: nowrap')
    // 单行：不加换行（`wrap` 会让「一行」退化成两行）
    expect(row).not.toMatch(/flex-wrap:\s*wrap/)

    // 中间区与触摸键同高 —— 同一份 88px 源，不写第二个魔数
    const center = block(code, 'center')
    expect(center).toMatch(/height:\s*88px\s*;/)
    expect(block(code, 'mode-toggle')).toMatch(/flex-shrink:\s*0\s*;/)
  })
})

describe('B 端输入条 — 默认语音模式 + 键盘/语音切换（issue #6596）', () => {
  it('首屏默认语音模式：中间是「按住说话」，没有输入框', () => {
    render(<MessageInput onSend={jest.fn()} isStreaming={false} />)
    expect(screen.getByLabelText('按住说话')).toBeInTheDocument()
    expect(screen.queryByLabelText('消息输入框')).toBeNull()
    // 切换键在（用于切到键盘）
    expect(screen.getByLabelText('切换到键盘输入')).toBeInTheDocument()
  })

  it('点键盘图标 ⇒ 变输入框（中间换输入框、placeholder 是键盘措辞）且「按住说话」消失；再点 ⇒ 变回', () => {
    render(<MessageInput onSend={jest.fn()} isStreaming={false} />)

    fireEvent.click(screen.getByLabelText('切换到键盘输入'))
    expect(screen.getByLabelText('消息输入框')).toBeInTheDocument()
    expect(screen.queryByLabelText('按住说话')).toBeNull()
    // 键盘模式中间是 placeholder（不是又一条「按住说话」按钮）
    expect(document.querySelector('.message-input__textarea')).not.toBeNull()
    // 语音可达 ⇒ placeholder 是「发消息或按住说话」（双语义；不可达那条腿的键盘措辞见
    // tests/chat-input-surface.test.tsx 判据 1）
    expect(screen.getByPlaceholderText('发消息或按住说话')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('切换到语音输入'))
    expect(screen.queryByLabelText('消息输入框')).toBeNull()
    expect(screen.getByLabelText('按住说话')).toBeInTheDocument()
  })

  it('切到键盘输入后打字：动作键变发送，发出的是输入的文字', () => {
    const onSend = jest.fn()
    render(<MessageInput onSend={onSend} isStreaming={false} />)

    fireEvent.click(screen.getByLabelText('切换到键盘输入'))
    fireEvent.change(screen.getByLabelText('消息输入框'), { target: { value: '今天经营怎么样' } })
    expect(screen.queryByLabelText('按住说话')).toBeNull()

    fireEvent.click(screen.getByLabelText('发送'))
    expect(onSend).toHaveBeenCalledWith('今天经营怎么样')
  })
})

describe('B 端输入条 — 底栏不遮输入条（issue #6596）', () => {
  const chatPage = scssCode(CHAT_PAGE_SCSS)
  const input = scssCode(INPUT_SCSS)

  it('🔴 `.chat-page` 为底栏留位：底部预留 == 底栏高（`50PX + 安全区`），值不是随手写的数', () => {
    const page = chatPage.match(/\.chat-page\s*\{[^}]*\}/)?.[0] ?? ''
    expect(page).not.toBe('')
    // 预留 = 浮层底栏所占的那一条（`MerchantTabBar.scss` 的条高算式，同源同值）
    expect(page).toMatch(/padding-bottom:\s*calc\(\s*50PX\s*\+\s*env\(safe-area-inset-bottom\)\s*\)\s*;/)
  })

  it('🔴 `.chat-page` 是 border-box（状态栏 `padding-top` 不许把整页顶出视口）', () => {
    const page = chatPage.match(/\.chat-page\s*\{[^}]*\}/)?.[0] ?? ''
    expect(page).not.toBe('')
    // 线上实测：content-box + 行内 `padding-top: 20px` ⇒ 整页 864px（视口 844）⇒ 输入条到底边之外。
    // 这条与下面「预留」是**两半**：只留位不修 box-sizing，输入条仍然出视口（几何腿同样会红）。
    expect(page).toMatch(/box-sizing:\s*border-box\s*;/)
  })

  it('🔴 安全区只补一次：输入条自己**不再**补 `env(safe-area-inset-bottom)`（两处都补 ⇒ 底部留缝）', () => {
    expect(input).not.toContain('env(safe-area-inset-bottom)')
  })

  it('底栏那一侧仍是同一条算式（预留的依据没被改走）', () => {
    const bar = scssCode(path.resolve(__dirname, '../src/components/MerchantTabBar.scss'))
    expect(bar).toMatch(/height:\s*calc\(\s*50PX\s*\+\s*env\(safe-area-inset-bottom\)\s*\)\s*;/)
  })
})
