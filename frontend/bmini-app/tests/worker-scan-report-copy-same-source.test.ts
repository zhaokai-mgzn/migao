// case_ids: BM-006, PG-018
/**
 * 工人端「扫码报工」**H5 单面**文案判据（issue #6868 第一刀；2026-10-14 收缩）。
 *
 * ## 为什么从「跨面同源」收缩成「单面」
 *
 * 原判据是**过渡期守卫**：小程序工人工作台（`frontend/bmini-app/src/pages/worker/home/index.tsx`）
 * 与 H5 扫码页（`frontend/worker-h5/src/render.mjs`）各写一份字面量、**没有任何 import 关系**
 * ⇒ 改一侧漏另一侧时没有任何东西会红，故当时**逐字钉住两面**。文件头原文已写明它的**寿命**：
 * 「下架该批页面时，同步移除或收缩本文件（那时两个面里只剩 H5 一个 ⇒ 本文件的跨面比较失去对象，
 * 应退化为 H5 单面的文案判据）」。
 *
 * 🔴 2026-10-14（issue #6868 实现包 D1）兑现了这条：用户逐字「**没有用处的页面就直接删了**」⇒
 * 小程序侧报工页（`frontend/bmini-app/src/pages/production/index/**`）整页删除、工人工作台的
 * 「扫码报工」主按钮一并删除（删页后它是死链）⇒ `frontend/worker-h5` 是工人报工的**唯一实现**。
 * 本文件据此**收缩为 H5 单面**：删掉跨面比较（`SAME_SOURCE_STRINGS` / 小程序副标题锚 /「两面同源」
 * 那条判据）与「只改一侧 ⇒ 红」的注入红证；**保留** H5 的标题 / 副标题 / 回执逐字断言、旧口径
 * （`领活` / `领走`）代码面零命中、以及注入式红证（改回旧串 ⇒ 红）。
 *
 * ## 判据（每条都能红）
 *
 * | # | 判什么 | 怎么红 |
 * |---|---|---|
 * | ① | H5 的可见文案逐字等于**冻结串**（扫码页标题 / 副标题 / 登录页标题 / 报工回执三段 / 机台页回执） | 任一处漂移 ⇒ 红并报出实际串 |
 * | ② | 旧口径 `领活` / `领走` 在 H5 两个文件的**代码面**（剥注释、剔除范围外白名单）零命中 | 回退一处 ⇒ 红 |
 * | ③ | 注入式红证：把标题 / 副标题 / 登录页标题改回旧串 ⇒ 判红且报出差异 | 判据不是空断言 |
 * | ④ | 注释面**允许**保留历史沿革（`开工 / 领活` 的 #4967 裁定记录） | 守卫不逼人删掉留痕 |
 *
 * ## 边界（照实登记）
 *
 * - 射程 = `frontend/worker-h5` 的两个工人可见文件（`render.mjs` / `machine.mjs`）；
 *   `docs/` / `.github/cases/` / `acceptance/` 是留痕，不在面内。
 * - 记账口径（issue #4967「扫码 = 开工/领活 ⇒ 记账时点 / `started_at` / `done_at` 语义」）
 *   与端点 / 字段名 / 内部标识 **一字未动** —— 本守卫只判**可见文案**。
 * - `开工`（报工**动作按钮**文案）**有意不改**：它是 #4967 裁定的语义名（「不是完工」），
 *   且被 `.github/cases/bmini.yml` 的 BM-006 逐字冻结；本守卫**不**对它设判据。
 * - **小程序侧那一页的删除另有判据**（不在本文件）：`frontend/bmini-app/tests/worker-home-page.test.tsx`
 *   （工人工作台不再渲染「扫码报工」主按钮）+ `frontend/bmini-app/tests/page-entry-reachability.test.ts`
 *   （入口台账里没有指向该页的登记，且该页已不在 `app.config.ts` 的 pages 里）。
 */
import { readFileSync } from 'fs'
import { join } from 'path'

const REPO_ROOT = join(__dirname, '..', '..', '..')

/** H5 扫码页（扫纸上的部位码后的落点） */
const WorkerH5Render = 'frontend/worker-h5/src/render.mjs'
/** H5 机台页（一体机常驻扫码；同一句「本套工序都已报工」回执） */
const WorkerH5Machine = 'frontend/worker-h5/src/machine.mjs'

function read(rel: string): string {
  return readFileSync(join(REPO_ROOT, rel), 'utf8')
}

/** 剥注释：`//` / `/* *\/` / JSDoc 续行 —— 只留代码面（字符串与模板串文本原样留下，行号不变） */
function stripComments(source: string): string {
  return source
    .split('\n')
    .map((line) => {
      const trimmed = line.trimStart()
      if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) return ''
      return line
    })
    .join('\n')
}

/** 剥注释后**仍在代码面**的行（带原行号）—— 判据 ② 的发现面 */
function nonCommentLines(source: string): { no: number; line: string }[] {
  return stripComments(source)
    .split('\n')
    .map((line, index) => ({ no: index + 1, line: line.trim() }))
    .filter(({ line }) => line.length > 0)
}

/** 空白折叠（模板串换行缩进 vs 一行）：只比文案本身，不比排版 */
function fold(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

// ── 冻结的文案（改这里 = 改判据）─────────────────────────────────────────────

/** 扫码页标题（H5 `scanView` 的 `<h1>`，裸字面量） */
const TITLE = '扫码报工'
/** 副标题（`扫一次码 = …` 那句话；H5 那台屏上有输码框 ⇒ 多一句指路） */
const H5_SUBTITLE = '扫一次码 = 报一道工序（先报工再生产，做完不用再扫）；扫不了就输码'
/** 登录页标题（同一个「不是商家面」的人话名） */
const LOGIN_TITLE = '工人报工'
/** 报工回执（H5 `doneNotice` 的四段） */
const DONE_NOTICE = '已报工'

/** 禁用的**旧措辞**（本刀口径：入口命名与回执一律用「报工」；两个词都禁） */
const BANNED = ['领活', '领走'] as const

/**
 * **本刀范围之外**的可见文案（仍含「领活」二字，**有意不改**）—— 白名单，逐条给理由。
 *
 * 它是**唯一**让「代码面零 `领活`」这条判据可满足的东西：白名单是**冻结**的，不是「含某字就放行」
 * 的宽泛豁免（那种写法实测会把 `扫码领活` 也放过去 = 判据失效）。
 */
const OUT_OF_SCOPE_STRINGS: readonly string[] = [
  '本单工序都领完了', // doneNotice 句尾（本刀只改「已领活」前缀，句尾的「领完了」是另一个词）
  '本套工序都领完了', // 同上
  '本部位推断不出待领工序', // 无工序时的说明：说的是**待领状态**，不是入口命名
  '待领', // 本套明细的状态列（工序实例状态标签，供应商服务端 status）
] as const

// ── 判据 ①：H5 的可见文案逐字等于冻结串 ───────────────────────────────────────

/**
 * **判定的全部实现**（纯函数 ⇒ 判据可注入合成源自证）。
 *
 * 返回违规清单（空 = 达标）。输入的 `…Source` 是**文件全文**（不是剥离后的），
 * 剥离只发生在旧口径那一条上。
 */
function copyViolations(h5: string, machine: string): string[] {
  const out: string[] = []
  // ⚠️ 必须**限定在 `scanView` 之后**：`loginView` 里也有一个 `<p class="wh5-sub">`
  //（「工号 + PIN 登录…」）—— 不加这个锚会抓到错的那一个（实测踩到，判据具名报错）。
  const scanAt = h5.indexOf('function scanView(')
  const h5Sub = scanAt < 0 ? null : h5.slice(scanAt).match(/<p class="wh5-sub">([^<]*)<\/p>/)
  if (!h5Sub) out.push(`${WorkerH5Render}：scanView 副标题锚点消失（或函数改名）⇒ 判据面断了`)

  if (!h5.includes(`<h1 class="wh5-title">${TITLE}</h1>`)) {
    out.push(`${WorkerH5Render}：扫码页标题不是「${TITLE}」`)
  }
  if (!h5.includes(`<h1 class="wh5-title">${LOGIN_TITLE}</h1>`)) {
    out.push(`${WorkerH5Render}：登录页标题不是「${LOGIN_TITLE}」`)
  }
  if (h5Sub && fold(h5Sub[1]) !== H5_SUBTITLE) {
    out.push(`${WorkerH5Render}：副标题实际「${fold(h5Sub[1])}」≠「${H5_SUBTITLE}」`)
  }
  for (const notice of [DONE_NOTICE, `${DONE_NOTICE} · 下一道：`, `${DONE_NOTICE} · 本套工序都领完了`]) {
    if (!h5.includes(notice)) out.push(`${WorkerH5Render}：回执缺「${notice}」（旧口径回流？）`)
  }
  // 机台页同一句回执（工人可见面）：本套做满时说的是「本套工序都已报工」
  if (!machine.includes('本套工序都已报工')) {
    out.push(`${WorkerH5Machine}：本套做满的回执不是「本套工序都已报工」（旧口径回流？）`)
  }
  // 旧措辞零命中（**剥注释**：沿革留痕不算）。先摘掉**显式登记的本刀范围外**文案，
  // 再看剩下的代码面里还有没有 `领活` / `领走`（摘而不是「整行放行」⇒ 同一行里的真违规照样被抓）。
  for (const [rel, source] of [
    [WorkerH5Render, h5],
    [WorkerH5Machine, machine],
  ] as const) {
    for (const { no, line } of nonCommentLines(source)) {
      let rest = line
      for (const allowed of OUT_OF_SCOPE_STRINGS) rest = rest.split(allowed).join('')
      if (BANNED.some((term) => rest.includes(term))) {
        out.push(`${rel}:${no} 可见文案仍是旧口径：${line}`)
      }
    }
  }
  return out
}

describe('工人端「扫码报工」文案（H5 单面，issue #6868；2026-10-14 由跨面守卫收缩）', () => {
  it('🔴 H5 的可见文案逐字达标（扫码页标题 / 副标题 / 登录页标题 / 报工回执 / 机台页回执）', () => {
    const violations = copyViolations(read(WorkerH5Render), read(WorkerH5Machine))
    // 复算：`cd frontend/bmini-app && npx jest tests/worker-scan-report-copy-same-source.test.ts`
    expect(violations).toEqual([])
  })

  // ── 判据 ③：注入式红证（判别力下界）─────────────────────────────────────

  it('③ 注入「H5 标题改回旧串」⇒ 必红（标题 + 旧口径两处同时报出）', () => {
    const h5 = read(WorkerH5Render)
    // ⚠️ 必须钉**标题那一处**：裸 `replace(TITLE, …)` 会先命中**注释**里的同名字样
    //（`render.mjs` 的 #4967 沿革逐字写着「先扫码报工后再真实进行生产」）⇒ 注入变成空跑（实测踩到）。
    const mutated = h5.replace(
      `<h1 class="wh5-title">${TITLE}</h1>`,
      '<h1 class="wh5-title">扫码领活</h1>',
    )
    expect(mutated).not.toBe(h5) // 注入真生效（内容级，不靠 mtime/size）
    const violations = copyViolations(mutated, read(WorkerH5Machine))
    // 把 H5 标题改回旧串却没被判红 ⇒ 判据是空断言
    expect(violations.length).toBeGreaterThanOrEqual(2)
    expect(violations.join('\n')).toContain('扫码报工') // 具名到期望串
    expect(violations.join('\n')).toContain('领活') // 具名到旧口径
  })

  it('③ 之二 副标题改回旧串（口径回退）⇒ 判红', () => {
    const h5 = read(WorkerH5Render)
    const scanAt = h5.indexOf('function scanView(')
    const hit = h5.slice(scanAt).match(/<p class="wh5-sub">([^<]*)<\/p>/)
    if (!hit) throw new Error('副标题锚点不存在（本红证会空跑 ⇒ 判据要点名）')
    const mutated = h5.replace(hit[1], '扫一次码 = 把这道活领走（先领活再生产，做完不用再扫）')
    expect(mutated).not.toBe(h5)
    const violations = copyViolations(mutated, read(WorkerH5Machine))
    expect(violations.length).toBeGreaterThanOrEqual(1)
    expect(violations.join('\n')).toContain('副标题')
  })

  it('③ 之三 改回登录页标题 `工人领活` ⇒ 判红', () => {
    const h5 = read(WorkerH5Render)
    const mutated = h5.replace(`>${LOGIN_TITLE}</h1>`, '>工人领活</h1>')
    expect(mutated).not.toBe(h5) // 注入真生效（内容级）
    expect(copyViolations(mutated, read(WorkerH5Machine)).join('\n')).toContain('登录页标题')
  })

  // ── 判据 ④：注释面允许保留历史沿革（正面对照）────────────────────────────

  it('④ 注释面保留历史沿革（不逼人删留痕）', () => {
    const h5 = read(WorkerH5Render)
    // #4967 的语义裁定记录必须还在；沿革里的「领活」按仓库惯例保留
    expect(h5).toContain('issue #4967')
    expect(h5).toContain('领活')
    // 但代码面不得有旧口径
    expect(nonCommentLines(h5).some(({ line }) => line.includes('领活'))).toBe(false)
  })
})
