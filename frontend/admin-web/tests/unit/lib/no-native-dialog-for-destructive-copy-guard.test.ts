// case_ids: CU-010, UI-046
// 破坏性动作不得走原生 window.prompt（issue #6669 第 3 条）。
/**
 * 类级元守卫：**破坏性动作不得用原生 `window.prompt` 收原因**（issue #6669 第 3 条）。
 *
 * ## 为什么是类级而不是只修那一处
 *
 * 修前的余料台账「报废」逐字是 `const reason = window.prompt('报废原因…')`。原生 prompt 的代价：
 * ① **没有上下文**（弹层里看不到要报废的是哪一块：尺寸 / 来源订单 / 缸号都没了）；
 * ② **没有「不可撤销」说明**（报废是不可逆的账，商家点确定才知道收不回）；
 * ③ 样式与可访问性不可控、且**不可测**（jsdom 里 `window.prompt` 是 no-op ⇒ 这条行为永远零判据）。
 * 只改这一处 = 没修：下一个人写第二个破坏性动作时可以把同一形态原样加回来。
 *
 * ## 判据
 *
 * ① **未登记即红**：`src/**` 里出现 `window.prompt(` / 裸 `prompt(` ⇒ 红（并具名 `文件:行号`）；
 * ② **台账只许缩短**（`migao-dev-flow` §19.1 / §23）：存量豁免表在下面，`length` 超过冻结基线 ⇒ 红；
 * ③ **判别力自证**：对**历史坏形态**（本单修前的逐字写法）必检出；且
 *    **注释/字符串里的同形态不误伤**（本仓注释惯例会引用这些串 —— 判据被自己的文案喂红是实测过的坑）。
 *
 * ## 出口
 *
 * 走自研 `Modal`（`@/components/ui`）：带上下文 + 「无法撤销」说明 + 具名确认按钮。
 * 参考实现 = `frontend/admin-web/src/app/(dashboard)/production/remnants/page.tsx` 的报废弹层。
 */
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ADMIN_WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')

/**
 * 存量豁免（**只许缩短**）：允许保留**非破坏性**用途的原生 prompt —— 富文本编辑器「插入链接」
 * 收一个 URL / 显示文字，不涉及不可逆动作、也没有业务上下文可给。
 * ⚠️ 新增任何条目都会让下面的「台账只许缩短」判据红 ⇒ 必须先在 PR 里说明为什么它不是破坏性动作。
 */
const ALLOWLIST = ['src/components/products/RichTextEditor.tsx']
const ALLOWLIST_FLOOR = 1

/**
 * 单行归一：**先剥注释、再掩字符串内容**（保留引号本身），**逐行**做。
 *
 * ## 为什么必须逐行、且这个顺序（两个坑都是实测出来的，如实登记）
 *
 * ① **只剥注释**（不掩字符串）会把**注释里的整行**一起带走 —— 实测：`// 修前走 window.prompt(…) —— 已改为…`
 *    这一行连同**后续多行**被行注释规则吞掉，导致**真代码行也检不出来**（假绿）；
 * ② **先掩模板串再掩引号**会把整行模板（含行内真实代码）一起掩掉 —— 夹具自己把自己吃了。
 *
 * ⇒ 逐行：行注释不会跨行误吞；先剥注释（注释里的字面量不该算证据），再把字符串**内容**掩成 `x`
 *   （引号保留 ⇒ `window.prompt(` 形态仍在），模板串**最后**处理。
 *
 * ## 边界（如实登记）
 *
 * - 多行 `/* … *\/` 块注释**内部**的行不做状态跟踪（实测本仓 `src/**` 无此形态干扰）；
 * - `…${'x'}…` 这类**插值里藏 prompt** 的形态检不出（有意不做解析器：那是故意绕守卫，不是顺手写坏）。
 */
export function maskCommentsAndStrings(code: string): string {
  return code
    .split('\n')
    .map((line) =>
      line
        .replace(/\/\*[\s\S]*?\*\//g, '')      // 单行内的块注释片段
        .replace(/(^|[^:])\/\/.*$/, '$1')      // 行注释（`[^:]` 避开 http://）
        .replace(/'[^']*'/g, "'x'")            // 单引号串内容
        .replace(/"[^"]*"/g, '"x"')            // 双引号串内容
        .replace(/`[^`]*`/g, '`x`'),           // 模板串（排最后：见上面 ②）
    )
    .join('\n')
}

/** 检出「原生 prompt 收输入」的调用；返回 `文件:行号` 列表 */
export function detectNativePrompt(code: string, file = 'snippet'): string[] {
  const hits: string[] = []
  maskCommentsAndStrings(code)
    .split('\n')
    .forEach((line, i) => {
      // `window.prompt(`（点号形态）与裸 `prompt(`（全局别名）**都算**；`customPrompt(` 这类标识符后缀不算。
      // 🔴 正则必须同时容下这两种前缀（实测踩过两次，判据都表现为「恒绿」）：
      //   ① `(?:^|[^.\w])prompt` 会**回溯**（把 `window` 的 `d` 让给字符类）⇒ 点号形态检不出；
      //   ② 只写 `(?<![.\w])prompt` 又把点号形态**排除**了 ⇒ 同样检不出。
      // 后顾 = 「前面不是字母/数字/下划线」（点号允许 ⇒ 容下 `window.prompt(`）。
      if (/(?<![\w$])prompt\s*\(/.test(line)) hits.push(`${file}:${i + 1}`)
    })
  return hits
}

function collectSourceFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) return collectSourceFiles(full)
    return /\.tsx?$/.test(entry.name) ? [full] : []
  })
}

describe('破坏性动作不用原生 window.prompt（#6669 第 3 条 · 类级元守卫）', () => {
  it('① src/ 全域零「未登记的 window.prompt 收输入」', () => {
    const files = collectSourceFiles(path.join(ADMIN_WEB_ROOT, 'src'))
    const violations = files
      .flatMap((f) => detectNativePrompt(fs.readFileSync(f, 'utf-8'), path.relative(ADMIN_WEB_ROOT, f)))
      .filter((v) => !ALLOWLIST.includes(v.split(':')[0]))

    expect(files.length).toBeGreaterThan(100) // 扫描面自证（不是空集上恒真）
    expect(violations).toEqual([])
  }, 60_000)

  it('② 台账只许缩短（冻结基线 %d）', () => {
    expect(ALLOWLIST.length).toBeLessThanOrEqual(ALLOWLIST_FLOOR)
    for (const rel of ALLOWLIST) {
      // 豁免项必须真实存在且**真的**还带着该形态 ⇒ 留着一条失效豁免会让判据悄悄放宽
      const p = path.join(ADMIN_WEB_ROOT, rel)
      expect(fs.existsSync(p), `豁免项不存在：${rel}`).toBe(true)
      expect(detectNativePrompt(fs.readFileSync(p, 'utf-8'), rel).length, `豁免项已不再命中：${rel}`).toBeGreaterThan(0)
    }
  })

  it('③ 判别力自证：历史坏形态必检出，注释/字符串里的同形态不误伤', () => {
    // 历史坏形态（本单修前的逐字写法）—— 用**拼接**而不是模板串：
    // 模板串的 `[^`]*` 规则会把单行模板整体掩掉，夹具自己就被吃掉了（实测踩过）
    const bad = 'const reason = ' + 'window.prompt(' + "'报废原因（报废要留痕：谁、何时、为什么）'" + ')'
    expect(detectNativePrompt(bad, 'bad.tsx')).toEqual(['bad.tsx:1'])

    // 出口形态（修后的自研 Modal）⇒ 不得检出
    const good = 'setScrapTarget(row.id); await remnantApi.scrap(id, reason.trim())'
    expect(detectNativePrompt(good, 'good.tsx')).toEqual([])

    // 说明性注释与字符串**不得**误伤（本仓注释惯例就会引用这些串）
    const commented = [
      '// 修前走 ' + 'window.prompt(' + "'报废原因…')" + ' —— 已改为自研 Modal',
      '/* 实例：' + 'window.prompt(' + "'xx') */",
      'const s = "' + 'window.prompt(' + "'yy')\"",
    ].join('\n')
    expect(detectNativePrompt(commented, 'doc.tsx')).toEqual([])

    // 标识符后缀不算（防误伤 `customPrompt(` 这类）
    expect(detectNativePrompt("customPrompt('x')", 'id.tsx')).toEqual([])
    // 裸 `prompt(`（全局别名，等价形态）**要算**
    expect(detectNativePrompt("const r = prompt('原因')", 'bare.tsx')).toEqual(['bare.tsx:1'])
  })
}, 120_000)
