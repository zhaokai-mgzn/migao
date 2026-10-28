// case_ids: UI-122
/**
 * 类级元守卫（issue #7176，2026-10-18 用户裁定）：**配置面的字段只有一种写法**。
 *
 * ## 它治的类
 *
 * 用户逐字：「这里的风格为什么不和第二张图的风格对齐呢，第二张图可以作为一个标准来参考，
 * **后续都要形成固定的设计风格和组件**，我们一个产品不要出现多种设计和风格样式」。
 *
 * 真机截图里的**三种字段语言**（同一次会话内实测）：① 「阈值试算」标签在上 / 控件满列 / 单位入框；
 * ② 「预演（只读）」标签顺排在控件左边 + 定宽框；③ 算料口径的「属性行」标签左 / 控件右。
 * 「同一个产品里有几种字段语言」这件事**当时没有任何东西会红** —— 每个面各自有判据，谁也不会问
 * 「你这个字段跟页面上其它字段长一样吗」。本判据把这句话变成每一次 PR 都会跑的：
 *
 * 1. **控件铬只许住在共享原语里**：`h-9 ... rounded-lg ... border-neutral-300` 这种「控件 chrome」
 *    字符串只许出现在 `frontend/admin-web/src/components/ui/**`（业务面自己拼一份 ⇒ 红，具名报出）；
 * 2. **标签不得顺排在控件左边**：源码里出现 `ml-1 inline-block` 这类「标签 + 同行控件」写法 ⇒ 红；
 *    存量按**冻结台账**双向相等 + 只许缩短（修好了必须删条目，死条目也红）；
 * 3. **标准本身不许被削弱**：`FIELD_CONTROL` 必须仍带 `w-full` / `h-9` / `rounded-lg` /
 *    `border-neutral-300` / 主色聚焦环（把 `w-full` 换成定宽、或去掉圆角 ⇒ 红）；
 * 4. **三个受管面必须继续用原语**（`CalcCaliberPanel` / `OversizeThresholdPreview` /
 *    `CuttingHeightConfigPanel` 都得从 `components/ui/FormPanel` 取字段版式）。
 *
 * ## 边界（如实登记，§19.1）
 *
 * - 判的是**写法（源码形态）**，不是「好不好看」；审美仍由 §15.7 读图 + 人裁定（§31.4）。
 * - 台账是**人工维护**的：真要把某个存量面留成另一种写法 ⇒ 出口是**登记台账**（并写明为什么），
 *   不是让判据静默放行；台账**只许缩短**。
 * - 只扫 `src/**` 的 `.tsx/.ts`，不解析 AST：「标签顺排」用**归一化源码行**匹配（与
 *   `frontend/admin-web/tests/unit/list-table-nowrap-guard.test.ts` 同一套口径）；跨元素的排版
 *   形态（例如自定义组件内部再拼一套）不在此判据面内。
 * - 本轮**只迁移三个受管面**；其余配置面按 `INLINE_LABEL_LEDGER` 登记，逐页迁移（issue #7176）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'fs'
import { join, sep } from 'path'
import { FIELD_CONTROL } from '../../src/components/ui/FormPanel'

const SRC_DIR = join(process.cwd(), 'src')
/** 控件铬的**唯一居住地**（业务面自己拼一份 = 第二套设计语言） */
const CHROME_DIR = 'src/components/ui/'
/** 控件铬的识别串：同一个字符串字面量里同时有这三样（见 `FIELD_CONTROL` / `Input` / `Select`） */
const CHROME_NEEDLES = ['h-9', 'rounded-lg', 'border-neutral-300']
/** 字符串字面量（单/双/反引号）；跨 `+` 拼接会拆成多段，所以只要求**同一段**里有这三样 */
const STRING_RE = /'([^'\\\n]{4,300})'|"([^"\\\n]{4,300})"|`([^`\\\n]{4,300})`/g

/**
 * 存量台账·规则 1：**业务面自带的控件铬** —— 只许缩短。
 * 冻结于 2026-10-18（issue #7176）：图像识别按钮那个 224px 定制输入框（随该组件重做时收口）。
 */
const CHROME_LEDGER: string[] = ['src/components/image-recognize/ImageRecognizeButton.tsx']
const CHROME_BASELINE = 1

/**
 * 存量台账：**标签顺排在控件左边**（`ml-1 inline-block`）的面 —— **只许缩短**。
 *
 * 双向相等：现取集合必须逐条登记（新写法进不来），登记的条目必须仍能命中（修好了必须删条目）。
 * 冻结于 2026-10-18（issue #7176）：算料口径 / 阈值试算 / 预演在本包已迁到 `Field`，
 * 剩余在这一个面（裁剪高度的**取整 / 保留位数**两个工具栏下拉，随该页整体迁移处理）。
 */
// 2026-10-28（issue #7997）：裁高配置的「取整 / 保留位数」已迁入 `Field`（标签在上）
// ⇒ 最后一个存量条目退场，台账清空、基线 1 → 0（只许缩短的方向）。
const INLINE_LABEL_LEDGER: string[] = []
/** 冻结读数（条数现取；只许下调） */
const INLINE_LABEL_BASELINE = 0

/** `src/**` 下所有 `.ts` / `.tsx`（仓库相对路径，`/` 分隔） */
function walk(dir: string, base = SRC_DIR, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const abs = join(dir, name)
    if (statSync(abs).isDirectory()) {
      walk(abs, base, out)
    } else if (/\.(ts|tsx)$/.test(name)) {
      out.push(`src/${abs.slice(base.length + 1).split(sep).join('/')}`)
    }
  }
  return out
}

/** 仓库相对路径（`src/...`）→ 源码 */
function read(rel: string): string {
  return readFileSync(join(process.cwd(), rel), 'utf8')
}

/** 规则 1 的**纯函数**（可内存注入取证）：返回「自带控件铬、但不住在共享原语里」的文件。 */
export function chromeOutsiders(files: { rel: string; text: string }[]): string[] {
  return files
    .filter((f) => !f.rel.startsWith(CHROME_DIR))
    .filter((f) => {
      for (const m of f.text.matchAll(STRING_RE)) {
        const lit = m[1] ?? m[2] ?? m[3] ?? ''
        if (CHROME_NEEDLES.every((n) => lit.includes(n))) return true
      }
      return false
    })
    .map((f) => f.rel)
}

/**
 * 规则 2 的**纯函数**：返回「标签顺排在控件左边」的文件集合。
 *
 * 识别串 = `ml-1 inline-block`（真机截图上那种 `<label>部位<select className="ml-1 inline-block w-auto">`
 * 的写法）；归一化空白后匹配，避免缩进/换行造成的漏判。
 */
export function inlineLabelOutsiders(files: { rel: string; text: string }[]): string[] {
  return files
    .filter((f) => /ml-1\s+inline-block|inline-block\s+ml-1/.test(f.text.replace(/\s+/g, ' ')))
    .map((f) => f.rel)
}

const ALL = walk(SRC_DIR)
const FILES = ALL.map((rel) => ({ rel, text: read(rel) }))

describe('设计系统守卫（issue #7176）：配置面字段只有一种写法', () => {
  it('🔴 控件铬只许住在共享原语里（业务面自己拼一份 ⇒ 红；存量台账只许缩短）', () => {
    const now = chromeOutsiders(FILES).sort()
    expect(now, '业务面自带控件铬 ⇒ 改用 FIELD_CONTROL / ui 原语').toEqual([...CHROME_LEDGER].sort())
    expect(CHROME_LEDGER.length, '台账条数只许下调').toBeLessThanOrEqual(CHROME_BASELINE)
    // 出处自己必须在（共享原语里没有铬 = 判据失明）
    expect(FILES.some((f) => f.rel === 'src/components/ui/FormPanel.tsx' && f.text.includes('FIELD_CONTROL'))).toBe(
      true,
    )
    // 判别力自证：业务面拼一份铬 ⇒ 当场红并具名；只传 `className` 的调用**不算**（不制造假红）
    expect(
      chromeOutsiders([
        { rel: 'src/components/ui/FormPanel.tsx', text: "'h-9 rounded-lg border-neutral-300 bg-white'" },
        { rel: 'src/components/settings/OldField.tsx', text: "'h-9 rounded-lg border-neutral-300 bg-white'" },
        { rel: 'src/components/settings/Normal.tsx', text: '<Input className="w-40" h-9 rounded-lg border-neutral-300 />' },
      ]),
    ).toEqual(['src/components/settings/OldField.tsx'])
  })

  it('🔴 标签不得顺排在控件左边（存量台账双向相等 + 只许缩短）', () => {
    const now = inlineLabelOutsiders(FILES).sort()
    expect(now, '「标签 + 同行控件」新写法进不来；修好了请删台账条目').toEqual(
      [...INLINE_LABEL_LEDGER].sort(),
    )
    expect(INLINE_LABEL_LEDGER.length, '台账条数只许下调').toBeLessThanOrEqual(INLINE_LABEL_BASELINE)
    // 判别力自证：旧形态源码 ⇒ 红
    expect(
      inlineLabelOutsiders([
        { rel: 'src/x/Y.tsx', text: '<label>部位<select className="ml-1 inline-block w-auto" /></label>' },
        { rel: 'src/x/Z.tsx', text: '<Field label="部位" unit="米"><select /></Field>' },
      ]),
    ).toEqual(['src/x/Y.tsx'])
  })

  it('🔴 标准本身不许被削弱（`FIELD_CONTROL` 仍是「满列 + 本仓控件铬」）', () => {
    for (const token of ['w-full', 'h-9', 'rounded-lg', 'border-neutral-300', 'focus:ring-2']) {
      expect(FIELD_CONTROL, `FIELD_CONTROL 丢了 ${token}`).toContain(token)
    }
    // 定宽回归（`w-40` 这类）⇒ 红：满列是「标签在上」版式的前提
    expect(FIELD_CONTROL, '控件不得再定宽').not.toMatch(/\bw-(24|32|36|40|64)\b/)
    // 带单位的控件要给单位留位（否则数字压到「米」上）
    expect(FIELD_CONTROL, '基线（无单位）不带单位位').not.toContain('pr-9')
  })

  it('🔴 三个受管面继续用原语（`FormPanel` / `Field` / `FormGrid`）', () => {
    for (const rel of [
      'src/components/settings/CalcCaliberPanel.tsx',
      'src/components/settings/OversizeThresholdPreview.tsx',
      'src/components/production/CuttingHeightConfigPanel.tsx',
    ]) {
      const text = read(rel)
      expect(text, `${rel} 必须从 FormPanel 取字段版式`).toContain("from '@/components/ui/FormPanel'")
      expect(text, `${rel} 必须至少用一个 Field`).toMatch(/<Field[\s>]/)
    }
  })
})
