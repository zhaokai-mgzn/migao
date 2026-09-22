// case_ids: UI-046
/**
 * React 钩子纪律门禁（真缺陷版）—— 防「渲染期读写 ref / 声明前访问 / 渲染期 Date.now()」复发。
 *
 * 为什么需要这条测试（而不是只靠 CI 的 `npm run lint`）：
 * 这 3 条规则命中的是**与 React Compiler 无关的真实代码缺陷**，`#5105`（Next 16 升级）
 * 当时为维持升级前口径把它们连同另外 11 条编译器规则一起 `off` 了 —— 等于把真缺陷
 * **重新藏起来**。本包逐条修好后把 3 条**收紧为 error**，并用本测试把它钉死：
 *   · 规则若被重新改回 `off`（回退）⇒ 违规不再上报 ⇒ 本测试**必须变红**；
 *   · 源码若重新引入同类缺陷 ⇒ 同样变红。
 *
 * 判别力自证（红证）：把任一被修文件恢复到 `#5105` 的形态（如 useOrderAmounts 的
 * `orderTotalRef.current = orderTotal` 渲染期赋值），本测试即报出对应违规。
 */
import { describe, it, expect } from 'vitest'
import { ESLint } from 'eslint'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ADMIN_WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

/** 本包修好、并因此收紧为 error 的 3 条规则（与 eslint.config.mjs 的 REFS_PURITY_RULES 同源语义）。 */
const GUARDED_RULES = ['react-hooks/refs', 'react-hooks/immutability', 'react-hooks/purity']

describe('React 钩子纪律门禁（UI-046 · 渲染期 ref / 声明前访问 / 渲染期 Date.now()）', () => {
  it('src/ 全域对这 3 条规则零违规（规则被改回 off 或缺陷复发都会红）', async () => {
    const eslint = new ESLint({ cwd: ADMIN_WEB_ROOT })
    const results = await eslint.lintFiles(['src/**/*.{ts,tsx}'])

    const violations = results.flatMap((r) =>
      r.messages
        .filter((m) => m.ruleId !== null && GUARDED_RULES.includes(m.ruleId))
        .map((m) => `${path.relative(ADMIN_WEB_ROOT, r.filePath)}:${m.line} ${m.ruleId} — ${m.message.split('\n')[0]}`),
    )

    expect(violations).toEqual([])
  }, 120_000)

  it('这 3 条规则在配置里是 error（不是 off / warn）—— 防「静默放宽」', async () => {
    const eslint = new ESLint({ cwd: ADMIN_WEB_ROOT })
    const config = await eslint.calculateConfigForFile(path.join(ADMIN_WEB_ROOT, 'src/hooks/useNow.ts'))
    const levels = GUARDED_RULES.map((r) => [r, config.rules?.[r]?.[0]] as const)

    for (const [rule, level] of levels) {
      expect(`${rule}=${level}`).toBe(`${rule}=2`)
    }
  }, 120_000)
})
