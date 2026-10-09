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
/** 同上的**字面量**形态（源码里的写法，判「端点片段真的在文件里」时用）。 */
const SCAN_COMPLETE_ENDPOINT_LITERAL = "'/api/worker/production/scan/complete'"
/**
 * 无码自由报工的端点（issue #6598）：`.../orders/{orderId}/operations/{operationId}/report`。
 *
 * ⚠️ 源码用 `'…' + encodeURIComponent(…) + '…'` **拼接**而非模板串 —— 本仓有一族 TS 静态判据
 * 用 Python `tokenize` 剥注释，模板串里的 `${…}` 会被读成「未闭合括号」⇒ 整文件 tokenize 失败
 * （实测 `tests/unit_ci_workflows/test_operation_display_name_guard.py` 的 C8 两条判红）。
 * `workerPostEndpoints()` 把拼接结果还原成**完整端点**后再与下面的期望值比对；
 * `FREE_REPORT_ENDPOINT_SOURCE_PIECES` 是源码里的**字面量片段**（判「这份端点真写在这条函数里」）。
 */
const FREE_REPORT_ENDPOINT =
  '/api/worker/production/orders/:orderId/operations/:operationId/report'
/** 源码里的拼接片段（`${…}` 位置即 `encodeURIComponent(…)` 调用点）。 */
const FREE_REPORT_ENDPOINT_SOURCE_PIECES = [
  "'/api/worker/production/orders/' + encodeURIComponent(orderId)",
  "'/operations/' + encodeURIComponent(operationId) + '/report'",
]

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
 * 报工写面的**两条具名路**（唯一真值表；issue #6598）。
 *
 * <p>每条 = 端点值（`{x}` 只是写法，源码里是 `encodeURIComponent(x)`）+ 该端点在源码里的
 * **字面量片段**（判「这份端点真写在这条函数里」）+ 实现它的顶层导出函数。</p>
 */
const REPORT_WRITE_PATHS = [
  {
    fn: 'completeByScan',
    endpoint: '/api/worker/production/scan/complete',
    pieces: ["'/api/worker/production/scan/complete'"],
  },
  {
    fn: 'reportOperationFree',
    endpoint: '/api/worker/production/orders/{orderId}/operations/{operationId}/report',
    // ⚠️ 源码刻意用字符串拼接（不是模板串）：本仓有一族 TS 静态判据用 Python 词法器剥注释，
    //    模板串里的 `${…}` 会被读成「未闭合括号」⇒ 整文件解析失配（实测 C8 两条判红）。
    pieces: [
      "'/api/worker/production/orders/' + encodeURIComponent(orderId)",
      "'/operations/' + encodeURIComponent(operationId) + '/report'",
    ],
  },
] as const

/**
 * `productionService.ts` 里 `post<…>(…)` 的第一个实参处、`/api/worker/production/**` 开头的
 * **字面量片段**（不含注释）。
 *
 * <p>🔴 为什么判「片段」而不是「还原出完整端点」：本仓的端点既可能是整串字面量，也可能是
 * `'a' + encodeURIComponent(x) + 'b'` 拼接（见 `REPORT_WRITE_PATHS` 的注释）。写过三版「还原
 * 完整端点」的解析器（模板串截断 / 提前返回 / 正则片段二次转义），每一版都**静默读半截**过 ——
 * 与其养一个易错的迷你解析器，不如只取**引号内**的字面量片段 + 逐条断言片段齐全，
 * 并把「代码里有没有第三条写路」交给下面另外两条判据（`post(` 计数 + 函数体归属）。</p>
 */
function workerEndpointPieces(): string[] {
  const text = fs.readFileSync(PRODUCTION_SERVICE, 'utf8')
  const pieces: string[] = []
  // 剥掉注释，避免「注释里提到过端点」被当成接线（本仓被点过名的陷阱 T1）
  const code = text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
  const callRe = /\bpost\s*(?:<[^(]*)?\(/g
  const LITERAL = /'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"/g
  for (const call of code.matchAll(callRe)) {
    const slice = code.slice(call.index + call[0].length, call.index + call[0].length + 400)
    // 取「第一个实参」：从起点到第一个顶层逗号（字面量片段都在这一段里）
    const arg = slice.split('\n').slice(0, 6).join('\n')
    for (const literal of arg.match(LITERAL) || []) {
      const value = literal.slice(1, -1)
      if (value.startsWith('/api/worker/production/') || value.startsWith('/operations/')
        || value.startsWith('/report')) {
        pieces.push(`${literal}`)
      }
    }
  }
  return pieces
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

    // 无码端点由两段字面量拼接而成（见常量注释）⇒ 按**拼接片段**定位实现处
    const freeFiles = hits(/\/operations\/' \+ encodeURIComponent\(operationId\) \+ '\/report/)
      .map((loc) => loc.split(':')[0])
    expect(Array.from(new Set(freeFiles))).toEqual(['services/productionService.ts'])

    const bodies = exportedFunctionBodies()
    expect(bodies.completeByScan).toContain(SCAN_COMPLETE_ENDPOINT)
    for (const piece of FREE_REPORT_ENDPOINT_SOURCE_PIECES) {
      expect(bodies.reportOperationFree).toContain(piece)
    }
    // 🔴 交叉污染判据：每条路只打自己的端点（把两条路合成一个函数 ⇒ 这里红）
    expect(bodies.reportOperationFree).not.toContain(SCAN_COMPLETE_ENDPOINT)
    expect(bodies.completeByScan).not.toContain(FREE_REPORT_ENDPOINT_SOURCE_PIECES[0])
  })

  it('判据③：报工写面 = 真值表里的**两条具名路**，且每条只有一份实现（第三条 ⇒ 红）', () => {
    const bodies = exportedFunctionBodies()
    const text = fs.readFileSync(PRODUCTION_SERVICE, 'utf8')
    const pieces = workerEndpointPieces()

    // ① 真值表里每条路：端点片段都真的写在它自己的函数体里（**且只写在它自己那里**）
    for (const path of REPORT_WRITE_PATHS) {
      for (const piece of path.pieces) {
        expect(bodies[path.fn]).toContain(piece)
        // 交叉污染：这条路的端点片段不许出现在另一条路的函数体里
        for (const other of REPORT_WRITE_PATHS) {
          if (other.fn !== path.fn) expect(bodies[other.fn]).not.toContain(piece)
        }
      }
    }

    // ② 现取：源码里 `/api/worker/production/**` 的 POST 动作端点，只许是这两条
    const detected = pieces.filter((piece) => piece.includes('/api/worker/production/'))
    expect(detected).toEqual([SCAN_COMPLETE_ENDPOINT_LITERAL,
      "'/api/worker/production/orders/'"])
    // ③ 报工面 POST 调用的**条数**：恰好 2 条（出现第三条写路 ⇒ 红，无豁免台账）
    const postCalls = [...text.matchAll(/\bpost\s*(?:<[^(]*)?\(/g)]
      .filter((call) => {
        const window = text.slice(call.index, call.index + 600)
        return /\/api\/worker\/production\//.test(window)
      })
    expect(postCalls).toHaveLength(2)
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
