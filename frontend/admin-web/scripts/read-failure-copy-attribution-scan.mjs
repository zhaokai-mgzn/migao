#!/usr/bin/env node
// case_ids: UI-046, PP-010
/**
 * 「读面失败时**不许**把失败说成别的原因」判据**单一源**（issue #6702）。
 *
 * ## 为什么要有它（本单的两种缺陷形态，各自实测过）
 *
 * `/production/remnants` 读面注入 500（`GET /api/admin/production/remnants**` ⇒ 500）实测：
 *
 * ① **计数照样印零**：屏上一边写「余料台账读取失败」，一边照旧印「共 **0** 块」
 *    （源码 = `data?.page?.total ?? 0`）—— 读不到 ⇒ 计数是**未知**，印 0 是**界面在撒谎**
 *    （商家据此以为「没有余料」）。与 #6701 的工作台金额面同族：**读失败画成零值**；
 * ② **500 被归因成权限**：文案逐字「可能是当前岗位没有「工艺配置」权限」——
 *    把**服务侧故障**说成**权限问题** ⇒ 商家去找管理员开一个跟本页无关的权限，真因被掩盖。
 *
 * 只改这一页 = 没修：下一个页面把同一形态写回来**没有任何东西会变红**（同族已实测：
 * `stock-ledger/page.tsx` 两处**逐字**同形态，见 `LEDGER`）⇒ 判据必须落在**族**上。
 *
 * ## 判的是哪两个形态（口径，逐条可判别力自证）
 *
 * 面 = `src/app/(dashboard)`（商家后台页面）下的 `.tsx` / `.ts`，**逐行、剥注释后**判定
 * （`stripLineComments`：本仓注释惯例会**引用**这些串，不剥 ⇒ 判据被自己的文案喂红，
 * 实测过的坑）。
 *
 * - **A 形态 = 读失败 + 零值兜底上屏**：一行 JSX 文本同时含
 *   ① **零值兜底**（`?? 0` / `|| 0`）且 ② **读面信封锚**（`page` / `data` / `res` / `result` / `report`
 *   之一的 `.` 后接 `total|items|list|rows`）且 ③ **计数/金额措辞**（`共` / `块` / `条` / `笔` / `元`），
 *   而该行**没有**失败守卫（`!error` / `!err` / `== 'error'` 之类）。修前逐字形态：
 *   `<span>共 {data?.page?.total ?? 0} 块</span>`。
 *   🔴 **「没有失败守卫」也要成对**：本页修后「修后行」= `共 {error ? '—' : (data?.page?.total ?? 0)} 块`
 *   —— 它**含 `?? 0`** 且**不含 `!error`**，若只判「有 `?? 0` 就红」会把已修好的形态判红（假红）
 *   ⇒ 判据认的是**「`?? 0` 直接交给屏上」**，不是「文件里出现了 `?? 0`」。
 *
 * - **B 形态 = 非 403 的失败被归因成权限**：一行里有**权限因果措辞**（「(没有|无|缺少|不足|未获|不具备)…
 *   权限」/「权限不足」/「未授权」/「没有权限」）且这一行**不读状态码**
 *   （`status` / `403` / `code` / `forbidden` 一个都没有）。
 *   典型形态：`setError('批次余量读取失败（可能是当前岗位没有「商品管理」权限）—— 请联系管理员开权限后重试')`
 *   （该页见 `LEDGER`）。修后形态（两条分开）：`if (status === 403) { setError('…没有「生产管理」…权限…') }`
 *   这一行含 `403` ⇒ 不红；服务侧那条 `setError('余料台账暂时读不到（读数服务暂时不可用）—— 请稍后重试')`
 *   无权限因果措辞 ⇒ 不红。
 *
 * 🔴 **B 形态对本单修前那句 500 文案检不出**（实测，如实登记）：`可能是当前岗位没有「工艺配置」权限`
 * 里「没有」与「权限」之间夹了「「工艺配置」」⇒ 要检它得放宽到「出现『权限』二字」（第一版就是那样，
 * 代价 = 2 处假红，见 `PERMISSION_CAUSE_RE` 的注释）。⇒ **修前那句的守卫靠实例判据**
 * （`tests/unit/pages/production-remnants-read-failure.test.tsx` ② 逐字锚在用户可见面上），
 * B 形态只作**类级补充**（覆盖更露骨的「没有权限」式归因，如 `stock-ledger`）。
 *
 * ## 两级判据（缺一不可）
 *
 * - **扫描判据**：命中 A / B ⇒ 必须登记进 `LEDGER`（**未登记即红**）；
 * - **正向核**：`POSITIVE_ANCHORS` 里每一条「已改对的页面」必须**逐字**含它的锚
 *   （失败锚点 + 真重试出口 + **按状态分流**的判据函数签名）⇒ 锚被删当场红；
 * - **台账只许缩短**：`LEDGER.length > LEDGER_FLOOR` ⇒ 红（逼着先修，不是先加豁免）；
 *   且台账条目**仍须真命中**其声明的形态（修好了 / 删了 ⇒ 僵尸条目当场红）。
 *
 * ## 与 #6701 扫描面的**边界**（两份台账不许互相打架）
 *
 * | 面 | 扫描器 | 判什么 |
 * |---|---|---|
 * | **本面**（issue #6702） | 本文件 | **读失败的「话术归因」与「计数零值」**：A = 读失败仍印计数/金额的零值；B = 非 403 被说成权限 |
 * | #6701 的**工作台金额面** | `frontend/admin-web/scripts/derived-zero-fallback-scan.mjs`（`SCOPE = src/app/(dashboard)/dashboard`，**在飞**） | **派生字面量的零值回退**（工作台金额/图表口径） |
 *
 * 两面的**交集**（`dashboard/**` 里的零值回退）以 #6701 为准：本文件 `SCOPE` 逐字含
 * `dashboard` 目录 ⇒ **本条有意让出该目录**（`EXCLUDE_DIRS`），避免同一行被两份台账各记一次
 * （重复记账会变成「修一处要改两处台账」，且两份台账会互相把对方判成僵尸条目）。
 *
 * ## 边界（照实登记，`migao-dev-flow` §19.1）
 *
 * - **只认源码文本形态**（逐行）：多行 JSX（`共` 与 `?? 0` 不在一行）会漏判；
 *   把 `?? 0` 先存进变量再上屏（如 `const n = data?.total ?? 0` 后 `<span>共 {n} 块</span>`）
 *   也漏判 —— 要判它得做数据流分析，那是另一个包；
 * - B 形态的「不读状态码」是**行内**判据：`const status = …` 在上文、`setError('…权限…')` 在下文
 *   且中间没有 `if` 的形态会**假红**（本仓未实测到，`settings/page.tsx` 的专业形态是同行的 `403` 比较）；
 * - **不判**「文案语气好不好」（那是 §31 / 产品评审面）；
 * - 只读：命令行跑只打印，本文件不写任何文件。
 */
import { readdirSync, statSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'

/** 判据面：商家后台（与 `read-failure-empty-state-scan.mjs` 同面，便于两把尺子对齐） */
export const SCOPE = 'src/app/(dashboard)'
/** 让给 #6701（工作台金额面）的目录：见文件头「与 #6701 扫描面的边界」 */
const EXCLUDE_DIRS = new Set(['node_modules', '.next', 'dist', 'coverage', '__pycache__', 'dashboard'])

/** 剥行注释（`[^:]` 避开 `http://`）；注释里的同形态**不算证据** */
export function stripLineComments(code) {
  return code
    .split('\n')
    .map((l) => l.replace(/(^|[^:])\/\/.*$/, '$1'))
    .join('\n')
}

/** A 形态：零值兜底 */
const ZERO_FALLBACK_RE = /(\?\?|\|\|)\s*0(?![\d.])/
/** A 形态：读面信封锚（`…page.total` / `data.items` …） */
const ENVELOPE_ANCHOR_RE = /\b(page|data|res|result|report)\s*\??\s*\.\s*(total|items|list|rows)\b/
/** A 形态：计数 / 金额措辞 */
const COUNT_WORD_RE = /(共|块|条|笔|元)/
/** A 形态：失败守卫（本仓既有写法：`!loading && !error && …` / `error ? '—' : …`） */
const FAILURE_GUARD_RE = /(!\s*(error|err|failed|loadError|readError)\b)|(\b(error|err|failed|loadError|readError)\s*\??\s*[?:])/
/**
 * B 形态：**把权限说成原因**的措辞（不是「提到权限」）。
 *
 * 🔴 口径收窄**是实测逼出来的**（第一版写 `/(权限|无权限|未授权)/` ⇒ 3 处命中里 2 处是假红）：
 * - `roles/page.tsx`：`'权限目录读取失败 —— 可能是网络或服务暂时不可用'` —— 权限是**读的对象**
 *   （权限目录），不是在说「你没权限」；
 * - `employees/page.tsx`：`toast.error('加载菜单权限失败，请刷新重试')` —— 同理。
 * ⇒ 只有「**没有 / 不足 / 未授权** + 权限」这种**因果句**才算归因。
 */
const PERMISSION_CAUSE_RE = /((没有|无|缺少|不足|未获|不具备)[^。，；]*?权限)|(权限不足)|(未授权)|(没有权限)/
/** B 形态：这一行读了状态码 / 权限码（读到了就不算「一律归因成权限」） */
const STATUS_READ_RE = /(\bstatus\b|\b403\b|\bcode\b|forbidden|PASSWORD_CHANGE_REQUIRED)/i
/** B 形态：只认**错误话术**（避免把「为什么不渲染：不持码不进入」这类注释/文案误判） */
const ERROR_SET_RE = /(set[A-Z]\w*(Error|Err|Msg|Message|Hint|Fail\w*)\s*\(|catch\s*\(|catch\s*\{|toast\.error\s*\()/

/**
 * 单文件判据（纯函数：守卫的判别力自证直接喂文本进来）。
 * 返回 `[]`（不命中）或 `[{ file, line, form }]`（`line` 为**文件内行号**）。
 */
export function classifySource(file, source) {
  const hits = []
  stripLineComments(source)
    .split('\n')
    .forEach((line, i) => {
      if (
        ZERO_FALLBACK_RE.test(line) &&
        ENVELOPE_ANCHOR_RE.test(line) &&
        COUNT_WORD_RE.test(line) &&
        !FAILURE_GUARD_RE.test(line)
      ) {
        hits.push({ file, line: i + 1, form: 'A' })
      }
      if (PERMISSION_CAUSE_RE.test(line) && !STATUS_READ_RE.test(line) && ERROR_SET_RE.test(line)) {
        hits.push({ file, line: i + 1, form: 'B' })
      }
    })
  return hits
}

function walk(dir, out = []) {
  for (const entry of readdirSync(dir).sort()) {
    if (EXCLUDE_DIRS.has(entry)) continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) out.push(full)
  }
  return out
}

/** 扫描面内的全部源码文件（仓库相对路径，`/` 分隔） */
export function listSourceFiles(root) {
  return walk(join(root, SCOPE))
    .map((f) => relative(root, f).split('\\').join('/'))
    .sort()
}

/** 命中清单（**单一源**） */
export function copyAttributionSites(root) {
  const files = listSourceFiles(root)
  const sites = []
  for (const file of files) {
    sites.push(...classifySource(file, readFileSync(join(root, file), 'utf8')))
  }
  return { files, sites }
}

/** 台账键 = `仓库相对路径::形态`（**不写行号**：活跃文件的裸行号几分钟就失效） */
export function ledgerKey(site) {
  return `${site.file}::${site.form}`
}

/**
 * 台账（**只许缩短**）：命中而**本包不修**的条目，逐条给理由。
 * 新增任何条目 ⇒ 「台账只许缩短」判据红 ⇒ 必须先在 PR body 说明为什么。
 *
 * ⚠️ 现有 1 条是**如实记账**（**不收编成「已修」**）：`stock-ledger/page.tsx` 两处 `catch`
 * 与 issue #6702 的修前形态**同族**（一律说「可能是当前岗位没有「商品管理」权限」，不提状态），
 * 而它的写面**不在本包**（issue #6702 的边界 = 只改 `production/remnants`）
 * ⇒ 已开跟踪单 **#6707**，登记待另包修。**归零判据**：该页按状态分流后**必须同批删掉这一条**
 * （不删 ⇒ `staleLedger` 判红，逼着删干净）。
 */
export const LEDGER = ['src/app/(dashboard)/stock-ledger/page.tsx::B']

/**
 * 每条台账的**理由**（与 `LEDGER` 一一对应；守卫核「键 ⇄ 理由」双向都在）。
 * 形态 = `<仓库相对路径>::<形态>`（**不写行号**：活跃文件的裸行号几分钟就失效）。
 */
export const LEDGER_REASONS = /** @type {Record<string, string>} */ ({
  'src/app/(dashboard)/stock-ledger/page.tsx::B':
    '库存明细 / 批次余量两处 catch 一律说「可能是当前岗位没有「商品管理」权限」—— 与 issue #6702 修前形态同族；写面不在本包（只改 production/remnants），已开跟踪单 #6707，登记待另包修',
})

/** 台账冻结基线（只许缩短；`LEDGER.length > LEDGER_FLOOR` ⇒ 红） */
export const LEDGER_FLOOR = 1

/**
 * **正向核**：本包已改对的页面 ⇒ 必须逐字含这些锚（删掉 ⇒ 当场红）。
 * 锚 = 失败锚点（`data-testid`）+ **真重发**的重试出口 + **按状态分流**的判据函数。
 */
export const POSITIVE_ANCHORS = [
  {
    name: '余料台账读失败（issue #6702）',
    file: 'src/app/(dashboard)/production/remnants/page.tsx',
    anchors: [
      'data-testid="remnant-ledger-load-failed"',
      'data-testid="remnant-ledger-retry"',
      'remnantReadErrorCopy',
      // 计数行**逐字**锚（含失败态三元）：修前是 `共 {data?.page?.total ?? 0} 块`
      '<span className="text-xs text-neutral-500">共 {error ? \'—\' : (data?.page?.total ?? 0)} 块</span>',    ],
  },
]

/** 命中清单（台账过滤后）：`unregistered` 非空 ⇒ 判红面 */
export function findOffenders(root) {
  const { files, sites } = copyAttributionSites(root)
  const keys = LEDGER.slice()
  const unregistered = sites.filter((s) => !keys.includes(ledgerKey(s)))
  return { files, sites, unregistered }
}

/** 台账「空转」检测：登记了但**不再命中**的条目（只许缩短 ⇒ 必须删） */
export function staleLedger(root) {
  const { sites } = copyAttributionSites(root)
  const live = new Set(sites.map(ledgerKey))
  return LEDGER.filter((k) => !live.has(k))
}

// ── 命令行（只读）──
if (process.argv[1] && process.argv[1].endsWith('read-failure-copy-attribution-scan.mjs')) {
  const root = process.cwd()
  const { files, sites, unregistered } = findOffenders(root)
  const stale = staleLedger(root)
  console.log(
    `扫描 ${files.length} 个 (dashboard) 文件 · 命中「读失败零值上屏 / 权限归因」${sites.length} 处 · ` +
      `台账豁免 ${LEDGER.length} 条（基线 ${LEDGER_FLOOR}）\n`,
  )
  for (const s of sites) console.log(`  ${unregistered.includes(s) ? '🔴' : '  '} [${s.form}] ${s.file} 第 ${s.line} 行`)
  for (const k of stale) console.log(`  🔴 僵尸台账条目（不再命中，必须删）：${k}`)
  const bad = unregistered.length > 0 || stale.length > 0 || LEDGER.length > LEDGER_FLOOR
  console.log(bad ? '\n🔴 判红：未登记命中 / 僵尸条目 / 台账超基线' : '\n✅ 全部命中均已登记，台账未超基线')
  process.exit(bad ? 1 : 0)
}
