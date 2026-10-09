// case_ids: BM-037
/**
 * 工人面**写入口台账**元守卫（issue #6467 切片 1，S8；AGENTS.md 铁律 8 / `migao-dev-flow` §23 G1~G3）
 *
 * ## 治的形态：「同一个缺陷在这台设备上出现一次，就能在下一个页面上再出现一次」
 *
 * 现场（2026-10-07 生产）：报工页在**没有工人身份**时照样渲染「完成报工」⇒ 点下去
 * `POST /api/worker/production/scan/complete` 401 → 请求层把它读成「商家会话过期」⇒
 * 清商家 token、踢回登录页（重登再点仍然如此）。修一处**不等于**这一类进不来：
 * 入库页早就有 `workerReady` 分流（`.github/cases/bmini.yml` 判据 1），报工页却漏了 ——
 * 两者都不会因为「另一处有没有分流」而变红。
 *
 * 本台账把「哪个页面渲染工人写入口 / 哪个页面必须先有工人身份」变成**可执行判据**：
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | 1 | **未登记即红**：`src/pages/**` 里出现工人写调用（`completeByScan(` / `workerLogin(` / `workerLogout(` / `createInboundDraft(` / `postInboundDraft(`）而台账没有这个 **(页面, 调用)** 配对 | 新页面调一次 `workerLogout()` ⇒ 红并具名 |
 * | 2 | **台账只许缩短**：每条登记都必须仍能被扫到（页面已不再有该调用 ⇒ 该条已死 ⇒ 红） | 摘掉某页的写调用而不删登记 ⇒ 红 |
 * | 3 | **声称「必须先有工人身份」的写入口必须真的有身份分流**：页面里找不到 `gate_token` ⇒ 红 | 把分流摘掉（内存变异）⇒ 红 |
 * | 4 | **引导可行动**：分流页面必须渲染引导文案 + 指向登录页的工人入口（`guide_token` / `login_route_token`） | 删掉引导 / 改指向 ⇒ 红 |
 * | 5 | **台账不许空转**（fail-closed）：条数为 0 ⇒ 红；每条必须声明 `case_ids` | 清空台账「消红」⇒ 红 |
 *
 * ## 边界（照实登记，§19.1）
 * ① 它判的是**静态形态**（记号在不在、配对全不全），**不是**运行期真的走到了分流 ——
 *    行为面由 `production-worker-entry.test.tsx` / `worker-home-page.test.tsx` 等实例判据承担；
 * ② 射程 = `src/pages` 下的全部 `.tsx`：**组件**（如 `src/components/WorkerBar.tsx`）不在本台账内 ——
 *    WorkerBar 当前只被 import 未渲染（issue #6467 的现场证据之一），一旦真的渲染，
 *    它调用的 `switchWorker` 应连同渲染它的页面一起重新登记（本守卫**不会**替你记得这一点）；
 * ③ 它**不改任何门禁的通过条件、不新增豁免**。
 */
import fs from 'fs'
import path from 'path'
import { stripComments } from './helpers/h5PlatformLists'

const BMINI_ROOT = path.join(__dirname, '..')
const PAGES_ROOT = path.join(BMINI_ROOT, 'src', 'pages')

/**
 * 「工人写调用」记号（发现即必须登记）。
 * 🔴 这里是**唯一**的记号真值 —— 观测到新的工人写调用形态时，加在**这里**并同批补台账条目，
 * 不要在别处再列一份清单（`migao-dev-flow` §17.3「同一真值两处推导」）。
 */
export const WORKER_WRITE_CALLS: string[] = [
  'completeByScan(',
  // issue #6598：无码自由报工 —— 报工页的**第二条**具名写路（有码走 scan/complete，
  // 无码走它；用户 2026-10-09 裁定「允许工人自由报工」）。它的端点打在 `/api/worker/**`
  // （工人到得了），所以 `worker-action-endpoint-ledger` 的「打商家端点」面不覆盖它；
  // 它属于**本**台账的射程：它是工人写入口，且必须先有工人身份。
  'reportOperationFree(',
  'workerLogin(',
  'workerLogout(',
  'createInboundDraft(',
  'postInboundDraft(',
]

export interface LedgerEntry {
  page: string
  call: string
  label: string
  requires_worker_session: boolean
  /**
   * 该页「必须先有工人身份」的**两个记号**（都要命中）：
   * ① 身份分流的**声明**（如 `const workerReady = hasWorkerSession()`）；
   * ② **用到它的渲染条件**（写入口真的被它挡着）。
   * 只写声明、不接到渲染条件 ⇒ 红（「声明了却没用」正是本台账要拦的形态之一）。
   */
  gate_tokens?: string[]
  guide_token?: string
  login_route_token?: string
  case_ids: string[]
}

export interface LedgerInput {
  /** 受管页面（bmini 相对 posix 路径，即 `src/pages` 下全部 `.tsx`） */
  pages: string[]
  read: (rel: string) => string
  entries: LedgerEntry[]
}

function pairKey(page: string, call: string): string {
  return `${page}::${call}`
}

/** 核心判定（真判据与注入式红证**共用同一份** —— 红证必须走真判据，见 `migao-dev-flow` §23.5） */
export function ledgerProblems(input: LedgerInput): string[] {
  const problems: string[] = []
  const declared = new Set(input.entries.map((entry) => pairKey(entry.page, entry.call)))

  // 🔴 一律**先去注释**再判：「注释里提到过这个调用」不是接线（本仓被点过名的形态：
  //    判据把原文当代码读 ⇒ 注释/报错文案自己把判据喂绿，见 `migao-dev-flow` §23.4 陷阱 T1）。
  const bodyOf = (rel: string): string => stripComments(input.read(rel))

  // 现取：受管页面里真实出现的 (页面, 工人写调用) 配对
  const detected = new Set<string>()
  for (const page of input.pages) {
    const text = bodyOf(page)
    for (const call of WORKER_WRITE_CALLS) {
      if (text.includes(call)) detected.add(pairKey(page, call))
    }
  }

  // 判据 5：台账不许空转（fail-closed）—— 空台账不是「全部合规」
  if (input.entries.length === 0) {
    problems.push('台账为空：工人面写入口台账被清空 ⇒ fail-closed 判红（「空」不等于「全部合规」）')
  }

  // 判据 1：未登记即红
  for (const key of detected) {
    if (!declared.has(key)) {
      problems.push(
        `未登记即红：${key} —— 页面里出现了工人写调用，而 tests/worker-surface-ledger.json 没有这一条` +
          `（新写入口必须同批登记「谁需要工人身份 / 引导去哪」）`,
      )
    }
  }
  // 判据 2：台账只许缩短（条目必须活着）
  for (const key of declared) {
    if (!detected.has(key)) {
      problems.push(
        `台账条目已死：${key} —— 该页面已不再有这个工人写调用 ⇒ 同批删掉这一条（台账只许缩短）`,
      )
    }
  }

  for (const entry of input.entries) {
    const key = pairKey(entry.page, entry.call)
    // 判据 5：每条登记都要有用例面关联
    if (!Array.isArray(entry.case_ids) || entry.case_ids.length === 0) {
      problems.push(`${key}：没有声明 case_ids（登记而不关联用例 ⇒ 没人知道它靠哪条判据活着）`)
    }
    if (!entry.requires_worker_session) continue
    const text = bodyOf(entry.page)
    // 判据 3：声称必须先有工人身份 ⇒ 页面里必须真的有身份分流（声明 **以及** 用到它的渲染条件）
    const gateTokens = Array.isArray(entry.gate_tokens) ? entry.gate_tokens : []
    if (gateTokens.length === 0) {
      problems.push(`${key}：requires_worker_session=true 却没有 gate_tokens（身份分流的记号）`)
    }
    for (const token of gateTokens) {
      if (!text.includes(token)) {
        problems.push(
          `${key}：写入口「${entry.label}」声称必须先有工人身份，但 ${entry.page} 里找不到身份分流记号「${token}」` +
            `—— 摘掉分流 = 无工人身份的商家设备也能看到写入口`,
        )
      }
    }
    // 判据 4：引导必须可行动（文案 + 去登录）
    if (!entry.guide_token || !text.includes(entry.guide_token)) {
      problems.push(`${key}：没有渲染可行动的引导文案（guide_token=${entry.guide_token ?? '（缺）'}）`)
    }
    if (!entry.login_route_token || !text.includes(entry.login_route_token)) {
      problems.push(
        `${key}：没有指向登录页工人入口（login_route_token=${entry.login_route_token ?? '（缺）'}）`,
      )
    }
  }
  return problems
}

/** 递归收集 `src/pages/**` 下的页面文件（bmini 相对 posix 路径）。 */
function pageFiles(dir: string = PAGES_ROOT): string[] {
  const collected: string[] = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) collected.push(...pageFiles(full))
    else if (entry.name.endsWith('.tsx')) {
      collected.push(path.relative(BMINI_ROOT, full).split(path.sep).join('/'))
    }
  }
  return collected.sort()
}

const LEDGER = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'worker-surface-ledger.json'), 'utf8'),
) as { entries: LedgerEntry[] }

const readReal = (rel: string): string => {
  const abs = path.join(BMINI_ROOT, rel)
  if (!fs.existsSync(abs)) throw new Error(`找不到受管页面：${rel}（路径漂移不得静默跳过 ⇒ 红）`)
  return fs.readFileSync(abs, 'utf8')
}

function realInput(): LedgerInput {
  return { pages: pageFiles(), read: readReal, entries: LEDGER.entries }
}

/** 变异生效自证：锚点失配会让 `replace` 静默返回原文 ⇒ 红证退化成空断言。 */
function expectMutationApplied(mutated: string, tokens: string[], label: string): void {
  for (const token of tokens) {
    if (!mutated.includes(token)) {
      throw new Error(
        `[${label}] 变异未生效：变异体里找不到「${token}」⇒ 红证会退化成空断言。` +
          `锚点与被读文件版本不匹配，不要靠下游断言反推。`,
      )
    }
  }
}

describe('工人面写入口台账元守卫（issue #6467 S8）', () => {
  it('正跑：全量页面的工人写调用都已登记，且每条登记的身份分流/引导都活着', () => {
    const input = realInput()
    // 反空跑：真的扫到了页面与登记（否则两边都是空集 ⇒ 判据空转通过）
    expect(input.pages.length).toBeGreaterThanOrEqual(12)
    expect(LEDGER.entries.length).toBeGreaterThanOrEqual(3)
    expect(ledgerProblems(input)).toEqual([])
    // 两类形态都真的覆盖到了（否则「必须先有工人身份」这一族从没被核过）
    expect(LEDGER.entries.filter((entry) => entry.requires_worker_session).length).toBeGreaterThanOrEqual(3)
  })

  it('🔴 判据 5 红证：台账被清空 ⇒ 判红（空台账不是「全部合规」，是 fail-closed）', () => {
    const empty = ledgerProblems({ ...realInput(), entries: [] })
    expect(empty.join('\n')).toContain('台账为空')
    expect(empty.join('\n')).toContain('未登记即红')
  })

  it('🔴 判据 1 红证：新页面里出现工人写调用而没登记 ⇒ 判红并具名', () => {
    const input = realInput()
    const injected = 'src/pages/worker/brand-new/index.tsx'
    const read = (rel: string): string =>
      rel === injected ? 'export default function P() { void workerLogout() }' : input.read(rel)
    const problems = ledgerProblems({ ...input, pages: [...input.pages, injected], read })
    expect(problems.join('\n')).toContain(`${injected}::workerLogout(`)
    expect(problems.join('\n')).toContain('未登记即红')
  })

  it('🔴 判据 2 红证：摘掉某页的写调用而不删登记 ⇒ 判红（条目必须活着，只许缩短）', () => {
    const input = realInput()
    const target = 'src/pages/worker/home/index.tsx'
    const read = (rel: string): string =>
      rel === target ? input.read(rel).replace(/workerLogout\(/g, 'loggedOut(') : input.read(rel)
    expectMutationApplied(
      read(target),
      ['loggedOut('],
      '判据 2 摘掉 workerLogout 调用',
    )
    expect(read(target).includes('workerLogout(')).toBe(false)
    const problems = ledgerProblems({ ...input, read })
    expect(problems.join('\n')).toContain(`${target}::workerLogout(`)
    expect(problems.join('\n')).toContain('台账条目已死')
  })

  it('🔴 判据 3 红证：把报工页的身份分流摘掉（内存变异）⇒ 判红并具名到页面', () => {
    const input = realInput()
    const target = 'src/pages/production/index/index.tsx'
    const read = (rel: string): string =>
      rel === target ? input.read(rel).replace(/hasWorkerSession\(\)/g, 'true') : input.read(rel)
    const mutated = read(target)
    // 变异生效自证：分流记号真的没了，而写调用与引导都还在（所以"按文本在不在"判的守卫仍会绿）
    expectMutationApplied(mutated, ['PRODUCTION_WORKER_LOGIN_REQUIRED', 'completeByScan('], '判据 3 摘掉身份分流')
    expect(mutated.includes('hasWorkerSession()')).toBe(false)
    // 对照：真仓库下本判据判绿（否则下面那条"红"可能只是读错了文件）
    expect(ledgerProblems(input)).toEqual([])
    const problems = ledgerProblems({ ...input, read })
    expect(problems.join('\n')).toContain(target)
    expect(problems.join('\n')).toContain('身份分流')
  })

  it('🔴 判据 3b 红证：**留着**身份分流声明、只把无码写入口的身份闸门摘掉 ⇒ 判红', () => {
    const input = realInput()
    const target = 'src/pages/production/index/index.tsx'
    // 变异形态：声明还在（`const workerReady = hasWorkerSession()`），只是「完成报工」的
    // **无码那条路**（issue #6598）不再被它挡着 —— 这一族**按"某个 token 在不在"判的守卫会漏**
    // （声明那行仍在文件里）⇒ 台账必须同时核**该写路独有**的渲染条件。
    const read = (rel: string): string =>
      rel === target
        ? input.read(rel).replace('{workerReady && (', '(')
        : input.read(rel)
    const mutated = read(target)
    // 变异生效自证：① 该写路独有的闸门记号真的没了；② 分流声明与两条写调用本体都还在
    // （所以「按调用在不在」判的判据 1/2 仍会绿 —— 本台账必须核渲染条件才拦得住）。
    expect(mutated.includes('{workerReady && (')).toBe(false)
    expect(mutated.includes('const workerReady = hasWorkerSession()')).toBe(true)
    expect(mutated.includes('completeByScan(')).toBe(true)
    expect(mutated.includes('reportOperationFree(')).toBe(true)
    const problems = ledgerProblems({ ...input, read })
    expect(problems.join('\n')).toContain(target)
    expect(problems.join('\n')).toContain('身份分流')
    expect(problems.join('\n')).toContain('reportOperationFree(')
  })

  /**
   * 🔴 <b>边界（照实登记，§19.1）</b>：报工页的两处身份闸门写法**刻意不同**
   * （扫码一屏 `{workerReady ? (` / 逐道报工 `{workerReady && (`）—— 这样台账才能把
   * 「摘掉哪一条写路的闸门」具名到那条路上。若日后有人把两处改成同一写法，
   * 下面这条会红，提示复核 `worker-surface-ledger.json` 的 gate_tokens 口径
   * （否则两条登记的闸门记号会退化成同一个、判据 3b 的红证随即失效）。
   */
  it('判据 3b 边界：两条写路的身份闸门记号**各自可定位**（写法不同 + 都在文件里）', () => {
    const input = realInput()
    const target = 'src/pages/production/index/index.tsx'
    const body = stripComments(input.read(target))
    expect(body.includes('{workerReady ? (')).toBe(true) // 扫码一屏
    expect(body.includes('{workerReady && (')).toBe(true) // 逐道报工（无码自由报工那条）
    expect(body.includes('completeByScan(')).toBe(true)
    expect(body.includes('reportOperationFree(')).toBe(true)
    // 真仓库下台账判绿（对照读数）
    expect(ledgerProblems(input)).toEqual([])
  })

  it('🔴 判据 4 红证：删掉引导文案 / 改坏去登录入口 ⇒ 判红', () => {
    const input = realInput()
    const target = 'src/pages/production/index/index.tsx'
    const read = (rel: string): string =>
      rel === target
        ? input.read(rel)
            .replace(/PRODUCTION_WORKER_LOGIN_REQUIRED/g, 'SOME_OTHER_HINT')
            .replace(/WORKER_TAB_LOGIN_ROUTE/g, 'SOME_OTHER_ROUTE')
        : input.read(rel)
    const problems = ledgerProblems({ ...input, read })
    expect(problems.join('\n')).toContain('引导文案')
    expect(problems.join('\n')).toContain('登录页工人入口')
  })
})
