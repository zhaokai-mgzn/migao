// case_ids: BM-034
/**
 * 类级守卫：工人端页头 / 行内的 **Taro `Button` 必须显式 `width: auto`**（issue #7921）
 *
 * ## 治的形态（2026-10-27 用户真机截图）
 *
 * 「待发货单」页的标题「待发货单」「当前工人：验收工人」被挤成**竖排**，刷新按钮独占整行。
 * 根因不在文案、不在数据：Taro 的 `Button` 默认 `width: 100%`（`.taro-button-core`），
 * 在 `display: flex` 的页头里只写 `flex: 0 0 auto` 不够 —— `flex-basis: auto` 会去用那条 100%
 * ⇒ 标题被压到最小内容宽度（中文逐字折行 = 竖排）。
 *
 * 同一病灶此前已在 `pages/worker/home/index.scss` 的 `&__ghost` 上修过一次并留了注释
 * （说明它**会复发**：新页面照抄「flex 页头 + Button」就会再踩一遍）。
 *
 * ## 判据（两条，都会红）
 *
 * 1. **实例**：`pages/worker/shipment-orders/index.scss` 的 `&__refresh` 必须同时声明
 *    `width: auto` 与 `white-space: nowrap`（还原成本单修前形态 ⇒ 红）；
 * 2. **类级**：`src/pages/worker/**` 下所有「动作类」块（`__refresh|__ghost|__retry|__login|
 *    __submit|__primary|__action`）只要写了 `flex: 0 0 auto`，就必须同时写 `width: auto`
 *    （新页面照抄旧写法 ⇒ 红）。
 *
 * ## 边界（照实登记）
 *
 * - 它判的是**样式声明**，不是真几何 —— jsdom 没有布局引擎，真机观感仍靠 §15.7 读图；
 * - 「动作类」是按**命名约定**认的（本仓工人页的既有命名）；起了新名字的按钮类不在射程内
 *   （这一条如实登记，别把本守卫读成「所有 Button 都被管住」）。
 */
import fs from 'fs'
import path from 'path'

const ROOT = path.resolve(__dirname, '..')
const WORKER_PAGES = 'src/pages/worker'
const SHIPMENT_REL = `${WORKER_PAGES}/shipment-orders/index.scss`

/** 剥行注释与块注释 —— 注释里提到 `width: auto` 不算声明（与同族样式守卫同口径）。 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
}

/** 取某个 `&__xxx {` 选择器块（按 `{`/`}` 配对；找不到 ⇒ 空串，由断言具名报错）。 */
function blockOf(source: string, selector: string): string {
  const at = source.indexOf(selector)
  if (at < 0) return ''
  const open = source.indexOf('{', at)
  if (open < 0) return ''
  let depth = 0
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1
    else if (source[i] === '}') {
      depth -= 1
      if (depth === 0) return source.slice(open + 1, i)
    }
  }
  return source.slice(open + 1)
}

/** 动作类块名（页头 / 行内动作 —— 这些块里的 `Button` 默认 100% 宽会被 flex 兄弟挤扁）。 */
const ACTION_BLOCKS = [
  '&__refresh',
  '&__ghost',
  '&__retry',
  '&__login',
  '&__submit',
  '&__primary',
  '&__action',
]

export interface ScssFile {
  /** 仓库相对（bmini 根）路径，用于具名报错 */
  rel: string
  /** 剥过注释的 scss 文本 */
  css: string
}

/**
 * 找出「只写 flex: 0 0 auto、却不写 width: auto」的动作类块（= 会被 100% 宽挤扁的形态）。
 *
 * @returns 逐条问题（空数组 = 零违规）
 */
export function widthProblems(files: ScssFile[]): string[] {
  const problems: string[] = []
  for (const file of files) {
    for (const selector of ACTION_BLOCKS) {
      const block = blockOf(file.css, selector)
      if (block === '') continue
      if (!/flex:\s*0\s+0\s+auto/.test(block)) continue
      if (!/width:\s*auto/.test(block)) {
        problems.push(
          `${file.rel}: ${selector} 写了 \`flex: 0 0 auto\` 却没有 \`width: auto\` —— ` +
            'Taro Button 默认 width:100%，flex-basis:auto 会吃那条 100% ⇒ 页头标题被挤成竖排（issue #7921）',
        )
      }
    }
  }
  return problems
}

/** 工人端全部页面样式（现扫磁盘，不写死清单）。 */
function readWorkerScss(): ScssFile[] {
  const base = path.join(ROOT, WORKER_PAGES)
  const out: ScssFile[] = []
  const walk = (dir: string): void => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const abs = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(abs)
      else if (entry.name.endsWith('.scss')) {
        out.push({
          rel: path.relative(ROOT, abs),
          css: stripComments(fs.readFileSync(abs, 'utf8')),
        })
      }
    }
  }
  walk(base)
  return out
}

describe('工人端 Taro Button 宽度守卫（issue #7921）', () => {
  it('① 实例：待发货单页的「刷新」显式 width: auto + nowrap（修前形态 ⇒ 红）', () => {
    const scss = stripComments(fs.readFileSync(path.join(ROOT, SHIPMENT_REL), 'utf8'))
    const refresh = blockOf(scss, '&__refresh')
    expect(refresh).not.toBe('')
    expect(refresh).toMatch(/width:\s*auto/)
    expect(refresh).toMatch(/white-space:\s*nowrap/)
  })

  it('② 类级：工人端所有动作类块「flex: 0 0 auto ⇒ 必须 width: auto」', () => {
    const files = readWorkerScss()
    // 反空跑：真的扫到了工人页样式与至少一个动作块
    expect(files.length).toBeGreaterThanOrEqual(5)
    expect(files.some((file) => /&__refresh/.test(file.css))).toBe(true)
    expect(widthProblems(files)).toEqual([])
  })

  it('③ 红证（内存变异，不落仓库）：摘掉待发货单页的 width: auto ⇒ 判红且具名', () => {
    const original = stripComments(fs.readFileSync(path.join(ROOT, SHIPMENT_REL), 'utf8'))
    const mutated = original.replace(/(&__refresh\s*\{[\s\S]*?)\n\s*width:\s*auto;/, '$1')
    // 变异自证：真的摘掉了（否则本红证退化成空断言）
    expect(mutated).not.toBe(original)
    const problems = widthProblems([{ rel: SHIPMENT_REL, css: mutated }])
    expect(problems.join('\n')).toContain(SHIPMENT_REL)
    expect(problems.join('\n')).toContain('&__refresh')
    expect(problems.join('\n')).toContain('width: auto')
  })

  it('④ 对照：写了 width: auto 的动作块不判红（守卫不是「见到动作类就红」）', () => {
    const ok = '&__ghost { flex: 0 0 auto; width: auto; }'
    expect(widthProblems([{ rel: 'x', css: ok }])).toEqual([])
    const bad = '&__ghost { flex: 0 0 auto; }'
    expect(widthProblems([{ rel: 'x', css: bad }])).toEqual([
      expect.stringContaining('&__ghost'),
    ])
  })
})
