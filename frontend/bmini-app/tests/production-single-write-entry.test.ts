// case_ids: BM-006
/**
 * 类级元守卫：bmini 的**工人报工写面只许这两个具名入口**（issue #5647 G10 的固化面）。
 *
 * ## 为什么需要一条「类级」判据
 * 这处缺陷能长期存在，是因为「多长出一条写路径」**没有任何东西会红**：页面同时调
 * URL 定工序的 `.../operations/{id}/report` 与 `scan/complete`，两条路各自都跑得通，
 * 防呆④（非本部位码）/ 防呆⑤（工序必须确定）/ 一次事务 / `done_at` 只在后者生效
 * ⇒ 同一租户两条报工路径迟早给出不同结果，且**只能靠人记得**别走错那条。
 * 本条把「写入口是**具名的两条**」变成可执行判据：**第三条 ⇒ 红**
 * （无豁免台账 ⇒ 不存在「登记一下就放行」）。
 *
 * ## 🔴 2026-10-09 用户裁定改口径（issue #6598）
 * 用户逐字：「当前工人报工只能按固定顺序报工，这个设计是不对的，**允许工人自由报工**」；
 * 开放范围当场选定 = **整张加工单内任选任意工序（不扫码也能自由报）**。
 * ⇒ 本文件**改判**（不是放宽）：写面从「一条路（有码才能报）」变成
 * **两条具名路**，判别键 = 本部位有没有 `part_token`：
 *
 * | # | 路径 | 端点 | 工序怎么定 |
 * |---|---|---|---|
 * | 1 | 有码（扫码 = **快捷定位**） | `POST /api/worker/production/scan/complete` | 码定位部位 + 系统推断，或一键改 |
 * | 2 | 无码（**自由报工**） | `POST /api/worker/production/orders/{orderId}/operations/{operationId}/report` | 工人在本单清单里**显式选** |
 *
 * ⚠️ **改判的理由（留痕，不粉饰）**：判据 ①② 当年把路径 2 整条禁掉的依据是
 * 「它没有码、不校验部位归属、非事务、也不落 `done_at`」。🔴 **该依据与今日代码不符** ——
 * 路径 2 的服务端实现（`ProductionService#report` → `#applyReport`）与路径 1 走的是
 * **同一份记账实现**：CAS 推进 / `done_at` / 完工判定一处不差，归属校验走
 * `ProductionService#requireActiveOperation`（同租户 + 未软删 + 属于本加工单）。
 * ⇒ 路径 2 不再是「绕开防呆的后门」，而是**无码部位的唯一合法入口**。
 *
 * ## 🔴 一条都没放宽的部分（本文件继续钉死）
 * ① **工序必须显式确定**（issue #4694 硬约束）：两条路的工序标识都来自**路径 / 请求体里由工人
 *    确认过的显式值**，客户端与服务端**都不许**猜「下一道」（服务端缺 `operationId` 直接 422）；
 * ② **身份绝不进请求体**（issue #4733）：两条路的报工 body 里都不许出现 `worker_id` / `worker_name`
 *    —— 计件归属只能由服务端从 `X-Worker-Session-Id` 解；
 * ③ **写面只有这两条路**：出现第三条 `/api/worker/production/**` 的 POST 动作端点 ⇒ 红。
 *
 * ## 判据（全部取 `frontend/bmini-app/src/**` 的源码文本，不依赖运行时）
 * ① `reportOperation` 符号一处都不许有（URL 定工序那条**旧**客户端封装，issue #5647 已退场）；
 * ② 每条具名路径各**只有一份**实现：
 *    `scan/complete` 落在 `services/productionService.ts` 的 `completeByScan`（单一文件单一函数）；
 *    `.../operations/{id}/report` 落在 `services/productionService.ts` 的 `reportOperationFree`。；
 * ③ 生产服务里**报工面**（`/api/worker/production/**`）的 POST 端点集合 = 那两条（**多一条 ⇒ 红**）；
 * ④ **不看码也能报**的判据面：`reportOperationFree` 的请求体构造里不许出现 `token`
 *    （它是无码路径；出现 token = 又把写入口绑回码上）；
 * ⑤ 两条路的报工 body 都不许带身份键（`worker_id` / `worker_name`）。
 *
 * ⚠️ 判据③ 的射程**只到报工面**（issue #6472 收窄）：发货走的是另一条具名动作端点
 * `/api/worker/shipment/orders/{orderId}/ship`（issue #5648 既有端点，不是第三条**报工**写路径）——
 * 把发货也算进「报工写面」是把「同类」误判成「同一个动作」，而判据的立意是
 * 「同一次报工只许走这两条具名路之一」。发货自身的类级固化见
 * `frontend/bmini-app/tests/worker-action-endpoint-ledger.test.ts`。
 *
 * ## 红证（2026-10-09 实测）
 * - 给 `src/services/productionService.ts` 加回 `reportOperation` 符号 ⇒ 判据①红；
 * - 在 `reportOperationFree` 之后再写一条 `/api/worker/production/**` 的 POST ⇒ 判据③红
 *   （集合从 2 个变 3 个）；
 * - 把 `worker_id` 塞回报工 body ⇒ 判据⑤红；
 * - 撤回后再跑 ⇒ 全绿。
 */
import fs from 'fs'
import path from 'path'

const SRC_ROOT = path.join(__dirname, '..', 'src')
const PRODUCTION_SERVICE = path.join(SRC_ROOT, 'services', 'productionService.ts')
const SCAN_COMPLETE_ENDPOINT = '/api/worker/production/scan/complete'
/**
 * 无码自由报工的端点**记号**（issue #6598）：
 * `.../orders/{orderId}/operations/{operationId}/report` 的末段（插值写法照抄源码，
 * 保证判据咬住的是**同一个**具名端点而不是一个近似串）。
 */
const FREE_REPORT_ENDPOINT_MARKER =
  '/operations/${encodeURIComponent(operationId)}/report'

/** 递归收集 `src/**` 下的源码文件（样式 / 资源不参与文本取判据）。 */
function sourceFiles(dir: string): string[] {
  const collected: string[] = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      collected.push(...sourceFiles(full))
    } else if (/\.(ts|tsx|mjs|js)$/.test(entry.name)) {
      collected.push(full)
    }
  }
  return collected
}

const FILES = sourceFiles(SRC_ROOT)

/** 命中该正则的位置清单（`相对路径:行号` —— 判红时可归因到具体一行）。 */
function hits(pattern: RegExp): string[] {
  const found: string[] = []
  for (const file of FILES) {
    fs.readFileSync(file, 'utf8')
      .split('\n')
      .forEach((line, index) => {
        if (pattern.test(line)) found.push(`${path.relative(SRC_ROOT, file)}:${index + 1}`)
      })
  }
  return found
}

/**
 * `productionService.ts` 里 `post<…>(…)` 的**报工面**端点字面量。
 *
 * 🔴 射程 = `/api/worker/production/**`（报工动作面；issue #6472 收窄）—— 发货走的是
 * `/api/worker/shipment/**`（另一条具名动作端点），不属于「报工写面」这条判据。
 *
 * <p>issue #6598：写面从 1 条变为**2 条具名路**（有码 `scan/complete` + 无码
 * `.../operations/{id}/report`）⇒ 断言从「集合 == 1 条」改为「集合 == 这 2 条」，
 * **多一条仍红**（判据强度只升不降）。</p>
 *
 * <p>⚠️ <b>不能用「引号 + 非引号字符」的朴素正则在源码上直取端点</b>：无码那条端点含
 * <code>${encodeURIComponent(orderId)}</code>，朴素字符类会在 <code>${</code> 处停下、把端点读成
 * <b>被截断的前缀</b>（实测：读成 1 条 ⇒ 判据静默漏掉第二条路 —— 那正是本守卫存在的意义）。
 * 故这里按<b>实参位置</b>解析：从 `post(` 起、跳过 `<…>` 泛型与空白，再手工扫描第一个实参的
 * 字符串字面量（模板串里的 <code>${…}</code> 原样保留、不作为边界），并对 `'a' + 'b'` 形态做拼接。</p>
 */
function workerPostEndpoints(): string[] {
  const text = fs.readFileSync(PRODUCTION_SERVICE, 'utf8')
  const endpoints: string[] = []
  // 泛型实参可能**嵌套**（`post<ProductionResponse<X>>(`）⇒ 用非 `(` 字符类吃到第一个 `(`；
  // 写 `[^>(]*>` 会在内层 `>` 处停下、一条都匹配不到（实测：集合变空 ⇒ 判据恒绿/恒红都不可信）。
  const callRe = /\bpost\s*(?:<[^(]*)?\(\s*/g
  for (const call of text.matchAll(callRe)) {
    const endpoint = firstStringArgument(text, call.index + call[0].length)
    if (endpoint && endpoint.startsWith('/api/worker/production/')) endpoints.push(endpoint)
  }
  return endpoints
}

/** 从 `from` 处扫描 `post(…)` 的**第一个实参**；返回其字面量值（`'a' + 'b'` 形态会拼接）。 */
function firstStringArgument(text: string, from: number): string | null {
  let i = from
  const skipSpace = () => {
    while (i < text.length && /\s/.test(text[i])) i += 1
  }
  skipSpace()
  if (i >= text.length || !'\'"`'.includes(text[i])) return null
  const quote = text[i]
  i += 1
  let value = ''
  while (i < text.length) {
    const char = text[i]
    if (char === '\\') {
      value += text[i + 1] ?? ''
      i += 2
      continue
    }
    // 🔴 模板串的 `${…}` 原样收进值里（它是端点的一部分，不是字符串边界）
    if (quote === '`' && char === '$' && text[i + 1] === '{') {
      let depth = 1
      let j = i + 2
      while (j < text.length && depth > 0) {
        if (text[j] === '{') depth += 1
        else if (text[j] === '}') depth -= 1
        j += 1
      }
      value += text.slice(i, j)
      i = j
      continue
    }
    if (char === quote) {
      i += 1
      break
    }
    value += char
    i += 1
  }
  // `'a' + '/b'` 形态：继续吃后面的字面量（端点被拆成多段拼接时仍要读全）
  for (;;) {
    let j = i
    while (j < text.length && /\s/.test(text[j])) j += 1
    if (text[j] !== '+') break
    j += 1
    while (j < text.length && /\s/.test(text[j])) j += 1
    if (j >= text.length || !'\'"`'.includes(text[j])) break
    const nextQuote = text[j]
    j += 1
    let more = ''
    while (j < text.length && text[j] !== nextQuote) {
      if (text[j] === '\\') {
        more += text[j + 1] ?? ''
        j += 2
        continue
      }
      more += text[j]
      j += 1
    }
    value += more
    i = j + 1
  }
  return value
}

/** 顶层导出函数的源码块（名字 → 函数体文本）；用于「这个函数打的是哪个端点」这类判据。 */
function exportedFunctionBodies(): Record<string, string> {
  const text = fs.readFileSync(PRODUCTION_SERVICE, 'utf8')
  const bodies: Record<string, string> = {}
  const re = /^export (?:async )?function ([A-Za-z0-9_]+)\s*[(<]/gm
  const marks: { name: string; start: number }[] = []
  let match: RegExpExecArray | null
  while ((match = re.exec(text))) marks.push({ name: match[1], start: match.index })
  marks.forEach((mark, index) => {
    const end = index + 1 < marks.length ? marks[index + 1].start : text.length
    bodies[mark.name] = text.slice(mark.start, end)
  })
  return bodies
}

describe('bmini 报工写面 = 两条具名路（issue #5647 G10 → #6598 改口径的类级守卫）', () => {
  it('判据①：URL 定工序的**旧客户端封装**（reportOperation）一处都不许有', () => {
    // ⚠️ 注意：`reportOperationFree` 是 #6598 的**新**封装（合法），
    // 被禁的是无后缀的旧名 `reportOperation` ⇒ 正则用词边界 + 显式排除 Free 后缀。
    expect(hits(/\breportOperation(?!Free)\b/)).toEqual([])
  })

  it('判据②：两条路各**只有一份**实现，且都落在 productionService.ts 的两个具名函数里', () => {
    const scanFiles = hits(/\/api\/worker\/production\/scan\/complete/).map((loc) => loc.split(':')[0])
    expect(Array.from(new Set(scanFiles))).toEqual(['services/productionService.ts'])

    const freeFiles = hits(/operations\/\$\{[^}]*\}\/report/)
      .map((loc) => loc.split(':')[0])
    expect(Array.from(new Set(freeFiles))).toEqual(['services/productionService.ts'])

    const bodies = exportedFunctionBodies()
    expect(bodies.completeByScan).toContain(SCAN_COMPLETE_ENDPOINT)
    expect(bodies.reportOperationFree).toContain(FREE_REPORT_ENDPOINT_MARKER)
    // 🔴 交叉污染判据：每条路只打自己的端点（把两条路合成一个函数 ⇒ 这里红）
    expect(bodies.reportOperationFree).not.toContain(SCAN_COMPLETE_ENDPOINT)
    expect(bodies.completeByScan).not.toContain(FREE_REPORT_ENDPOINT_MARKER)
  })

  it('判据③：报工面（/api/worker/production/**）的 POST 端点集合 = {scan/complete, operations/{id}/report}', () => {
    const endpoints = workerPostEndpoints()
    expect(endpoints).toHaveLength(2)
    expect(endpoints).toContain(SCAN_COMPLETE_ENDPOINT)
    expect(endpoints.some((endpoint) => endpoint.endsWith(FREE_REPORT_ENDPOINT_MARKER))).toBe(true)
    // 出现**第三条**报工 POST 端点 ⇒ 红（无豁免台账）
    expect(new Set(endpoints).size).toBe(2)
  })

  it('判据④：无码路径真的**不看码**（reportOperationFree 的 body 里不许出现 token）', () => {
    const body = exportedFunctionBodies().reportOperationFree
    expect(body).not.toContain('token')
    // 有码路径反之：它必须带 token（否则扫码定位失效）
    expect(exportedFunctionBodies().completeByScan).toContain('token')
  })

  it('判据⑤：两条路的报工请求体都不带身份键（issue #4733 不放宽）', () => {
    // 身份只许走 `workerSessionHeaders()`（服务端从 X-Worker-Session-Id 解）——
    // 报工 body 里出现 worker_id / worker_name = 把计件归属交回客户端（发错工资的根因）。
    // 🔴 射程 = **这两条报工路的函数体**（不是全文件）：`ReportResult` **响应**类型里
    // 合法地声明了这两个键（服务端回执带「这笔记到谁头上」）—— 那是读，不是写。
    const bodies = exportedFunctionBodies()
    for (const fn of ['completeByScan', 'reportOperationFree']) {
      expect(bodies[fn]).toBeTruthy()
      expect(bodies[fn]).not.toMatch(/worker_id\s*:/)
      expect(bodies[fn]).not.toMatch(/worker_name\s*:/)
    }
    // 反向对照（防「射程取空 ⇒ 恒绿」）：两条路的 body 里**确实**有会写进请求体的东西
    expect(bodies.completeByScan).toMatch(/body\./)
    expect(bodies.reportOperationFree).toMatch(/body\./)
  })
})
