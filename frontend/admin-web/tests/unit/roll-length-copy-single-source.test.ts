// case_ids: PR-044
/**
 * 类级元守卫：卷长文案**只有一个来源**（issue #5919，铁律 8 的类级固化）。
 *
 * 病：同一个字段的展示文案写在**两处**（商品表单的字段标签 + 商品详情页的 `dt`）⇒ 下次只改一边、
 * 两边说法就不一致了，而没有东西会红。用户裁定（2026-10-01）：「1 卷 = 多少米」正名为**标称值**，
 * 并补副说明「仅作建单时的默认值与整卷换算，实际卷长以入库单 / 订单行为准」，两处**同源**。
 *
 * 本判据把「同源」变成机械口径：
 *   ① 关键串**只许**出现在 `src/lib/product-roll-length.ts` 这一处（第二份字面量 ⇒ 红）；
 *   ② 两个消费方（商品表单 / 商品详情页）都必须**引用**该模块的常量（少一处 ⇒ 红，防只改一边）；
 *   ③ 常量字面量本身必须保住「标称」与「以入库单 / 订单行为准」的指向（措辞被稀释 ⇒ 红）。
 *
 * 扫描前剥掉注释：判的是**会上屏的字面量**，不是「源码里有没有这句话」
 * （注释里解释这条口径是允许的，也正是本文件在做的事）。
 * 边界（如实登记）：字符串里的 `//`（如 URL）会被行注释剥掉 ⇒ **只会少扫、不会假红**。
 */
import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync, readdirSync, statSync } from 'fs'
import { join, relative } from 'path'

/** 包根（vitest 的 cwd = `frontend/admin-web`） */
const ROOT = process.cwd()
const SRC = join(ROOT, 'src')
const SKIP_DIRS = new Set(['node_modules', '.next', 'dist', 'coverage'])

/** 唯一允许存在这份文案的地方（单点定义） */
const MODULE = 'src/lib/product-roll-length.ts'
/** 必须引用它的两个展示面（少一个 ⇒ 红） */
const CONSUMERS = [
  'src/components/products/ProductForm.tsx',
  'src/app/(dashboard)/products/[id]/ProductDetail.tsx',
]
/** 关键串：任何**第二处**字面量出现 ⇒ 红（「两处各写一份」正是本单要防的复发形态） */
const CANONICAL = ['1 卷 = 多少米（标称）', '实际卷长以入库单', '仅作建单时的默认值', '标称值']

/** 剥掉注释（块注释含 JSX `{/* … *\/}`；行注释只剥整行 —— 避免把字符串里的 `//` 误当注释） */
function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
}

/** 纯判据：文本里是否已有这份文案的字面量（可在内存里自证判别力） */
const containsCanonicalCopy = (text: string): boolean => CANONICAL.some((s) => text.includes(s))

/** 从模块源码里取某个导出的**字面量值**（拿不到 ⇒ null） */
function literalOf(source: string, name: string): string | null {
  const m = source.match(new RegExp(`export const ${name}\\s*=\\s*(['"\`])([\\s\\S]*?)\\1`))
  return m ? m[2] : null
}

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) sourceFiles(full, out)
    else if (/\.(tsx|ts)$/.test(entry)) out.push(full)
  }
  return out
}

describe('卷长文案单点定义（issue #5919）', () => {
  const modulePath = join(ROOT, MODULE)
  const hits = sourceFiles(SRC)
    .map((f) => ({ file: relative(ROOT, f).split('\\').join('/'), text: stripComments(readFileSync(f, 'utf-8')) }))
    .filter((x) => containsCanonicalCopy(x.text))
    .map((x) => x.file)

  it('普查面自证：单点定义处命中（扫不到 ⇒ 判据在扫空气；模块被搬走 / 改名请同步 MODULE）', () => {
    expect(existsSync(modulePath), `单点定义模块不存在：${MODULE}`).toBe(true)
    expect(hits, `${MODULE} 应命中关键串`).toContain(MODULE)
  })

  it('关键串只许出现在单点定义处：第二处硬编码 ⇒ 红', () => {
    const offenders = hits.filter((h) => h !== MODULE)
    expect(
      offenders,
      `这些文件里又写了一份卷长文案：${offenders.join('、')}。`
        + `出口：改成从 '@/lib/product-roll-length' 引常量（ROLL_LENGTH_LABEL / ROLL_LENGTH_HINT），`
        + '不要各写一份。',
    ).toEqual([])
  })

  it('两个展示面都必须引用同一份常量（少一处 ⇒ 红，防「只改一边」）', () => {
    for (const consumer of CONSUMERS) {
      const p = join(ROOT, consumer)
      expect(existsSync(p), `消费方不存在：${consumer}（被删/搬走 ⇒ 请同步 CONSUMERS）`).toBe(true)
      const text = readFileSync(p, 'utf-8')
      expect(text, `${consumer} 未从 ${MODULE} 引入卷长文案`).toContain("from '@/lib/product-roll-length'")
      for (const name of ['ROLL_LENGTH_LABEL', 'ROLL_LENGTH_HINT']) {
        expect(text, `${consumer} 未使用 ${name}`).toContain(name)
      }
    }
  })

  it('措辞不许被稀释：标签含「标称」，副说明指向入库单 / 订单行（两处渲染同一份）', () => {
    const source = readFileSync(modulePath, 'utf-8')
    const label = literalOf(source, 'ROLL_LENGTH_LABEL')
    const hint = literalOf(source, 'ROLL_LENGTH_HINT')
    expect(label, 'ROLL_LENGTH_LABEL 必须是字面量导出').toBeTruthy()
    expect(label!).toContain('标称')
    expect(label!).toContain('1 卷 = 多少米')
    expect(hint, 'ROLL_LENGTH_HINT 必须是字面量导出').toBeTruthy()
    expect(hint!).toContain('标称')
    expect(hint!).toContain('默认值')
    expect(hint!).toContain('实际卷长以入库单')
    expect(hint!).toContain('订单行')
  })

  it('判别力自证：第二份字面量 / 常量化引用两种情况各自判红与判绿', () => {
    // ① 硬编码第二处 ⇒ 命中（红）
    expect(containsCanonicalCopy('<dt className="text-xs">1 卷 = 多少米（标称）</dt>')).toBe(true)
    // ② 引用常量 ⇒ 不命中（绿）
    expect(containsCanonicalCopy('<dt>{ROLL_LENGTH_LABEL}</dt>')).toBe(false)
    // ③ 剥注释后不再命中（注释里解释口径不算上屏文案）
    expect(containsCanonicalCopy(stripComments('// 标称值：仅作建单时的默认值…'))).toBe(false)
    // ④ 字面量取值器不是空转
    expect(literalOf("export const A = 'x'", 'A')).toBe('x')
    expect(literalOf('export const A = f()', 'A')).toBeNull()
  })
})
