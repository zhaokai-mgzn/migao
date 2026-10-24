// case_ids: UI-124
/**
 * 按钮只有一种形态（issue #7184）—— 与 `FormPanel` 那套（字段/区块，#7176）同一族。
 *
 * 用户逐字（2026-10-18）：「还是老问题，按钮样式未统一，你检查下 PC 端的按钮，然后制定一个统一规范
 * 并执行落地，后续新增功能都要按页面&按钮的统一规范来落地，咱们的产品已经可以形成统一规范了」
 * ｜「这个规范包含观星台所有功能，PC&手机端」。
 *
 * 判据分两层：
 * 1. **原语自身**（组件测）：`icon` slot 给统一间距；`loading` 时 spinner **顶替** icon（不并排）；
 *    `aria-busy` 随 loading；三档尺寸与圆角是写死的 token（改 sm/md/lg 的映射 ⇒ 红）。
 * 2. **类级**（源码扫描）：裸 `<button>` 自己拼**主色 chrome**（`bg-primary-600`）⇒ 红。
 *    存量按**冻结台账 + 只许缩短**收口（新增文件 / 同文件变多 ⇒ 红并具名）。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import Button from '../../src/components/ui/Button'

const SRC = join(process.cwd(), 'src')

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (entry.endsWith('.tsx') || entry.endsWith('.ts')) out.push(full)
  }
  return out
}

/** 去掉注释（注释里写「改前长这样」不该判红） */
function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
}

/**
 * 裸 `<button>` 且**开标签里自带主色 chrome** 的位置 → `{ 'src/…': 条数 }`。
 *
 * 为什么只扫主色 chrome：主色按钮是「一屏一个」的那个动作，它必须来自 `Button variant="primary"`
 * —— 手拼一份就等于多出**第二个**按钮原语（用户截图里的「刷新/新增工序/新建路线三种形态」）。
 * 描边/幽灵的裸按钮存量更多（296 处量级），本单**不**一刀切（见 #7184 的收敛顺序），只钉住这一类。
 */
function nakedPrimaryButtonsIn(sources: Record<string, string>): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const [rel, text] of Object.entries(sources)) {
    const code = stripComments(text)
    const re = /<button\b/g
    let m: RegExpExecArray | null
    while ((m = re.exec(code))) {
      const seg = code.slice(m.index, m.index + 400)
      const gt = seg.indexOf('>')
      const tag = gt === -1 ? seg : seg.slice(0, gt)
      if (!tag.includes('bg-primary-600')) continue
      counts[rel] = (counts[rel] ?? 0) + 1
    }
  }
  return counts
}

/** 真语料：`src/**` 逐文件读进来走**同一个**纯函数（注入副本因此与真语料同判） */
function nakedPrimaryButtons(): Record<string, number> {
  const sources: Record<string, string> = {}
  for (const file of walk(SRC)) sources[file.replace(`${SRC}/`, 'src/')] = readFileSync(file, 'utf-8')
  return nakedPrimaryButtonsIn(sources)
}

/**
 * **冻结台账（只许缩短）**：现取 10 处（2026-10-18），逐条都是历史存量。
 *
 * 新增文件 / 同一文件变多 ⇒ 红（并具名文件）——用 `Button variant="primary"` 或 `size` 三档即可；
 * 收小之后台账**可以**再减一行（那是允许的方向），不要为了绿而往里加。
 */
const NAKED_PRIMARY_LEDGER: Record<string, number> = {
  'src/app/(dashboard)/customers/error.tsx': 1,
  'src/app/(dashboard)/settings/page.tsx': 2,
  'src/components/ui/SearchPanel.tsx': 1,
  'src/components/products/BatchStocktakeForm.tsx': 1,
  'src/components/chat/MessageInput.tsx': 2,
  'src/components/chat/InteractiveMessage.tsx': 2,
  'src/components/production/CuttingHeightConfigPanel.tsx': 1,
}

describe('按钮只有一种形态（issue #7184）', () => {
  it('icon slot：图标由组件给统一间距（调用方不再手写 mr-*）', () => {
    render(<Button icon={<span data-testid="glyph">+</span>}>新建路线</Button>)
    const glyph = screen.getByTestId('glyph')
    expect(glyph.parentElement?.className).toContain('mr-1.5')
    expect(glyph.parentElement?.className).toContain('shrink-0')
    expect(glyph.parentElement?.getAttribute('aria-hidden')).toBe('true')
  })

  it('loading 时 spinner **顶替** icon（并排 = 双图标，真机读成「图标重叠」）', () => {
    const { container } = render(
      <Button loading icon={<span data-testid="glyph">+</span>}>
        保存
      </Button>,
    )
    expect(screen.queryByTestId('glyph'), 'loading 时不得再渲染页面自带的图标').toBeNull()
    const icons = container.querySelectorAll('svg, [data-testid^="icon-"]')
    expect(icons.length, '有且只有一个 spinner').toBe(1)
  })

  it('aria-busy 随 loading；不 loading 时不出这个属性', () => {
    const { rerender } = render(<Button loading>保存</Button>)
    expect(screen.getByRole('button')).toHaveAttribute('aria-busy', 'true')
    rerender(<Button>保存</Button>)
    expect(screen.getByRole('button')).not.toHaveAttribute('aria-busy')
  })

  it('三档尺寸 + 圆角的 token 是写死的（改映射 ⇒ 红）', () => {
    const { rerender } = render(<Button size="sm">a</Button>)
    expect(screen.getByRole('button').className).toContain('h-8')
    expect(screen.getByRole('button').className).toContain('rounded-lg')
    rerender(<Button size="md">a</Button>)
    expect(screen.getByRole('button').className).toContain('h-9')
    rerender(<Button size="lg">a</Button>)
    expect(screen.getByRole('button').className).toContain('h-10')
  })

  /**
   * **判别力自证**（铁律 8：判据必须能红，且红得可归因）。
   *
   * 三条注入：真违规（裸主色 button）必红；两种**不该红**的形态（注释里的历史说明、
   * 走 `Button` 原语且把主色写在 className 上）必须不红 —— 否则这条判据只是「见字就红」的假门禁。
   */
  it('判别力自证：注入真违规 ⇒ 命中；注释与 `Button` 调用 ⇒ 不命中', () => {
    expect(
      nakedPrimaryButtonsIn({
        'src/x.tsx': `<button className="h-9 rounded-lg bg-primary-600 text-white">保存</button>`,
      }),
      '真违规必须被抓到（否则台账判据是空断言）',
    ).toEqual({ 'src/x.tsx': 1 })

    expect(
      nakedPrimaryButtonsIn({
        'src/y.tsx': `// 改前长这样：<button className="bg-primary-600">保存</button>\nconst a = 1`,
      }),
      '注释里的历史说明不该红',
    ).toEqual({})

    expect(
      nakedPrimaryButtonsIn({
        'src/z.tsx': `<Button variant="primary" className="bg-primary-600 border-2">保存</Button>`,
      }),
      '走原语的调用不该红（判据只针对裸 <button>）',
    ).toEqual({})
  })

  it('🔴 裸 `<button>` 不得自带主色 chrome（台账只许缩短）', () => {
    const current = nakedPrimaryButtons()
    const outside = Object.keys(current).filter((file) => !(file in NAKED_PRIMARY_LEDGER))
    expect(outside, '这些文件里的裸 <button> 自己拼了主色 chrome ⇒ 用 Button variant="primary"').toEqual([])
    const grew = Object.entries(current)
      .filter(([file, n]) => n > (NAKED_PRIMARY_LEDGER[file] ?? 0))
      .map(([file, n]) => `${file}（现取 ${n} > 台账 ${NAKED_PRIMARY_LEDGER[file] ?? 0}）`)
    expect(grew, '同一文件里又长出一个主色裸按钮 ⇒ 用 Button').toEqual([])
  })
})
