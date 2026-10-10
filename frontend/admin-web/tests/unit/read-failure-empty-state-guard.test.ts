// case_ids: UI-011, CH-028, UI-046, UI-057, UI-058
/**
 * 类级元守卫：**读面失败不得与空态同屏**（issue #6713 + #6714，**一把尺子**）。
 *
 * ## 为什么是类级 / 为什么两单合并
 *
 * `/chat`（#6713）与 `/employees` `/notifications` `/products` `/shipments`（#6714）是**同一个形态**：
 * 注入读接口 500、等 6s（越过拦截器 toast 的 ≈4s 生存期）后，持久面上留着**事实性断言**
 * 「暂无会话 / 暂无数据 / 暂无通知」或「表头在、零行」。各立一把尺子会互相把对方判成僵尸条目、
 * 同一份文件被两份台账各记一次 ⇒ 按集成侧口径合并进
 * `frontend/admin-web/scripts/read-failure-empty-state-scan.mjs`（**判据单一源**）。
 *
 * ## 判据（各自能单独变红）
 *
 * ① **未登记即红**：`REQUIRED_SURFACES`（票据点名的 5 页 + chat）必须在
 *    `READ_SURFACES` / `PENDING_AUDIT` / `OUT_OF_SCOPE` **三张表之一**出现 ——
 *    未分类项（`/agent-workspace` `/briefing` `/categories`）**显式登记为待判**，不静默放行；
 * ② **接线不可摘**：每条登记读面必须逐字含「常驻失败锚 + 重试出口 + 空态锚 + 失败读数 key + `role="alert"`」
 *    —— 摘掉锚点 / 把守卫删了 ⇒ 当场红并**具名**报出缺哪条；
 * ③ **空态文案不许静默通过**：面内出现空态断言的每个文件要么带失败锚、要么在
 *    `EMPTY_STATE_LEDGER` 登记；台账**只许缩短**（超过冻结基线 ⇒ 红）、条目**不再命中 ⇒ 僵尸红**；
 * ④ **失败读数必须真落地**：store 承载的读面（`chat-sessions`）的 `failureKey` 必须在 store 里被
 *    **写成 true** —— 这正是 #6664 删掉的那个「全仓无消费点」假承诺的**反面保证**；
 * ⑤ **判别力自证**（本文件）：修前的逐字坏形态必红、修后形态不红、**真为空**的空态不红、
 *    注释里的同形态不误伤 —— 守卫自己退化成绿时先在这里红。
 *
 * ## 边界（照实登记，`migao-dev-flow` §19.1）
 *
 * - 只扫**源码文本 / AST**：判不了「失败面够不够显眼」（§15.7 读图面）、
 *   也判不了「按**路由**渲染出来的整页」（路由级核对由 #6714 的普查表承担）；
 * - 共享 `frontend/admin-web/src/components/ui/Table.tsx` 的**默认** `emptyText = 暂无数据` **判不了**
 *   （改默认值会波及全站调用方）⇒ `/employees` `/products` 的机械认定来自 `READ_SURFACES` 的**登记**，
 *   不是文本命中；本包改的是**页面级失败面**；
 * - **不跑真实浏览器**：真机读数由集成侧复跑（见 PR 报告）。
 */
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  SYNC_SCOPES,
  REQUIRED_SURFACES,
  READ_SURFACES,
  POSITIVE_ANCHORS,
  PENDING_AUDIT,
  OUT_OF_SCOPE,
  EMPTY_STATE_LEDGER,
  EMPTY_STATE_LEDGER_FLOOR,
  STORE_FILES,
  emptyStateOffenders,
  emptyStateSitesFromSource,
  hasFailureAnchor,
  missingWiring,
  renderGuardsFromSource,
  storeActionsFromSource,
  storeFailureKeyOffenders,
  unregisteredSurfaces,
  // ── 判据 ④（共享表格的 `emptyText` 必须接住失败读数，issue #6728）──
  TABLE_EMPTY_LEDGER,
  TABLE_EMPTY_LEDGER_FLOOR,
  directTableSitesFromSource,
  tableEmptyOffenders,
  tableEmptySitesFromSource,
  tableEmptyStale,
  specifierForModule,
  // ── 判据 ⑤（**运行期**：读失败后屏上不得出现任何「没有数据」断言，issue #6733）──
  RUNTIME_READ_FAILURE_SURFACES,
  RUNTIME_READ_FAILURE_LEDGER,
  RUNTIME_READ_FAILURE_LEDGER_FLOOR,
  RUNTIME_PENDING_AUDIT,
  findEmptyDataAssertions,
  runtimeGuardOffenders,
  runtimeGuardStale,
  unregisteredRuntimeSurfaces,
} from '../../scripts/read-failure-empty-state-scan.mjs'

const ADMIN_WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const read = (rel: string) => fs.readFileSync(path.join(ADMIN_WEB_ROOT, rel), 'utf8')

/**
 * 修前的**逐字**坏形态（`SessionList.tsx` 的三层三元；`git show origin/main:<path>` 可核）：
 * 失败后 `sessions` 仍是 `[]` ⇒ 落到「暂无会话」那一支 —— **失败与空态同屏**。
 */
const PRE_FIX_SNIPPET = `
  const { sessions, isLoadingSessions, searchKeyword } = useChatStore()
  return (
    <div className="flex-1 overflow-y-auto">
      {isLoadingSessions ? (
        <div className="flex items-center justify-center py-8">转圈</div>
      ) : filteredSessions.length === 0 ? (
        <div className="text-center py-8 text-neutral-400 text-xs">
          {searchKeyword ? '没有匹配的会话' : '暂无会话'}
        </div>
      ) : (
        <div className="py-1">{filteredSessions.map((s) => <SessionItem key={s.session_id} />)}</div>
      )}
    </div>
  )`

/** 修后形态（**不判红**的对照夹具；与工作树里的 `SessionList.tsx` 同构） */
const POST_FIX_SNIPPET = `
  const { sessions, isLoadingSessions, sessionsLoadFailed, fetchSessions } = useChatStore()
  return (
    <div className="flex-1 overflow-y-auto">
      {!isLoadingSessions && sessionsLoadFailed && (
        <div data-testid="chat-sessions-load-failed" role="alert">
          <span>会话列表读取失败 —— 请检查网络后重试</span>
          <button data-testid="chat-sessions-load-failed-retry" onClick={() => void fetchSessions()}>重试</button>
        </div>
      )}
      {isLoadingSessions ? (
        <div className="flex items-center justify-center py-8">转圈</div>
      ) : !sessionsLoadFailed && filteredSessions.length === 0 ? (
        <div data-testid="chat-sessions-empty" className="text-center py-8">暂无会话</div>
      ) : (
        <div className="py-1">{filteredSessions.map((s) => <SessionItem key={s.session_id} />)}</div>
      )}
    </div>
  )`

/** **反向对照**夹具：真为空（读成功、零条）⇒ 「暂无会话」照旧（不许把空态也判红） */
const EMPTY_ONLY_SNIPPET = `
  const { sessions, isLoadingSessions, sessionsLoadFailed } = useChatStore()
  return (
    <div className="flex-1 overflow-y-auto">
      {!isLoadingSessions && sessionsLoadFailed && (
        <div data-testid="chat-sessions-load-failed" role="alert">
          <button data-testid="chat-sessions-load-failed-retry">重试</button>
        </div>
      )}
      {isLoadingSessions ? null : !sessionsLoadFailed && sessions.length === 0 ? (
        <div data-testid="chat-sessions-empty">暂无会话</div>
      ) : null}
    </div>
  )`

/** 登记册条目的形状（`retryAnchor` 可选：既有页面的重试 testid 可能不叫 `<锚>-retry`） */
type SurfaceSpec = {
  issue: string
  file: string
  anchor: string
  retryAnchor?: string
  emptyTestId: string
  failureKey: string
  failureFrom?: { file: string }
}

const GUARD_OPTS = {
  failureKey: 'sessionsLoadFailed',
  anchorTestId: 'chat-sessions-load-failed',
  emptyTestId: 'chat-sessions-empty',
}

describe('类级守卫：读面失败不得与空态同屏（issue #6713 + #6714）', () => {
  it('① 未登记即红：票据点名的每个读面都必须在三张表之一（含「未分类」显式登记）', () => {
    // 面自证：票据点名的读面清单不许空（判据被自己扫成空集 = 假绿）
    expect(REQUIRED_SURFACES.length).toBeGreaterThanOrEqual(6)
    expect(unregisteredSurfaces()).toEqual([])

    // #6714 点名的「未分类」三页**必须**显式登记为待判（不许默认放行）
    const pendingAudit = PENDING_AUDIT as Record<string, { observed: string; evidence: string }>
    for (const key of ['agent-workspace', 'briefing', 'categories']) {
      expect(Object.keys(pendingAudit), `${key} 未登记为「未分类」`).toContain(key)
      expect(pendingAudit[key].evidence.length).toBeGreaterThan(20)
    }
    // 超范围项必须点名归属单（不是"放过"），且每条都给证据
    expect(OUT_OF_SCOPE['stock-ledger'].owner).toBe('#6707')
    expect(OUT_OF_SCOPE['dashboard-amounts'].owner).toBe('#6715')
    for (const [key, v] of Object.entries(OUT_OF_SCOPE)) {
      expect(v.evidence, `${key} 缺证据`).toBeTruthy()
    }
    // 登记册的每条都要有接线锚（不许只登记不接线）
    for (const key of Object.keys(READ_SURFACES)) {
      expect(POSITIVE_ANCHORS[key], `${key} 缺正向核`).toBeTruthy()
    }
  })

  it('② 接线不可摘：每条登记读面逐字含 失败锚 + 重试出口 + 空态锚 + 失败读数 key', () => {
    for (const [key, surf] of Object.entries(READ_SURFACES) as [string, SurfaceSpec][]) {
      const source = read(surf.file)
      const retryAnchor = surf.retryAnchor || `${surf.anchor}-retry`
      // ⚠️ 失败面走**共享件**（`ListLoadError`）的页面：源码里是 `testId="<锚>"` 这个 prop
      // （`data-testid` 由组件内部渲染）⇒ 按**该形态**逐字核；其余页面走 `data-testid` 字面量。
      // 🔴 判定用**源码里实际是哪种**（不是拿 `retryAnchor` 当开关：`remnant-ledger` 有自定义
      // 重试锚、但它自己渲染 `data-testid`，拿开关判会假红）。
      if (source.includes(`testId="${surf.anchor}"`)) {
        expect(source, `${surf.file} 缺共享失败件的重试 prop`).toContain(`onRetry=`)
      } else {
        expect(source, `${surf.file} 缺常驻失败锚`).toContain(`data-testid="${surf.anchor}"`)
        expect(source, `${surf.file} 缺重试出口`).toContain(`data-testid="${retryAnchor}"`)
      }
      expect(source, `${surf.file} 缺空态锚`).toContain(`data-testid="${surf.emptyTestId}"`)
      expect(source, `${surf.file} 缺失败读数 key`).toContain(surf.failureKey)
      // 失败面必须是 role=alert（读屏器会播报，不是视觉装饰）——共享件 `ListLoadError` 自带
      expect(
        source.includes('role="alert"') || source.includes('ListLoadError'),
        `${surf.file} 的失败面缺 role="alert"`,
      ).toBe(true)
      expect(key).toBeTruthy()
    }
    // 扫描器与守卫**同一份接线口径**（不写第二份清单）
    expect(missingWiring(ADMIN_WEB_ROOT).filter((w) => w.missing.length > 0)).toEqual([])
  })

  it('③ 空态文案不许静默通过：未登记即红、台账只许缩短、僵尸条目即红', () => {
    const { files, sites, unregistered, stale } = emptyStateOffenders(ADMIN_WEB_ROOT)

    // 面自证：扫描面非空、且候选非空（空集 = 判据在扫空气）
    expect(files.length).toBeGreaterThanOrEqual(50)
    expect(sites.length).toBeGreaterThan(0)
    // 两个单的病灶页必须在面里（否则改目录名就会「静默全绿」）
    expect(files).toContain('src/components/chat/SessionList.tsx')
    expect(files).toContain('src/app/(dashboard)/notifications/page.tsx')
    expect(files).toContain('src/app/(dashboard)/shipments/page.tsx')
    expect(files).toContain('src/app/(dashboard)/production/remnants/page.tsx')
    // 判红面必须为空
    expect(unregistered).toEqual([])
    // 台账只许缩短 + 无僵尸条目
    expect(EMPTY_STATE_LEDGER.length).toBeLessThanOrEqual(EMPTY_STATE_LEDGER_FLOOR)
    expect(stale).toEqual([])
  })

  it('④ 失败读数必须真落地（#6664 那个「全仓无消费点」假承诺的反面保证）', () => {
    // store 面自证：真的扫到了 `fetchSessions`
    const storeSource = read(STORE_FILES[0])
    expect(storeActionsFromSource(storeSource).map((a) => a.name)).toContain('fetchSessions')
    // 登记里声明了 `failureFrom` 的（= 失败读数**产生**在 store）必须被真的写成 true
    expect(storeFailureKeyOffenders(ADMIN_WEB_ROOT)).toEqual([])

    // 🔴 反向对照：把 `set({ sessionsLoadFailed: true })` 摘掉 ⇒ 当场判红
    //（**内存变异**喂给**同一份**生产判据 `storeFailureKeyOffenders`，不另抄一份正则、不碰真文件）
    const broken = [{ file: STORE_FILES[0], source: storeSource.replace('sessionsLoadFailed: true', '') }]
    const offenders = storeFailureKeyOffenders(ADMIN_WEB_ROOT, READ_SURFACES, broken)
    expect(offenders.length).toBe(1)
    expect(offenders[0].reason).toContain('sessionsLoadFailed')

    // 对照读数：不改坏 ⇒ 不报（否则这条自证是假红）
    expect(
      storeFailureKeyOffenders(ADMIN_WEB_ROOT, READ_SURFACES, [{ file: STORE_FILES[0], source: storeSource }]),
    ).toEqual([])
  })

  it('⑤ 判别力自证：修前坏形态必红、修后与「真为空」不红、注释不误伤', () => {
    // 🔴 修前形态：**没有任何失败锚** ⇒ 判据 3 当场红
    expect(hasFailureAnchor(PRE_FIX_SNIPPET)).toBe(false)
    // …而它的空态文案确实被判据识别到（是「失败与空态同屏」，不是「没有空态」）
    expect(
      emptyStateSitesFromSource(PRE_FIX_SNIPPET, { file: 'src/components/chat/SessionList.tsx' }).map((s) => s.text),
    ).toEqual(['没有匹配的会话', '暂无会话'])
    // …接线检查逐条判红（各自缺什么，具名）
    const preGuards = renderGuardsFromSource(PRE_FIX_SNIPPET, GUARD_OPTS)
    expect(preGuards.anchor).toBe(false)
    expect(preGuards.retry).toBe(false)
    expect(preGuards.emptyGuarded).toBe(false)
    expect(preGuards.ok).toBe(false)

    // ✅ 修后形态：五条全过（`ok` = 五条同时成立）
    expect(renderGuardsFromSource(POST_FIX_SNIPPET, GUARD_OPTS)).toEqual({
      anchor: true,
      retry: true,
      emptyGuarded: true,
      emptyAnchorClean: true,
      ok: true,
    })

    // ✅ 反向对照：真为空（读成功、零条）⇒ 空态文案仍被识别，但守卫不判红
    expect(emptyStateSitesFromSource(EMPTY_ONLY_SNIPPET, { file: 'probe.tsx' }).map((s) => s.text)).toContain('暂无会话')
    expect(renderGuardsFromSource(EMPTY_ONLY_SNIPPET, GUARD_OPTS)).toEqual({
      anchor: true,
      retry: true,
      emptyGuarded: true,
      emptyAnchorClean: true,
      ok: true,
    })

    // 注释里的同形态不误伤（AST 里没有注释节点 —— 本仓注释惯例会引用这些串）
    const commented = `// 改前这里印「暂无会话」，失败时不该出现\n/* 旧形态：暂无数据 */\nconst x = 1`
    expect(emptyStateSitesFromSource(commented, { file: 'probe.tsx' })).toEqual([])

    // 失败文案**不算**空态断言（判据治的是「把读不到说成没有」，不是「把读不到说出来」）
    expect(
      emptyStateSitesFromSource(`<div data-testid="x-load-failed">列表加载失败 —— 请检查网络后重试</div>`, { file: 'probe.tsx' }),
    ).toEqual([])

    // 行内字段占位不误伤（`暂无消息` 是单条会话的占位，不是列表体空态）
    expect(emptyStateSitesFromSource(`<p>{m.last_message || '暂无消息'}</p>`, { file: 'probe.tsx' })).toEqual([])

    // 扫描面自证（不各说各话）
    expect(SYNC_SCOPES).toEqual(['src/app/(dashboard)', 'src/components/chat'])
  })
})

/**
 * 判据 ④（issue #6728）：**渲染共享 `ui/Table` 且带读失败面的页面必须显式把失败读数接进 `emptyText`**。
 *
 * 为什么单独一条：它治的形态**不在任何页面的源码里** —— 假绿来源是共享
 * `frontend/admin-web/src/components/ui/Table.tsx` 的默认 `emptyText = '暂无数据'`
 * （前三条只能扫页面里的空态断言 ⇒ 对这种「页面源码零命中、屏上却印着暂无数据」**全绿**）。
 * 判据挂在同一支尺子上（`read-failure-empty-state-scan.mjs`），**不新立第三把**。
 */
describe('判据 ④：共享表格的 emptyText 必须接住失败读数（issue #6728）', () => {
  const FAIL_KEY = 'loadFailed'

  it('⑥ 台账只许缩短 + 未登记即红（面自证 + 真文件读数）', () => {
    const { sites, unregistered, stale } = tableEmptyOffenders(ADMIN_WEB_ROOT)

    // 面自证：登记读面的闭包**真的被扫到了**（空集 = 判据在扫空气）
    expect(sites.length).toBeGreaterThan(0)
    // 台账里那一条真值在面里（把它删了 ⇒ 僵尸条目判红）；本单修好的三层**不在**（见下一条）
    const keys = sites.map((s) => s.key)
    expect(keys).toContain('src/components/employees/WorkerProfilesPanel.tsx::WorkerProfilesPanel')
    // 判红面必须为空（未登记命中 / 僵尸条目都没有）
    expect(unregistered).toEqual([])
    expect(stale).toEqual([])
    // 台账只许缩短（超过冻结基线 ⇒ 红）
    expect(TABLE_EMPTY_LEDGER.length).toBeLessThanOrEqual(TABLE_EMPTY_LEDGER_FLOOR)
    // 判据面 = 登记读面（`READ_SURFACES`），**不另立一份清单**（否则两份会漂）
    // 门槛随本单 +1（`customers-list`）—— 数字是**现取的下界**，不是写死的业务常量
    expect(Object.keys(READ_SURFACES).length).toBeGreaterThanOrEqual(7)
    expect(Object.keys(READ_SURFACES)).toContain('customers-list')
  })

  it('⑦ 反向对照：本单修好的两处**不在**命中面里（不假红）', () => {
    const { sites } = tableEmptyOffenders(ADMIN_WEB_ROOT)
    const keys = sites.map((s) => s.key)
    // `/employees` 页面级传了 `emptyText={loadFailed ? '' : '暂无数据'}`
    expect(keys).not.toContain('src/app/(dashboard)/employees/page.tsx::EmployeesPage')
    // `/products` 页面把它透传给 `ProductTable`（页面是**调用方**，判决在组件那一环）
    expect(keys).not.toContain('src/app/(dashboard)/products/page.tsx::ProductsPage')
  })

  it('⑧ 判别力自证（真文件 + 内存变异）：摘掉 emptyText / 去掉失败读数 ⇒ **必红且具名**', () => {
    const page = 'src/app/(dashboard)/employees/page.tsx'
    const pageSrc = read(page)
    const opts = { file: page, failureKey: FAIL_KEY, root: ADMIN_WEB_ROOT }
    const pageKey = `${page}::EmployeesPage`

    // 对照读数：改后**本页不报**（同页那个「工人档案」面在台账里，另算 —— 见 ⑥）
    expect(tableEmptySitesFromSource(pageSrc, opts).map((s) => s.key)).not.toContain(pageKey)

    // 🔴 摘掉本页传给共享表的 `emptyText`（= 改前形态）⇒ 当场红，且报出**是本页哪一处**
    const noProp = pageSrc.replace("          emptyText={loadFailed ? '' : '暂无数据'}\n", '')
    expect(noProp).not.toBe(pageSrc) // 注入**自证生效**（没生效时下面那条会假红在别处）
    const a = tableEmptySitesFromSource(noProp, opts).filter((s) => s.key === pageKey)
    expect(a.map((s) => s.key)).toEqual([pageKey])
    expect(a[0].emptyText).toBeNull() // 「缺席 = 继承共享默认值」

    // 🔴 位子还在、但**失败读数没接进去**（恒真文案 = 失败时照样印「暂无数据」）⇒ 也红
    const staticText = pageSrc.replace(
      "emptyText={loadFailed ? '' : '暂无数据'}",
      "emptyText={'暂无数据'}",
    )
    expect(staticText).not.toBe(pageSrc)
    expect(tableEmptySitesFromSource(staticText, opts).map((s) => s.key)).toContain(pageKey)

    // 🔴 `emptyText` 换成**本文件自己的局部量**（不是形参透传）⇒ 照样红（不拿「透传」当免死金牌）
    const localVar = pageSrc.replace(
      "emptyText={loadFailed ? '' : '暂无数据'}",
      "emptyText={emptyTextLocal}",
    ).replace('  // 列表状态', "  const emptyTextLocal = '暂无数据'\n  // 列表状态")
    expect(localVar).toContain('emptyText={emptyTextLocal}')
    expect(tableEmptySitesFromSource(localVar, opts).map((s) => s.key)).toContain(pageKey)

    // ✅ 三种合法形态：`!k` / `k ? … : …` / `k && …`（与 `renderGuardsFromSource` 同口径）
    for (const expr of [
      "emptyText={!loadFailed ? '暂无数据' : ''}",
      "emptyText={loadFailed ? '' : '暂无数据'}",
      "emptyText={loadFailed && '读取失败'}",
    ]) {
      const mutated = noProp.replace('rowKey="id"', `rowKey="id"\n          ${expr}`)
      expect(mutated, `${expr} 没注入进去`).toContain(expr)
      expect(
        tableEmptySitesFromSource(mutated, opts).map((s) => s.key),
        `${expr} 被误判`,
      ).not.toContain(pageKey)
    }

    // 注释里「提及」不算渲染（AST 里没有注释节点 ⇒ 本仓注释惯例不会把判据喂红）
    expect(directTableSitesFromSource(`// emptyText={loadFailed ? '' : '暂无数据'}\nconst x = 1`)).toEqual([])

    // 🔴 同类第三例（`/customers`，由判据 ④ 的调用图普查发现）：摘掉它的 `emptyText` ⇒ 同样必红
    const custPage = 'src/app/(dashboard)/customers/page.tsx'
    const custSrc = read(custPage)
    const custOpts = { file: custPage, failureKey: 'loadError', root: ADMIN_WEB_ROOT }
    const custKey = `${custPage}::CustomersPage`
    expect(tableEmptySitesFromSource(custSrc, custOpts).map((s) => s.key)).not.toContain(custKey)
    const custNoProp = custSrc.replace("          emptyText={loadError ? '' : '暂无数据'}\n", '')
    expect(custNoProp).not.toBe(custSrc)
    expect(tableEmptySitesFromSource(custNoProp, custOpts).map((s) => s.key)).toContain(custKey)
  })

  it('⑨ 跨组件透传（内存假模块图）：组件把 emptyText 透传给共享表 **不假红**；摘掉组件的透传 ⇒ 必红', () => {
    const root = ADMIN_WEB_ROOT
    const tableAbs = path.join(root, 'src/components/products/ProductTable.tsx')
    const barrelAbs = path.join(root, 'src/components/ui/index.ts')
    const pageAbs = path.join(root, 'src/app/(dashboard)/probe/page.tsx')
    // 假模块说明符由**同一份**解析器给出（证明解析器与判据同源、不各写一份）
    const tableSpec = specifierForModule(tableAbs, root)
    const barreled = `${tableSpec.split('/').slice(0, -1).join('/')}` // `@/components/products`

    const pageSrc = `
      import ProductTable from '${barreled}/ProductTable'
      export default function ProbePage() {
        const [loadFailed] = useState(false)
        return <div>${'<' + 'ProductTable'} products={[]} emptyText={loadFailed ? '' : '暂无数据'} /></div>
      }`
    const tableSrc = `
      import { Table } from '@/components/ui'
      export default function ProductTable({ emptyText }: { emptyText?: string }) {
        return ${'<' + 'Table'} dataSource={[]} columns={[]} rowKey="id" emptyText={emptyText} />
      }`
    const inMemory = (p: string) => {
      if (p === tableAbs) return tableSrc
      if (p === barrelAbs) return `export { default as Table } from './Table'\n`
      throw new Error(`不该读别的模块：${p}`)
    }
    const opts = { file: pageAbs, failureKey: FAIL_KEY, root, readModule: inMemory }

    // ✅ 透传形态不假红（组件的形参值定义在父级 ⇒ 本文件解不动，但透传是合法承载）
    expect(tableEmptySitesFromSource(pageSrc, opts)).toEqual([])

    // 🔴 把组件的透传摘掉 ⇒ 必红（报出的是**组件**那一环，不是页面）
    const broken = tableSrc.replace(' emptyText={emptyText}', '')
    expect(broken).not.toBe(tableSrc)
    const brokenSites = tableEmptySitesFromSource(pageSrc, {
      ...opts,
      readModule: (p: string) => (p === tableAbs ? broken : inMemory(p)),
    })
    expect(brokenSites.map((s) => s.key)).toEqual(['src/components/products/ProductTable.tsx::ProductTable'])

    // 🔴 台账空转（只许缩短）在**内存台账**上同样会红（判别力自证）
    expect(tableEmptyStale(ADMIN_WEB_ROOT, ['src/components/products/ProductTable.tsx::不存在的组件'])).toEqual([
      'src/components/products/ProductTable.tsx::不存在的组件',
    ])
  })
})

/**
 * 判据 ⑤（issue #6733）：**运行期**「读失败后屏上不得出现任何『没有数据』断言」。
 *
 * 为什么必须有它 —— 判据 ④ 是**调用图**普查（只看渲染共享 `ui/Table` 的页面），而 `/orders` 用的是
 * **自定义表**（`OrderTable` 手写 `<tbody>` 空态行）⇒ **调用图看不见**。这不是判据写错，是
 * **手段的射程盲区**：静态手段能看见「谁渲染了共享组件」，看不见「谁自己手写了空态行」；
 * 只有**渲染后读屏**（注入失败 → 渲染 → 断言屏上文本）才覆盖得了。
 *
 * 本节判的是**覆盖面与口径**（是否有那条运行期判据、是否用同一份文案口径）；
 * **真的跑一次渲染断言**在 `tests/unit/pages/read-failure-no-empty-assertion-runtime.test.tsx`。
 */
describe('判据 ⑤：运行期「读失败后屏上不得有『没有数据』断言」（issue #6733）', () => {
  it('⑩ 覆盖面未登记即红 + 台账只许缩短 + 运行期用例真的落地（真文件读数）', () => {
    // 面自证：登记表非空、且票据点名的那个在里面（空集 = 判据在扫空气）
    expect(Object.keys(RUNTIME_READ_FAILURE_SURFACES).length).toBeGreaterThan(0)
    expect(Object.keys(RUNTIME_READ_FAILURE_SURFACES)).toContain('orders')
    // 未登记即红
    expect(unregisteredRuntimeSurfaces()).toEqual([])
    // 登记的运行期用例必须真的落地：文件在 + 用**单一源口径** + 驱动该页的**读失败**
    expect(runtimeGuardOffenders(ADMIN_WEB_ROOT)).toEqual([])
    // 台账只许缩短 + 无僵尸条目
    expect(RUNTIME_READ_FAILURE_LEDGER.length).toBeLessThanOrEqual(RUNTIME_READ_FAILURE_LEDGER_FLOOR)
    expect(runtimeGuardStale(ADMIN_WEB_ROOT)).toEqual([])
    // 已普查到、本单不动的形态要**显式登记为待判**（不许静默放行）
    expect(Object.keys(RUNTIME_PENDING_AUDIT).length).toBeGreaterThan(0)

    // 该用例文件**真的**做了运行期断言（不是只登记了一个空壳）
    const runtimeTest = read(RUNTIME_READ_FAILURE_SURFACES.orders.testFile)
    expect(runtimeTest).toContain('findEmptyDataAssertions')
    expect(runtimeTest).toContain('orders-load-error')
    expect(runtimeTest).toContain('render(')
    // 且它驱动的是**页面**（不是只渲染组件就收工）
    expect(runtimeTest).toContain('@/app/(dashboard)/orders/page')
  })

  it('⑪ 判别力自证（内存变异）：用例壳 / 缺口径 / 缺失败驱动 / 台账僵尸 / 假绿窗口 —— 各自判红', () => {
    const surf = RUNTIME_READ_FAILURE_SURFACES.orders
    const good = `import { findEmptyDataAssertions } from '...'\nrender(<OrdersPage />)\nexpect(findEmptyDataAssertions(document.body.textContent)).toEqual([])\n// ${surf.failureTestId}`
    const readWith = (text: string | null) => () => {
      if (text === null) throw new Error('ENOENT')
      return text
    }

    // 对照读数：好用例 ⇒ 不报（否则下面的「红」分不清是注入还是判据自己坏）
    expect(runtimeGuardOffenders(ADMIN_WEB_ROOT, RUNTIME_READ_FAILURE_SURFACES, [], readWith(good))).toEqual([])

    // ① 用例文件不存在 ⇒ 红
    const missing = runtimeGuardOffenders(ADMIN_WEB_ROOT, RUNTIME_READ_FAILURE_SURFACES, [], readWith(null))
    expect(missing).toHaveLength(1)
    expect(missing[0].reason).toContain('不存在')
    // ② 用例没用单一源口径（自己抄一份正则 ⇒ 会漂的第二份真值）⇒ 红
    const noMarker = good.split('findEmptyDataAssertions').join('自己抄的断言')
    const markerOff = runtimeGuardOffenders(ADMIN_WEB_ROOT, RUNTIME_READ_FAILURE_SURFACES, [], readWith(noMarker))
    expect(markerOff.map((o) => o.reason).join('|')).toContain('单一源口径')
    // ③ 用例没有驱动该页的读失败（渲染了但没注入失败 ⇒ 断言恒真）⇒ 红
    const noFailure = good.split(surf.failureTestId).join('没注入失败')
    const failOff = runtimeGuardOffenders(ADMIN_WEB_ROOT, RUNTIME_READ_FAILURE_SURFACES, [], readWith(noFailure))
    expect(failOff.map((o) => o.reason).join('|')).toContain('读失败')
    // ④ 台账僵尸（登记了但不在登记表里）⇒ 红；台账只许缩短
    expect(runtimeGuardStale(ADMIN_WEB_ROOT, RUNTIME_READ_FAILURE_SURFACES, ['不存在的页面'])).toEqual(['不存在的页面'])
    // ⑤ 覆盖面未登记（票据点名了、三张表都没有）⇒ 红
    expect(
      unregisteredRuntimeSurfaces({} as Record<string, never>, [], {} as Record<string, never>),
    ).toEqual([{ key: 'orders', issue: '#6733', required: true }])

    // ⑥ 🔴 **口径自证（本单实测踩到的假绿）**：`document.body.textContent` 把同屏不同元素连成一串，
    //    失败横幅那句「…不可信。请检查网络后重试。」与表体空态行**只隔几十个字符** ——
    //    若按「窗口内含失败文案就不算」排除，**真缺陷会被当场漏掉**（判据恒绿）。
    const preFixDom = '订单加载失败 —— 没读到数据，下面的条数与列表都不可信。请检查网络后重试。重试'
      + '采购商品采购明细累计金额(元)实收款(元)收货人信息下单时间制单人到货日备注操作暂无数据共 — 条‹1›'
    const hits = findEmptyDataAssertions(preFixDom)
    expect(hits.length).toBeGreaterThan(0)
    expect(hits[0].text).toContain('暂无数据')
    // 反向：失败文案本身**不算**空态断言（正则层就不命中，不靠窗口）
    expect(findEmptyDataAssertions('订单加载失败 —— 没读到数据，下面的条数与列表都不可信。')).toEqual([])
    expect(findEmptyDataAssertions('商品加载失败 —— 不是没有商品，是没读到。请检查网络后重试')).toEqual([])
    // 行内字段占位不算（`暂无消息` 一族）；真空态断言必命中，且**不绑死「暂无数据」四个字**
    expect(findEmptyDataAssertions('暂无消息')).toEqual([])
    expect(findEmptyDataAssertions('暂无数据').length).toBe(1)
    expect(findEmptyDataAssertions('暂无订单').length).toBe(1)
    expect(findEmptyDataAssertions('还没有订单记录').length).toBe(1)
    // 修后形态：空串空态 + 失败横幅同屏 ⇒ 不命中（这正是页面级修法要达到的读数）
    expect(findEmptyDataAssertions('订单加载失败 —— 没读到数据，下面的条数与列表都不可信。重试共 — 条‹1›')).toEqual([])
  })
})
