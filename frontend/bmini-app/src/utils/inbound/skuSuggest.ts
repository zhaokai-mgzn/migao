/**
 * 零命中时的**模糊搜索下拉候选**（issue #7892）—— 端侧纯逻辑，不碰网络。
 *
 * 用户 2026-10-27 逐字：「手机端拍照入库如果未识别出商品&货号，要允许用户可以选择，
 * 通过输入模糊搜索下拉框来选中」。
 *
 * 处境：拍照入库没认出商品 / 货号（`evaluateSkuGate` 返回 `none`）⇒ 工人只能自己在**既有**货号里找。
 * 改造前（issue #7759 的形态）= 输入框 + 「搜货号」**按钮** + 整宽按钮列表：要点一下才出结果，
 * 出来还得在长列表里看。本模块给「边输边出候选、点一条即选中」提供三条**只有端侧才需要判**的口径
 * （服务端只负责 `LIKE` 查 20 条）：
 *
 * | 判据 | 坏形态 |
 * |---|---|
 * | ① **短于 2 字不下发**（与 `GET /api/worker/inbound/skus` 的 400 同口径） | 一次 400 + 一句「请至少输入 2 字」，白跑 |
 * | ② **后发先至**：旧查询的响应不许覆盖新查询的候选 | 先搜 `26`（慢）后搜 `2659`（快）⇒ 面板回弹成 `26` 那批 ⇒ 工人选到别的货号 = **错库存** |
 * | ③ **展示截断要说清** | 明明只列了前几条，却写「找到 N 个」⇒ 工人以为就这几条 |
 *
 * ⚠️ 不在这里写业务口径：命中规则（型号 / 货号归一 + 色名消歧 + 门幅判定）的唯一真值在服务端
 * `WorkerInboundService`；本模块只决定「什么时候问、问回来的还算不算数、怎么念给工人听」。
 * 防抖的**时长**也只在这里一处（`SUGGEST_DEBOUNCE_MS`），页面不许自带第二个魔法数字。
 */
import type { SkuMatch } from './recognizeGate'

/** 与服务端最小长度同口径（`INBOUND_SKU_SEARCH_TOO_SHORT`：至少 2 个字 / 2 位货号） */
export const SUGGEST_MIN_CHARS = 2

/** 停手多久才发请求：每敲一个字就发 ⇒ `2659-04` 一次输入 = 6 个请求 */
export const SUGGEST_DEBOUNCE_MS = 300

/** 下拉最多列几条（手机上再多也没人滚；服务端另有 20 条上限，那是服务端的真值，不在端侧重写） */
export const SUGGEST_SHOW_LIMIT = 8

/** 还没到 2 个字时的话（说清「还差多少」，不是一句「输入太短」） */
export const SUGGEST_TOO_SHORT_HINT = '再输入 1 个字或 1 位货号就能搜（至少 2 个字）'

/** 输入框里的查询词（两头空白不算字 —— `'  '` 不是一次有效查询） */
export function suggestQueryOf(raw: string | null | undefined): string {
  return String(raw ?? '').trim()
}

/** 够不够长到值得问一次 */
export function canSuggest(raw: string | null | undefined): boolean {
  return suggestQueryOf(raw).length >= SUGGEST_MIN_CHARS
}

/**
 * 候选下面的那句话：**只说事实 + 下一步**（migao-dev-flow §31 P4：不催、不惊叹）。
 *
 * `count` = 服务端这次的命中条数（不是渲染条数）—— 超过展示上限时**明说只列了前 N 个**，
 * 否则工人会把「只列 8 个」读成「库里只有 8 个」。
 */
export function suggestHint(count: number): string {
  if (!Number.isFinite(count) || count <= 0) return '没搜到这个货号：换个写法，或只输入色名 / 货号的一部分'
  if (count > SUGGEST_SHOW_LIMIT) {
    return `找到 ${count} 个货号，只列前 ${SUGGEST_SHOW_LIMIT} 个；再输入几个字更准`
  }
  return `找到 ${count} 个货号，点一个选中`
}

/** 一次查询的结果（失败也折成这个形状：页面只认「有候选 / 一句可行动的话」） */
export type SuggestOutcome = { ok: true; matches: SkuMatch[] } | { ok: false; message: string }

/** 一次查询的**回执**：`stale` = 这次的结果已经过期（期间又发过新查询）⇒ 页面必须丢弃 */
export interface SuggestAnswer {
  query: string
  outcome: SuggestOutcome
  stale: boolean
}

/**
 * 带**乱序守卫**的查询器（同一页面只建一个）。
 *
 * 只做一件事：给每次查询编号，回来时用「我是不是最后一次」判断该不该被采用。
 * 请求本身由调用方注入（`request`），所以本函数**零依赖、可单测**——上表 ② 的红证就靠它。
 */
export function createSuggestRunner(request: (query: string) => Promise<SuggestOutcome>) {
  let latest = 0
  return async function run(query: string): Promise<SuggestAnswer> {
    const seq = ++latest
    let outcome: SuggestOutcome
    try {
      outcome = await request(query)
    } catch (error: any) {
      // 网络异常也走同一个口径：页面永远拿得到「一句能行动的话」，不会是一片空白下拉
      outcome = { ok: false, message: String(error?.message || '').trim() || '搜索没成功，请重试' }
    }
    return { query, outcome, stale: seq !== latest }
  }
}
