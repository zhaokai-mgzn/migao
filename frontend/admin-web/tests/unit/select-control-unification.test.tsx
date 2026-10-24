// case_ids: UI-131
/**
 * 类级元守卫（issue #7397）：**下拉框只有一种形态**。
 *
 * ## 病灶（用户 2026-10-20 三张截图 + 逐字「我们所有页面的下拉框都看着很别扭，不协调」）
 *
 * 业务面 38 处原生 `<select>` 各页自己拼控件铬：有的**没写 `appearance-none`**（箭头交给操作系统画，
 * macOS 上是一个带框的原生箭头 —— 截图里那个被红框圈住的「框住的小箭头」）；有的写了
 * `appearance-none` + `pr-9` 却**没有自绘箭尖**（下拉看起来没有箭头）；共享原语
 * `frontend/admin-web/src/components/ui/Select.tsx` 又是第三种形态（`rounded-lg` + 叠层 `ChevronDown`）。
 * 当时**没有任何判据会红**：`design-system-form-fields.test.tsx` 的规则 1 只认
 * `h-9 + rounded-lg + border-neutral-300` 同现的串，手写的 `rounded border` 全部逃逸。
 *
 * ## 判据（每条都**会红**）
 *
 * 1. **业务面的每个 `<select>` 必须引用共享铬**（`SELECT_CONTROL`，或自有字号的 `SELECT_CHEVRON`
 *    —— 后者只许出现在冻结台账里）；
 * 2. **铬本身不许被削弱**：`SELECT_CONTROL` 少了 `appearance-none` / `h-9` / 自绘箭尖 / 焦点环 / `pr-9` 即红；
 * 3. **单一份箭尖图形**：`Select` 原语不得再叠一个 `ChevronDown`（两套箭头叠加是本单的成因之一）；
 * 4. **筛选条字段可增长**（同一张截图里的「输入框太短、占位文案被截断」）：
 *    `SearchBar` 的字段容器必须 `flex-1`（旧版定宽 `min-w-[200px]` 且不 grow）。
 *
 * ## 台账（**只许缩短**）
 *
 * `SELECT_CHEVRON_LEDGER` = 只借箭尖、尺寸自有口径的面。冻结于 2026-10-20（issue #7397）：
 * 企业入驻页 `register`（h-11 大字表单，硬塞 h-9 会与同页输入框不齐）。
 * 双向相等：现取集合必须逐条登记（新写法进不来），登记条目必须仍能命中（修好了必须删条目）。
 *
 * ## 边界（如实登记，§19.1）
 *
 * - 判的是**源码形态**（`<select>` 开标签里有没有引用共享铬），不是像素几何；
 *   真几何 / 「好不好看」仍由 `frontend/admin-web/scripts/design-baseline-geometry-probe.mjs`
 *   的真浏览器读数 + §15.7 读图裁定（§31.4）。
 * - 不判「该用原语 `Select` 还是原生 `<select>`」（表单字段面与筛选面各有一套，理由写在 `Select.tsx`）；
 * - 不判输入框的圆角/铬（本轮只收口下拉 + 筛选条宽度；输入框的 `rounded` 4px 存量差异登记在 issue #7397 的边界节）。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'

import {
  SELECT_BASE,
  SELECT_CHEVRON,
  SELECT_CONTROL,
  SELECT_CONTROL_FIELD,
} from '../../src/components/ui/Select'
import SearchBar from '../../src/components/ui/SearchBar'

const UI_DIR = 'src/components/ui/'

/**
 * 只借箭尖、尺寸自有口径的面 —— **只许缩短**。
 * `register`（h-11 大字入驻表单）：与同页输入框同高同圆角，仅把系统原生箭头换成本仓那一份图形。
 */
const SELECT_CHEVRON_LEDGER = ['src/app/register/page.tsx']
const SELECT_CHEVRON_BASELINE = 1

/** 收集 `src/**` 下的 `.tsx`（仓库相对路径，`/` 分隔）。 */
function tsxFiles(dir = 'src', base = process.cwd(), out: string[] = []): string[] {
  for (const name of readdirSync(join(base, dir))) {
    const rel = `${dir}/${name}`
    const abs = join(base, rel)
    if (statSync(abs).isDirectory()) tsxFiles(rel, base, out)
    else if (name.endsWith('.tsx')) out.push(rel.split(sep).join('/'))
  }
  return out
}

/** 从 `<select` 起，按花括号 / 圆括号配平取出**开标签**（`onChange={(e) => …}` 里的 `>` 不算结束）。 */
export function openingTag(text: string, start: number): string {
  let i = start
  let braces = 0
  let parens = 0
  let quote: string | null = null
  while (i < text.length) {
    const c = text[i]
    if (quote) {
      if (c === '\\') {
        i += 2
        continue
      }
      if (c === quote) quote = null
    } else if (c === "'" || c === '"' || c === '`') {
      quote = c
    } else if (c === '{') braces += 1
    else if (c === '}') braces -= 1
    else if (c === '(') parens += 1
    else if (c === ')') parens -= 1
    else if (c === '>' && braces === 0 && parens === 0) return text.slice(start, i + 1)
    i += 1
  }
  return text.slice(start)
}

export interface SelectTag {
  /** 1 起的行号（判红时点名） */
  line: number
  tag: string
}

/** 源码里**真实的** `<select>` 开标签（注释里的 `<select>` 字样不算）。 */
export function selectTags(text: string): SelectTag[] {
  const out: SelectTag[] = []
  const re = /<select(?![A-Za-z])/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    const tag = openingTag(text, m.index)
    if (tag === '<select>') continue // `<select>` 只在 JSDoc / 类型注释里出现
    out.push({ line: text.slice(0, m.index).split('\n').length, tag })
  }
  return out
}

/** 判据 1 的**纯函数**（可内存注入取证）：返回「下拉没有引用共享铬」的 `文件:行`。 */
export function bareSelects(files: { rel: string; text: string }[]): string[] {
  const bad: string[] = []
  for (const f of files) {
    if (f.rel.startsWith(UI_DIR)) continue
    for (const { line, tag } of selectTags(f.text)) {
      if (tag.includes('SELECT_CONTROL')) continue
      if (tag.includes('SELECT_CHEVRON') && SELECT_CHEVRON_LEDGER.includes(f.rel)) continue
      bad.push(`${f.rel}:${line}`)
    }
  }
  return bad
}

/** 业务面文件（`src/**`，排除共享原语目录）。 */
function businessFiles(): { rel: string; text: string }[] {
  return tsxFiles()
    .filter((rel) => !rel.startsWith(UI_DIR))
    .map((rel) => ({ rel, text: readFileSync(rel, 'utf8') }))
}

describe('判据 1：业务面下拉必须引用共享铬（未登记即红）', () => {
  it('没有「自己拼下拉铬」的 <select>', () => {
    const files = businessFiles()
    expect(files.length).toBeGreaterThan(40) // 反空跑：射程塌了要出声
    const bad = bareSelects(files)
    expect(
      bad,
      `这些 <select> 还在自己拼控件铬（原生箭头 / 各页各写一份）⇒ 全站下拉形态不统一：\n  ` +
        `${bad.join('\n  ')}\n改用 frontend/admin-web/src/components/ui/Select.tsx 导出的 ` +
        `\`SELECT_CONTROL\`（筛选 / 行内面）或 \`SELECT_CHEVRON\`（自有字号面，须登记台账）。`,
    ).toEqual([])
  })

  it('台账只许缩短：登记条目必须仍能命中，条数冻结', () => {
    expect(SELECT_CHEVRON_LEDGER).toHaveLength(SELECT_CHEVRON_BASELINE)
    for (const rel of SELECT_CHEVRON_LEDGER) {
      const text = readFileSync(rel, 'utf8')
      const uses = selectTags(text).filter((t) => t.tag.includes('SELECT_CHEVRON'))
      expect(uses.length, `台账条目已失效（该面已不再借箭尖）⇒ 必须删条目：${rel}`).toBeGreaterThan(0)
    }
  })

  it('反作弊：射程里确实有足量下拉（否则判据 1 是空转）', () => {
    const count = businessFiles().reduce((n, f) => n + selectTags(f.text).length, 0)
    expect(count).toBeGreaterThanOrEqual(30)
  })
})

describe('判据 2：共享铬不许被削弱', () => {
  const required = [
    'appearance-none', // 箭头必须自绘（交给系统 = 各平台三种形态）
    'h-9', // 桌面主控件下限（与 Input 同值）
    'border-neutral-300',
    'pr-9', // 给箭尖留位
    'rounded',
    'select-chevron', // 自绘箭尖（图形在 globals.css，见判据 2 的第二条）
    'focus:ring-2',
    'disabled:bg-neutral-100',
  ]

  it.each(required)('SELECT_CONTROL 仍带 `%s`', (needle) => {
    expect(SELECT_CONTROL).toContain(needle)
  })

  it('箭尖是内联 SVG 背景（单一图形，不依赖图标组件 / 操作系统）', () => {
    // 🔴 图形必须落在 globals.css 的组件类里：Tailwind **任意值**里的内联 SVG（引号 + 逗号）
    // 会被内容扫描器切碎 —— 2026-10-20 实测构建后 `background-image: none`（下拉变成没箭头）。
    expect(SELECT_CHEVRON).toBe('select-chevron')
    const css = readFileSync('src/app/globals.css', 'utf8')
    const rule = css.slice(css.indexOf('.select-chevron'))
    expect(rule).toContain('background-image: url("data:image/svg+xml')
    expect(rule).toContain('background-repeat: no-repeat')
    expect(rule).toContain('background-position: right 0.75rem center')
    expect(rule).toContain('background-size: 1rem 1rem')
  })

  it('表单字段面 = 同一套铬 + 8px 圆角（与 Input 一致）', () => {
    expect(SELECT_CONTROL_FIELD.startsWith('rounded-lg ')).toBe(true)
    expect(SELECT_CONTROL_FIELD).toContain('appearance-none')
    expect(SELECT_CONTROL).toContain('rounded')
  })

  it('SELECT_BASE 是两份面共用的那一半（不含圆角 / 宽度）', () => {
    expect(SELECT_BASE).not.toContain('rounded')
    expect(SELECT_BASE).not.toContain('w-full')
    expect(SELECT_CONTROL).toContain(SELECT_BASE.trim())
    expect(SELECT_CONTROL_FIELD).toContain(SELECT_BASE.trim())
  })
})

describe('判据 3：单一份箭尖图形（原语不再叠 ChevronDown）', () => {
  it('Select.tsx 不再 import `ChevronDown`，且用共享铬', () => {
    const text = readFileSync('src/components/ui/Select.tsx', 'utf8')
    expect(text).not.toContain("from 'lucide-react'")
    expect(text).toContain('SELECT_CONTROL_FIELD')
  })
})

describe('判据 4：筛选条字段参与伸缩（占位文案不再被截断）', () => {
  const longPlaceholder = '搜索标题 / 关键词 / 常见问法 / 回答内容'

  it('字段容器 `flex-1`（旧版定宽 min-w-[200px] 且不 grow ⇒ 必然截断）', () => {
    render(
      <SearchBar fields={[{ key: 'keyword', label: '关键词', type: 'input', placeholder: longPlaceholder }]} onSearch={() => {}} />,
    )
    const field = screen.getByTestId('search-field-keyword')
    expect(field.className).toContain('flex-1')
    expect(field.className).not.toContain('min-w-[200px]')
    // 初始宽度足以装下最长占位文案（22rem ≈ 352px > 19 个中文字 + 三个「 / 」）
    expect(field.className).toContain('basis-[22rem]')
  })

  it('输入框吃满字段容器（`w-full`，由 Input 原语提供）', () => {
    render(
      <SearchBar fields={[{ key: 'keyword', label: '关键词', type: 'input', placeholder: longPlaceholder }]} onSearch={() => {}} />,
    )
    const input = screen.getByPlaceholderText(longPlaceholder)
    expect(input.className).toContain('w-full')
  })
})

describe('判别力自证（纯函数级：坏形态判红、好形态放行）', () => {
  const BAD = `<select className="h-9 px-3 rounded border border-neutral-300" value={x} onChange={(e) => set(e.target.value)}>`
  const GOOD = `<select className={cn(SELECT_CONTROL, 'min-w-[9rem]')} value={x} onChange={(e) => set(e.target.value)}>`
  const LEDGER_OK = `<select className={cn(inputClassName(false), SELECT_CHEVRON)}>`

  it('自己拼铬 ⇒ 判红（并点名 文件:行）', () => {
    expect(bareSelects([{ rel: 'src/app/(dashboard)/x/page.tsx', text: BAD }])).toEqual([
      'src/app/(dashboard)/x/page.tsx:1',
    ])
  })

  it('引用 SELECT_CONTROL ⇒ 放行', () => {
    expect(bareSelects([{ rel: 'src/app/(dashboard)/x/page.tsx', text: GOOD }])).toEqual([])
  })

  it('SELECT_CHEVRON 只有在台账内才放行（未登记 ⇒ 判红）', () => {
    expect(bareSelects([{ rel: 'src/app/register/page.tsx', text: LEDGER_OK }])).toEqual([])
    expect(bareSelects([{ rel: 'src/app/(dashboard)/x/page.tsx', text: LEDGER_OK }])).toEqual([
      'src/app/(dashboard)/x/page.tsx:1',
    ])
  })

  it('注释里的 `<select>` 字样不算真实下拉（不制造假红）', () => {
    const text = '/** 控件本体：`<input>` / `<select>` / 日期区间 */\n<select className={SELECT_CONTROL} />'
    expect(bareSelects([{ rel: 'src/app/(dashboard)/x/page.tsx', text }])).toEqual([])
  })

  it('多行开标签（含 `=>`）能被完整取出（不把 `>` 当标签结尾）', () => {
    const [tag] = selectTags(GOOD.replace('{x}', '{a > b}'))
    expect(tag.tag).toContain('SELECT_CONTROL')
  })
})
