// case_ids: BM-038
/**
 * 工人面动作**端点归属**台账元守卫（issue #6472，S3；AGENTS.md 铁律 8 / `migao-dev-flow` §23 G1~G3）。
 *
 * ## 治的形态
 * 「修一个缺陷只修这一处 = 没修」：#6472 的病灶是**发货**这一个工人动作打了商家端点，
 * 但**同一台纯工人设备**上还有读面（`getOrderOperations`）走过同一条路 —— 修好发货
 * 不会让「下一个工人动作又打 `/api/admin/`」这件事变红。本台账把「哪个 service 动作函数
 * 打哪个端点 / 谁是它的工人替代」变成**可执行判据**。
 *
 * ## 判据（每条都有在测试内实测的红证）
 * | # | 判据 | 红证（in-test 注入，走**同一份** `ledgerProblems`） |
 * |---|---|---|
 * | 1 | **未登记即红**：身份感知页面（出现 `hasWorkerSession(` 的 `.tsx`）import 的 service 模块里，**函数体含 `/api/admin/`** 的顶层导出函数，凡不在台账 ⇒ 具名判红 | 注入一个函数体含 `/api/admin/` 的新函数 ⇒ 报出 `src/services/productionService.ts::injectedAdminAction` |
 * | 2 | **台账只许缩短**：每条登记都必须仍能被现扫命中（函数删了 / 不再被页面引用 ⇒ 条目已死 ⇒ 红） | 摘掉 `shipOrder` 的登记 ⇒ 判据 1 红；登记一个不存在的函数 ⇒ 判据 2 红 |
 * | 3 | **admin 条目必须给出路**：要么有 `worker_alternative`（同 service 里真的导出、函数体真的含 `/api/worker/`），要么显式写明 `reason`（有意不搬） | 把 `shipOrder` 的 `worker_alternative` 清空且不给 `reason` ⇒ 红；把替代函数名改成不存在 ⇒ 红 |
 * | 4 | **台账不许空转**（fail-closed）：条数为 0 ⇒ 红；每条必须声明 `case_ids` | 清空台账「消红」⇒ 红 |
 * | 5 | **工人替代必须真的被用上**：登记了 `worker_alternative` 就必须在调用页里找到对它的调用（声明了替代却没人调 = 接线不在，§28.2） | 把页面里的 `shipWorkerOrder(` 改名 ⇒ 「接线不在」红 |
 *
 * ## 边界（照实登记，`migao-dev-flow` §19.1）
 * ① 射程 = **顶层导出函数**（非导出 / 嵌套函数不在面内）；**只裁 `/api/admin/` 这一族**
 *    （`/api/worker/**` 的纯工人端点本就到得了、不是病灶 ⇒ 不登记，避免台账把「正常工人端点」也吃进来）；
 * ② 判的是**静态形态**（端点字符串在不在、页面有没有引用），**不是**运行期真的走对了端点 ——
 *    行为面由 `tests/production-ship-endpoint-by-identity.test.ts` 与 `tests/production-page.test.tsx` 的实例判据承担；
 * ③ 端点常量被抽成变量时静态扫描看不见（`frontend/bmini-app/src/services/workerInboundService.ts`
 *    的端点映射对象即此形态，当前 0 命中，如实登记）；④ 不改任何门禁的通过条件、不新增豁免。
 */
import fs from 'fs'
import path from 'path'
import { stripComments } from './helpers/h5PlatformLists'

const BMINI_ROOT = path.join(__dirname, '..')
const SERVICES_REL = 'src/services'
const PAGES_REL = 'src/pages'

/** 身份感知页面的记号：页面自己声明「本机有没有工人身份」的单一真值。 */
const WORKER_IDENTITY_MARKER = 'hasWorkerSession('

/** 🔴 病灶记号：工人面动作打**商家端点**（`/api/admin/**` 的拒绝集合含 `worker` ⇒ 纯工人设备必被拒）。 */
const ADMIN_ENDPOINT_MARKER = '/api/admin/'

export interface DetectedAction {
  /** service 模块（bmini 相对 posix 路径，如 `src/services/productionService.ts`） */
  service: string
  fn: string
  /** 🔴 本台账**只裁** `admin` 一族：工人面动作打 `/api/admin/**` 是病灶（`worker` 端点本就到得了） */
  endpoint: 'admin'
}

export interface ActionLedgerEntry {
  service: string
  fn: string
  endpoint: 'admin'
  label: string
  /** 工人替代函数名（同 service 里的顶层导出；空串 = 走 `reason` 登记「有意不搬」） */
  worker_alternative: string
  reason?: string
  pages: string[]
  requires_worker_session: boolean
  case_ids: string[]
}

export interface ActionLedgerInput {
  /** service 源码：相对路径 → 内容 */
  services: Record<string, string>
  /** 页面源码：相对路径 → 内容 */
  pages: Record<string, string>
  entries: ActionLedgerEntry[]
}

/** 顶层导出函数（名字 + 起止下标）；只认 `export function` / `export async function`。 */
export function exportedFunctions(text: string): { name: string; start: number; end: number }[] {
  const out: { name: string; start: number; end: number }[] = []
  const re = /^export (?:async )?function ([A-Za-z0-9_]+)\s*[(<]/gm
  let match: RegExpExecArray | null
  while ((match = re.exec(text))) out.push({ name: match[1], start: match.index, end: text.length })
  for (let i = 0; i < out.length; i += 1) {
    if (i + 1 < out.length) out[i].end = out[i + 1].start
  }
  return out
}

/** 页面是否「身份感知」（出现 `hasWorkerSession(`）。 */
function isWorkerAwarePage(text: string): boolean {
  return stripComments(text).includes(WORKER_IDENTITY_MARKER)
}

/**
 * 该 service 模块的**导入记号**（页面用相对路径 import：`../../../services/productionService`
 * ⇒ 只认末段 `services/<文件名>`，**不假设**任何前缀深度）。
 */
function importMarker(service: string): RegExp {
  const file = service.slice(service.lastIndexOf('/') + 1).replace(/\.ts$/, '')
  return new RegExp(`services/${file.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?:'|")`)
}

/** 现取：身份感知页面 import 的 service 模块里，**函数体含 `/api/admin/`** 的顶层导出函数。 */
export function detectActions(input: ActionLedgerInput): DetectedAction[] {
  const awarePages = Object.entries(input.pages).filter(([, text]) => isWorkerAwarePage(text))
  const detected: DetectedAction[] = []
  for (const [service, raw] of Object.entries(input.services)) {
    const text = stripComments(raw)
    const marker = importMarker(service)
    const importedByAwarePage = awarePages.some(([, pageText]) => marker.test(pageText))
    if (!importedByAwarePage) continue
    for (const fn of exportedFunctions(text)) {
      const body = text.slice(fn.start, fn.end)
      if (body.includes(ADMIN_ENDPOINT_MARKER)) detected.push({ service, fn: fn.name, endpoint: 'admin' })
    }
  }
  return detected
}

function pairKey(entry: { service: string; fn: string; endpoint: string }): string {
  return `${entry.service}::${entry.fn}::${entry.endpoint}`
}

/** 核心判定（真判据与注入式红证**共用同一份** —— 红证必须走真判据，见 §23.5）。 */
export function ledgerProblems(input: ActionLedgerInput): string[] {
  const problems: string[] = []
  const detected = detectActions(input)
  const detectedKeys = new Set(detected.map(pairKey))
  const declaredKeys = new Set(input.entries.map(pairKey))

  // 判据 4：台账不许空转（fail-closed）—— 空台账不是「全部合规」
  if (input.entries.length === 0) {
    problems.push('台账为空：工人面动作端点台账被清空 ⇒ fail-closed 判红（「空」不等于「全部合规」）')
  }

  // 判据 1：未登记即红
  for (const action of detected) {
    if (!declaredKeys.has(pairKey(action))) {
      problems.push(
        `未登记即红：${pairKey(action)} —— 身份感知页面 import 的 service 里有这样的动作函数，` +
          `而 tests/worker-action-endpoint-ledger.json 没有登记它（新工人动作必须同批登记「走哪个端点 / 谁是工人替代」）`,
      )
    }
  }
  // 判据 2：台账只许缩短（条目必须仍能被现扫命中）
  for (const entry of input.entries) {
    if (!detectedKeys.has(pairKey(entry))) {
      problems.push(
        `台账条目已死：${pairKey(entry)} —— 现扫命中不到它（函数已删 / 已不再被身份感知页面引用 / ` +
          `端点已搬走）⇒ 同批删掉这一条（台账只许缩短）`,
      )
    }
  }

  for (const entry of input.entries) {
    const key = pairKey(entry)
    // 判据 4：每条登记都要有用例面关联
    if (!Array.isArray(entry.case_ids) || entry.case_ids.length === 0) {
      problems.push(`${key}：没有声明 case_ids（登记而不关联用例 ⇒ 没人知道它靠哪条判据活着）`)
    }
    const serviceText = input.services[entry.service]
    if (serviceText === undefined) {
      problems.push(`${key}：登记的 service 不在射程内（${entry.service}）⇒ 台账指向了不存在的模块`)
      continue
    }
    const cleanService = stripComments(serviceText)
    const fn = exportedFunctions(cleanService).find((candidate) => candidate.name === entry.fn)
    if (!fn) {
      problems.push(`${key}：登记的 ${entry.service} 里找不到顶层导出函数 ${entry.fn} ⇒ 条目失效（漂移不得静默跳过）`)
      continue
    }
    // 判据 3：admin 条目必须给出路（工人替代，或显式写明有意不搬的理由）
    const hasAlternative = !!entry.worker_alternative
    const hasReason = !!entry.reason && entry.reason.trim().length > 0
    if (!hasAlternative && !hasReason) {
      problems.push(
        `${key}：admin 端点条目既没有 worker_alternative 也没有 reason ⇒ 「工人面动作打商家端点」` +
          `这件事没有被交代（要么给工人替代函数，要么写明有意不搬的理由）`,
      )
    }
    if (hasAlternative) {
      const alt = exportedFunctions(cleanService).find(
        (candidate) => candidate.name === entry.worker_alternative,
      )
      if (!alt) {
        problems.push(`${key}：worker_alternative=${entry.worker_alternative} 不在 ${entry.service} 的顶层导出里 ⇒ 替代函数是空的`)
      } else if (!cleanService.slice(alt.start, alt.end).includes('/api/worker/')) {
        problems.push(`${key}：worker_alternative=${entry.worker_alternative} 的函数体里没有 /api/worker/ ⇒ 它并不是工人替代`)
      }
      // 判据 5b：工人替代必须**真的被调用页用上**（声明了替代却没人调 = 接线不在，§28.2）
      for (const page of entry.pages) {
        const pageText = input.pages[page]
        if (pageText !== undefined && !stripComments(pageText).includes(`${entry.worker_alternative}(`)) {
          problems.push(
            `${key}：登记了 worker_alternative=${entry.worker_alternative}，但调用页 ${page} 里找不到对它的调用 ` +
              `⇒ 替代函数只是**声明**，接线不在（工人身份下仍走商家端点）`,
          )
        }
      }
    }
    // 判据 5：条目必须活着（调用页仍 import 该 service、且该函数在页面里被引用）
    if (!Array.isArray(entry.pages) || entry.pages.length === 0) {
      problems.push(`${key}：没有声明调用页（条目必须能指回它的消费者）`)
      continue
    }
    for (const page of entry.pages) {
      const pageText = input.pages[page]
      if (pageText === undefined) {
        problems.push(`${key}：登记的调用页不存在：${page}`)
        continue
      }
      const cleanPage = stripComments(pageText)
      if (!importMarker(entry.service).test(cleanPage)) {
        problems.push(`${key}：${page} 已不再 import ${entry.service} ⇒ 登记已死`)
        continue
      }
      // 函数被页面引用（调用形态）—— 只认「函数名 + (」这一形态（注释已剥）
      if (!cleanPage.includes(`${entry.fn}(`)) {
        problems.push(`${key}：${page} 里找不到对 ${entry.fn}( 的调用 ⇒ 条目已死（台账只许缩短）`)
      }
      if (entry.requires_worker_session && !cleanPage.includes(WORKER_IDENTITY_MARKER)) {
        problems.push(`${key}：条目声称该页按身份分流，但 ${page} 里找不到 ${WORKER_IDENTITY_MARKER} ⇒ 分流记号漂移`)
      }
    }
  }
  return problems
}

// ── 真实语料 ────────────────────────────────────────────────────────────────

function walk(dir: string, keep: (name: string) => boolean, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(full, keep, out)
    else if (keep(entry.name)) out.push(full)
  }
  return out
}

function toRel(abs: string): string {
  return path.relative(BMINI_ROOT, abs).split(path.sep).join('/')
}

function readRel(rel: string): string {
  const abs = path.join(BMINI_ROOT, rel)
  if (!fs.existsSync(abs)) throw new Error(`找不到受管文件：${rel}（路径漂移不得静默跳过 ⇒ 红）`)
  return fs.readFileSync(abs, 'utf8')
}

function realInput(): ActionLedgerInput {
  const services: Record<string, string> = {}
  for (const abs of walk(path.join(BMINI_ROOT, SERVICES_REL), (name) => name.endsWith('.ts'))) {
    services[toRel(abs)] = fs.readFileSync(abs, 'utf8')
  }
  const pages: Record<string, string> = {}
  for (const abs of walk(path.join(BMINI_ROOT, PAGES_REL), (name) => name.endsWith('.tsx'))) {
    pages[toRel(abs)] = fs.readFileSync(abs, 'utf8')
  }
  return { services, pages, entries: LEDGER.entries }
}

/**
 * 变异体（走**同一份**真判据）：`{...input}` 会丢掉原型方法 ⇒ 用 `Object.assign` 保原型。
 * 🔴 这是红证能不能算数的前提（丢了原型 = 判据静默变成空断言，见 §23.4 陷阱 T1）。
 */
function mutate(input: ActionLedgerInput, patch: Partial<ActionLedgerInput>): ActionLedgerInput {
  return Object.assign(Object.create(Object.getPrototypeOf(input)), input, patch)
}

const LEDGER = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'worker-action-endpoint-ledger.json'), 'utf8'),
) as { entries: ActionLedgerEntry[] }

/** 变异生效自证：锚点失配会让 replace 静默返回原文 ⇒ 红证退化成空断言。 */
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

describe('工人面动作端点台账元守卫（issue #6472 S3）', () => {
  it('正跑：身份感知页面的全部端点动作都已登记，且每条登记仍活着 / 有工人出路', () => {
    const input = realInput()
    // 反空跑：真的扫到了 service 与身份感知页面（否则两边都是空集 ⇒ 判据空转通过）
    expect(Object.keys(input.services).length).toBeGreaterThanOrEqual(6)
    const awarePages = Object.values(input.pages).filter((text) => isWorkerAwarePage(text))
    expect(awarePages.length).toBeGreaterThanOrEqual(3)
    const detected = detectActions(input)
    expect(detected.length).toBeGreaterThanOrEqual(3)
    expect(input.entries.length).toBeGreaterThanOrEqual(3)
    expect(ledgerProblems(input)).toEqual([])
    // 台账条数**现取**（文档不写死）：登记集与现扫集双向相等
    expect(new Set(input.entries.map(pairKey)).size).toBe(detected.length)
  })

  // ── 判据 1：未登记即红 ────────────────────────────────────────────────────

  it('红证①未登记即红：给已被工人页引用的 service 注入一个 admin 动作函数 ⇒ 具名判红', () => {
    const input = realInput()
    const key = 'src/services/productionService.ts'
    const injected =
      input.services[key] +
      '\n/** 注入：一个新的工人会点、却打商家端点的动作 */\nexport async function injectedAdminAction(orderId: string) {\n  return post(`/api/admin/production/orders/${orderId}/nope`, {})\n}\n'
    expectMutationApplied(injected, ['injectedAdminAction', '/api/admin/'], '未登记即红')
    const problems = ledgerProblems({ ...input, services: { ...input.services, [key]: injected } })
    expect(problems.some((p) => p.includes('未登记即红') && p.includes('injectedAdminAction'))).toBe(true)
    // 反向对照：不注入 ⇒ 同一份判据不报（否则红证是空断言）
    expect(ledgerProblems(input).filter((p) => p.includes('injectedAdminAction'))).toEqual([])
  })

  // ── 判据 2：台账只许缩短 / 条目必须活着 ────────────────────────────────────

  it('红证②台账条目已死：登记一个现扫命中不到的函数 ⇒ 判红', () => {
    const input = realInput()
    const dead: ActionLedgerEntry = {
      service: 'src/services/productionService.ts',
      fn: 'shippedLongAgo',
      endpoint: 'admin',
      label: '已不存在的函数',
      worker_alternative: '',
      reason: 'x',
      pages: ['src/pages/production/index/index.tsx'],
      requires_worker_session: false,
      case_ids: ['BM-039'],
    }
    const problems = ledgerProblems({ ...input, entries: [...input.entries, dead] })
    expect(problems.some((p) => p.includes('台账条目已死') && p.includes('shippedLongAgo'))).toBe(true)
  })

  it('红证②b 台账只许缩短：摘掉 `shipOrder` 的登记（函数还在被工人页引用）⇒ 未登记即红', () => {
    const input = realInput()
    const without = input.entries.filter((entry) => entry.fn !== 'shipOrder')
    expect(without.length).toBe(input.entries.length - 1)
    const problems = ledgerProblems({ ...input, entries: without })
    expect(problems.some((p) => p.includes('未登记即红') && p.includes('shipOrder'))).toBe(true)
  })

  // ── 判据 3：admin 条目必须给出路 ──────────────────────────────────────────

  it('红证③ admin 条目既无工人替代也无理由 ⇒ 判红', () => {
    const input = realInput()
    const stripped = input.entries.map((entry) =>
      entry.fn === 'shipOrder' ? { ...entry, worker_alternative: '', reason: undefined } : entry,
    )
    const problems = ledgerProblems({ ...input, entries: stripped })
    expect(problems.some((p) => p.includes('shipOrder') && p.includes('既没有 worker_alternative 也没有 reason'))).toBe(true)
  })

  it('红证③b 工人替代函数名不存在 / 不含工人端点 ⇒ 判红', () => {
    const input = realInput()
    const ghost = input.entries.map((entry) =>
      entry.fn === 'shipOrder' ? { ...entry, worker_alternative: 'shipWorkerOrderGhost' } : entry,
    )
    expect(
      ledgerProblems({ ...input, entries: ghost }).some((p) => p.includes('不在') && p.includes('shipWorkerOrderGhost')),
    ).toBe(true)
  })

  // ── 判据 4：空台账 fail-closed ────────────────────────────────────────────

  it('红证④ 清空台账「消红」⇒ fail-closed 判红（且现扫到的动作全部未登记）', () => {
    const input = realInput()
    const problems = ledgerProblems({ ...input, entries: [] })
    expect(problems.some((p) => p.includes('台账为空'))).toBe(true)
    expect(problems.some((p) => p.includes('未登记即红'))).toBe(true)
  })

  // ── 判据 5：工人替代必须真的被用上（接线不在 ⇒ 红） ───────────────────────

  it('红证⑤ 页面不再调工人替代函数（替代只在台账里声明）⇒ 判红（§28.2：判据绿 ≠ 接线在）', () => {
    const input = realInput()
    const page = 'src/pages/production/index/index.tsx'
    const mutated = input.pages[page].replace('shipWorkerOrder(', 'shipWorkerOrderRenamed(')
    expectMutationApplied(mutated, ['shipWorkerOrderRenamed('], '接线必须活着')
    const problems = ledgerProblems({ ...input, pages: { ...input.pages, [page]: mutated } })
    expect(
      problems.some((p) => p.includes('shipWorkerOrder') && p.includes('接线不在')),
    ).toBe(true)
    // 反向对照：不注入 ⇒ 同一份判据不报（否则红证是空断言）
    expect(ledgerProblems(input).filter((p) => p.includes('接线不在'))).toEqual([])
  })
})
