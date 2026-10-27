// case_ids: BM-052, BM-018
/**
 * 零命中时的**模糊搜索下拉候选**（issue #7892）—— 端侧纯逻辑判据
 *
 * 用户 2026-10-27 逐字：「手机端拍照入库如果未识别出商品&货号，要允许用户可以选择，通过输入模糊搜索下拉框来选中」。
 * 改造前（issue #7759 的形态）= 输入框 + **「搜货号」按钮** + 整宽按钮列表（要点一下才出，且在长列表里找）。
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | C1 | **短于 2 字不下发**（与 `GET /api/worker/inbound/skus` 的 400 同口径：至少 2 个字 / 2 位货号） | `canSuggest('2')` 返回 true ⇒ 红（一次 400 + 一句无意义提示） |
 * | C2 | **空白不算字**：`'  '` / `' 2659 '` 的判定按 trim 后长度 | 不 trim ⇒ 两个空格就当成 2 个字去扫库 ⇒ 红 |
 * | C3 | 🔴 **后发先至**：旧查询的响应**不得**覆盖新查询的候选 —— 先搜 `26`（慢）再搜 `2659`（快）⇒ 慢的那个 `stale=true` | 去掉 `latest` 判据 ⇒ 慢响应回来把 `2659` 的候选顶掉 ⇒ 工人选到别的货号 = **错库存**（红） |
 * | C4 | **失败也走同一个口径**：请求抛异常 ⇒ `outcome.ok=false` + 一句可行动文案（不抛给页面），乱序判定照旧 | 让异常冒出去 ⇒ 页面上是空白下拉（工人不知道该干嘛） |
 * | C5 | **提示只说事实 + 下一步**：0 条 ⇒ 换写法；N 条 ⇒ 找到 N 个、点一个；超过展示上限 ⇒ 明说只列前 N 个 | 截断了却仍写「找到 N 个」⇒ 工人以为只有这几条（红） |
 * | C6 | **类级元守卫**：页面/组件里凡直接用 `searchInboundSkus(` 的，必须经 `createSuggestRunner(`（带防抖 / 乱序守卫的唯一入口）—— 否则新页面又会手搓一个「裸 await 结果直接上屏」 | 新增一个页面裸调 `searchInboundSkus()` 并把结果塞进 state ⇒ 红（未登记即红） |
 */
import fs from 'fs'
import path from 'path'
import {
  SUGGEST_MIN_CHARS,
  SUGGEST_SHOW_LIMIT,
  SUGGEST_TOO_SHORT_HINT,
  canSuggest,
  createSuggestRunner,
  suggestHint,
  suggestQueryOf,
  type SuggestOutcome,
} from '../src/utils/inbound/skuSuggest'
import type { SkuMatch } from '../src/utils/inbound/recognizeGate'

const ROOT = path.resolve(__dirname, '..')

const ROW = (skuId: string, skuCode: string): SkuMatch => ({
  skuId,
  productId: 'p1',
  productName: '奶油风纯色遮光窗帘 桂月白露系列',
  skuCode,
  colorName: '2659-04 绵绵奶咖',
  doorWidth: '2.8',
})

/** 手控 resolve 的 promise（用来逐字复现「先发后至」的真实顺序） */
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

describe('零命中模糊搜索下拉（issue #7892）', () => {
  it('C1 短于 2 字不下发；2 字起才查（与服务端的最小长度同口径）', () => {
    expect(SUGGEST_MIN_CHARS).toBe(2)
    expect(canSuggest('')).toBe(false)
    expect(canSuggest('2')).toBe(false)
    expect(canSuggest('26')).toBe(true)
    expect(canSuggest('绵绵')).toBe(true)
    expect(SUGGEST_TOO_SHORT_HINT).toContain('至少 2 个字')
  })

  it('C2 空白不算字：判定按 trim 后长度（两个空格不许去扫库）', () => {
    expect(suggestQueryOf('  ')).toBe('')
    expect(canSuggest('  ')).toBe(false)
    expect(suggestQueryOf(' 2659 ')).toBe('2659')
    expect(canSuggest(' 2659 ')).toBe(true)
  })

  it('C3 后发先至：慢的旧查询被判 stale，面板不会回弹成旧候选', async () => {
    const slow = deferred<SuggestOutcome>()
    const fast = deferred<SuggestOutcome>()
    const pending = [slow, fast]
    const run = createSuggestRunner(async () => {
      const next = pending.shift()
      if (!next) throw new Error('unexpected third query')
      return next.promise
    })

    const first = run('26')
    const second = run('2659')
    // 新查询先回（快），旧查询后回（慢）—— 真实网络里这就是常态
    fast.resolve({ ok: true, matches: [ROW('fast', '2659-04-28')] })
    const secondAnswer = await second
    slow.resolve({ ok: true, matches: [ROW('slow', '2600-01-28')] })
    const firstAnswer = await first

    expect(secondAnswer.stale).toBe(false)
    expect(secondAnswer.query).toBe('2659')
    expect(secondAnswer.outcome.ok && secondAnswer.outcome.matches[0].skuId).toBe('fast')
    // 红证：去掉 runner 里的 `latest` 判据 ⇒ 这一条变 false ⇒ 红
    expect(firstAnswer.stale).toBe(true)
  })

  it('C4 请求抛异常 ⇒ 折成可行动文案（不把异常冒给页面），乱序判定照旧', async () => {
    const run = createSuggestRunner(async () => {
      throw new Error('断网了')
    })
    const answer = await run('2659')
    expect(answer.stale).toBe(false)
    expect(answer.outcome.ok).toBe(false)
    expect(answer.outcome.ok === false && answer.outcome.message).toContain('断网了')
  })

  it('C5 提示只说事实 + 下一步（0 条 / N 条 / 超过展示上限要说明只列前 N 个）', () => {
    expect(suggestHint(0)).toContain('没搜到')
    expect(suggestHint(2)).toContain('找到 2 个货号')
    expect(suggestHint(2)).toContain('点一个')
    expect(suggestHint(SUGGEST_SHOW_LIMIT + 5)).toContain(`只列前 ${SUGGEST_SHOW_LIMIT} 个`)
  })

  it('C6 类级元守卫：凡直接用 searchInboundSkus( 的页面/组件，必须经 createSuggestRunner(', () => {
    const files: string[] = []
    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) walk(full)
        else if (/\.(ts|tsx)$/.test(entry.name)) files.push(full)
      }
    }
    walk(path.join(ROOT, 'src/pages'))
    walk(path.join(ROOT, 'src/components'))

    const offenders = files.filter((file) => {
      const source = fs.readFileSync(file, 'utf8')
      return source.includes('searchInboundSkus(') && !source.includes('createSuggestRunner(')
    })
    expect(offenders).toEqual([])
    // 判别力自证：本守卫确实扫到了页面（不是空扫）
    expect(files.length).toBeGreaterThan(20)
  })
})
