// case_ids: UI-098
/**
 * 中文标点旁的强调归一化（issue #6910）—— `@/lib/cjk-emphasis` 的**纯函数面**。
 *
 * ## 缺陷（用户 2026-10-14 实测截图）
 *
 * `下单入口：后台的**「订单列表」页**，…` 的 `**` 原样上屏。归因 = CommonMark 的 flanking 规则：
 * 开标记「前=汉字、后=`「`」判**不能开**，闭标记「前=`」`、后=汉字」判**不能闭**（`「」（）《》、，。`
 * 都是 Unicode 标点 P/S，而中文正文里它们紧邻汉字）⇒ 配对不上 ⇒ 星号按字面输出。
 *
 * ## 判据分工（DOM 面在别处，本文件管**文本变换面**）
 *
 * - **本文件**：该插 ZWSP 的边界**逐个钉死**（正控），**不该插的绝不插**（负控 —— 含配对逻辑最关键的反例
 *   `**A**：**B**`：若把作 closer 的标记也 "修" 成能开，后一个 `**B**` 会落单 ⇒ 那是本模块必须避免的回归）；
 * - **DOM 面**：`tests/unit/components/MessageList-cjk-emphasis.test.tsx`（真 `react-markdown`）——
 *   「`**` 不再上屏 + `<strong>` 真的在」两条必须同时成立（只判前者的话，把标记删掉同样绿 = 空判据）。
 *
 * ## 红证（修前实测）
 *
 * 把 `MessageList` 的 `normalizeCjkEmphasis(visibleContent)` 换回 `visibleContent` ⇒ DOM 面「截图原句」
 * 与「整条回复」两条当场红（读数见 PR body）；本文件的负控 `**A**：**B**` 是**改了配对策略就会红**的那条。
 */
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import { normalizeCjkEmphasis, ZWSP } from '@/lib/cjk-emphasis'

const Z = ZWSP

describe('normalizeCjkEmphasis — 中文标点旁强调的零可见变化归一化（issue #6910）', () => {
  it('① 正控（该插的插）：开/闭两侧各自失效的边界各插一个 ZWSP', () => {
    // 截图原句：开标记「前=的、后=「」⇒ 不能开（闭标记那一侧本来就是好的，不动）
    expect(normalizeCjkEmphasis('下单入口：后台的**「订单列表」页**，页面里的「新建订单」入口。')).toBe(
      `下单入口：后台的**${Z}「订单列表」页**，页面里的「新建订单」入口。`
    )
    // 闭合侧失效：闭标记「前=」、后=文」⇒ 不能闭
    expect(normalizeCjkEmphasis('**「重点」**文本')).toBe(`**「重点」${Z}**文本`)
    // 两侧同时失效
    expect(normalizeCjkEmphasis('的**「重点」**文本')).toBe(`的**${Z}「重点」${Z}**文本`)
    // 中文标点族（全角括号 / 书名号 / 顿号）与汉字同形
    expect(normalizeCjkEmphasis('的**（备注）**、和')).toBe(`的**${Z}（备注）**、和`)
    // 两侧同时失效：开标记后插一个、闭标记前插一个
    expect(normalizeCjkEmphasis('见**《手册》**第 3 页')).toBe(`见**${Z}《手册》${Z}**第 3 页`)
  })

  it('② 负控（不该插的绝不插）：本来能配对的标记一个都不动', () => {
    const untouched = [
      '文本**加粗**文本',
      '**重点**（说明）',
      '**重点**「引用」',
      '开头**强调**',
      '**强调**结尾',
      // 🔴 配对逻辑的关键反例：`：` 两侧的标记本来各司其职（closer / opener）——
      // 若把 closer 也"修"成能开，后面的 `**B**` 会落单 ⇒ 星号上屏（本模块最危险的回归）
      '**A**：**B**',
      '**A**，**B**',
      // 非强调形态：蛇形命名 / 算式 / 掩码 / 单星列表 / 未闭合（流式中途）
      'snake_case_name 与 a_b_c',
      '2*3*4 = 24',
      '手机号 138****8888',
      '* 列表项不是强调',
      '的**「订单列表」页（流式未闭合，原样保留）',
      // 有意收窄：纯 ASCII 的同类失效不修（否则 `(**kwargs)` 这类代码随笔会被插入 ZWSP）
      'abc**"x"**def',
      'def f(**kwargs)',
    ]
    for (const text of untouched) {
      expect(normalizeCjkEmphasis(text), `不该改：${text}`).toBe(text)
      expect(normalizeCjkEmphasis(text).includes(Z), `不得插入 ZWSP：${text}`).toBe(false)
    }
  })

  it('③ 代码面逐字不动：行内代码与围栏代码块里的 `**` 既不配对也不插 ZWSP', () => {
    const inline = '看代码 `a**「x」**b` 与 `**kwargs`，正文 的**「说明」**。'
    const out = normalizeCjkEmphasis(inline)
    expect(out).toContain('`a**「x」**b`')
    expect(out).toContain('`**kwargs`')
    // 正文那一处该修的仍要修（代码面跳过 ≠ 整行跳过）
    expect(out).toContain(`的**${Z}「说明」**`)

    const fenced = ['示例：', '```python', 'print("中文**「不会被动」**")', '```', '正文 的**「会动」**'].join('\n')
    const fencedOut = normalizeCjkEmphasis(fenced)
    expect(fencedOut).toContain('print("中文**「不会被动」**")')
    expect(fencedOut).toContain(`的**${Z}「会动」**`)
  })

  it('④ 类级：凡 import `react-markdown` 渲染正文的组件都必须经 `normalizeCjkEmphasis`（新渲染点漏接 ⇒ 红）', () => {
    const files = walk(join(process.cwd(), 'src'))
    const renderers = files.filter((f) => readFileSync(f, 'utf-8').includes("from 'react-markdown'"))
    // 自证非空：面消失时报绿 = 判据失效（fail-closed）
    expect(renderers.length, '扫描面里没有 react-markdown 渲染点 ⇒ 本判据在空集上恒真').toBeGreaterThan(0)
    const unnormalized = renderers
      .filter((f) => !readFileSync(f, 'utf-8').includes('normalizeCjkEmphasis('))
      .map((f) => relative(process.cwd(), f))
    expect(
      unnormalized,
      '这些组件用 CommonMark 渲染商家可见正文，却没经 `normalizeCjkEmphasis` ⇒ 汉字紧邻中文标点的 `**` 会原样上屏'
    ).toEqual([])
  })
})

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    if (entry.name === 'node_modules' || entry.name === '.next') return []
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return walk(path)
    return /\.(tsx?|jsx?)$/.test(entry.name) ? [path] : []
  })
}
