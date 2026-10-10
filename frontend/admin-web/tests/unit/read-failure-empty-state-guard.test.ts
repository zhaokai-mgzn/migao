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
      expect(source, `${surf.file} 缺常驻失败锚`).toContain(`data-testid="${surf.anchor}"`)
      expect(source, `${surf.file} 缺重试出口`).toContain(`data-testid="${retryAnchor}"`)
      expect(source, `${surf.file} 缺空态锚`).toContain(`data-testid="${surf.emptyTestId}"`)
      expect(source, `${surf.file} 缺失败读数 key`).toContain(surf.failureKey)
      // 失败面必须是 role=alert（读屏器会播报，不是视觉装饰）
      expect(source, `${surf.file} 的失败面缺 role="alert"`).toContain('role="alert"')
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
