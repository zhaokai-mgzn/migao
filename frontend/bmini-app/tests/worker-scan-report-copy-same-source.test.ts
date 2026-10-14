// case_ids: BM-006, PG-018
/**
 * ⚠️ **本判据是「过渡期守卫」，不是永久契约**（issue #6868 的口径条，2026-10-14 用户逐字
 * 「小程序 = H5，未来 H5 功能都会通过微信发布成小程序，不要独立区分」）。
 *
 * **寿命**：工人面的**唯一实现 = `frontend/worker-h5`**；`frontend/bmini-app` 里的工人面
 * （`src/pages/worker/**`、`src/pages/production/index`）是**重复实现、将分批下架**。
 * 本判据只在**重复实现下架之前**成立 —— 它守的是「同一个产品不能两种说法」这一条过渡期要求
 * （下架前两端措辞必须一致）。**下架该批页面时，同步移除或收缩本文件**（那时两个面里
 * 只剩 H5 一个 ⇒ 本文件的跨面比较失去对象，应退化为 H5 单面的文案判据）。
 *
 * ⇒ 因此本文**不**断言「两个面必须并存」，只断言「并存期间说法一致」。
 *
 * ## 为什么过渡期也要有这条守卫（而不是改完几处就算完）
 *
 * 同一件事今天长在**两个独立 npm 工程**上：小程序工人工作台
 * （`frontend/bmini-app/src/pages/worker/home/index.tsx`）与 H5 扫码页
 * （`frontend/worker-h5/src/render.mjs`）。两边各写一份字面量、**没有任何 import 关系**
 * ⇒ 改一侧漏另一侧时**没有任何东西会红**（同一功能两张脸、两句不同的话）。
 * 这正是 #6638 给工序选择器标题立过的形态（判据在
 * `frontend/bmini-app/tests/production-scan-complete.test.tsx` 的「与 `/w/` 文案同源」一条）
 * —— 本条把**主按钮标题 + 副标题 + 回执 + 登录页标题**按同一形态钉住。
 *
 * ## 判据（每条都能红）
 *
 * | # | 判什么 | 怎么红 |
 * |---|---|---|
 * | ① | 每个面的可见文案逐字等于**冻结串**（主按钮标题 / 副标题 / H5 登录页标题 / 回执三段） | 任一处漂移 ⇒ 红并报出实际串 |
 * | ② | 两个面的**术语一致**：副标题首段逐字相同（`扫一次码 = ` 之后那句话） | 只改一侧 ⇒ 红 |
 * | ③ | 旧口径 `领活` / `领走` 在**两个面的代码面**（剥注释、剔除范围外白名单）零命中 | 回退一处 ⇒ 红 |
 * | ④ | 注入式红证：合成源里把文案改回旧串 ⇒ 判红且报出差异 | 判据不是空断言 |
 * | ⑤ | 注释面**允许**保留历史沿革（`开工 / 领活` 的 #4967 裁定记录） | 守卫不逼人删掉留痕 |
 *
 * ## 边界（照实登记）
 *
 * - 射程 = 上述两个**工人可见**文件；`docs/` / `.github/cases/` / `acceptance/` 是留痕，不在面内。
 *   ⚠️ `frontend/worker-h5/src/machine.mjs`（机台页）的同一句回执**已同批改口径**
 *   （`本套工序都已被领走` ⇒ `本套工序都已报工`），但它的判据在 `worker-h5-machine.test.mjs`
 *   —— 本文件射程只到上述两个文件，不声称覆盖机台页。
 * - 记账口径（issue #4967「扫码 = 开工/领活 ⇒ 记账时点 / `started_at` / `done_at` 语义」）
 *   与端点 / 字段名 / 内部标识 **一字未动** —— 本守卫只判**可见文案**。
 * - 两面的副标题**允许**后半句不同（H5 多一句「扫不了就输码」：那台屏上有输码输入框，小程序主按钮
 *   是导航入口、没有输入框）⇒ 只钉**首段**逐字一致（判据 ②）。
 * - `开工`（报工**动作按钮**文案）**有意不改**：它是 #4967 裁定的语义名（「不是完工」），
 *   且被 `.github/cases/bmini.yml` 的 BM-006 逐字冻结；本守卫**不**对它设判据（见 PR body 的「有意不改」）。
 */
import { readFileSync } from 'fs'
import { join } from 'path'

const REPO_ROOT = join(__dirname, '..', '..', '..')

/** 机台页全文（判据 ③ 与「本套工序都已报工」那一句的面） */
const machine = () => read(WorkerH5Machine)

/** 小程序工人工作台（主按钮 = 一天几十次的那一下） */
const BMiniWorkerHome = 'frontend/bmini-app/src/pages/worker/home/index.tsx'
/** H5 扫码页（扫纸上的部位码后的落点） */
const WorkerH5Render = 'frontend/worker-h5/src/render.mjs'
/** H5 机台页（一体机常驻扫码；同一句「本套工序都已报工」回执） */
const WorkerH5Machine = 'frontend/worker-h5/src/machine.mjs'

function read(rel: string): string {
  return readFileSync(join(REPO_ROOT, rel), 'utf8')
}

/** 剥注释：`//` / `/* *\/` / JSDoc 续行 —— 只留代码面（字符串与 JSX 文本原样留下，行号不变） */
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

/** 剥注释后**仍在代码面**的行（带原行号）—— 判据 ③ 的发现面 */
function nonCommentLines(source: string): { no: number; line: string }[] {
  return stripComments(source)
    .split('\n')
    .map((line, index) => ({ no: index + 1, line: line.trim() }))
    .filter(({ line }) => line.length > 0)
}

/** 副标题的**首段**（`扫一次码 = …` 那句话 = 两侧逐字相同的那一半） */
function headOf(subtitle: string): string {
  return fold(subtitle).split('；')[0]
}

/** 空白折叠（JSX 换行缩进 vs 模板串一行）：只比文案本身，不比排版 */
function fold(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

/** 一个文件里 `旧` ⇒ `新` 的**实参替换**（判据 ④ 的注入原语；先自证注入点存在） */
function replaceArg(source: string, from: string, to: string): string {
  const marker = `'${from}'`
  const at = source.indexOf(marker)
  if (at < 0) throw new Error(`注入点不存在（本红证会空跑 ⇒ 守卫要点名）：${marker}`)
  return source.slice(0, at) + `'${to}'` + source.slice(at + marker.length)
}

// ── 冻结的文案（改这里 = 改判据；两侧必须同批同口径）─────────────────────────

/** 主按钮标题（bmini JSX 文本 / H5 `scanView` 的 `<h1>`，两侧都是裸字面量） */
const TITLE = '扫码报工'
/** 副标题**首段**（`扫一次码 = …` 那句话 —— 两侧逐字相同的那一半） */
const SUBTITLE_HEAD = '扫一次码 = 报一道工序（先报工再生产，做完不用再扫）'
/** 小程序主按钮副标题（整句：主按钮是导航入口，没有输码输入框） */
const BMini_SUBTITLE = `${SUBTITLE_HEAD}`
/** H5 扫码页副标题（整句：那台屏上有输码框 ⇒ 多一句指路） */
const H5_SUBTITLE = `${SUBTITLE_HEAD}；扫不了就输码`
/** H5 登录页标题（同一个「不是商家面」的人话名） */
const LOGIN_TITLE = '工人报工'
/** 完成回执（H5 `doneNotice` 的四段；bmini 报工页回执由服务端 message 承载 —— 本守卫钉 H5 侧） */
const DONE_NOTICE = '已报工'

/** 禁用的**旧措辞**（本刀口径：入口命名与回执一律用「报工」；两个词都禁） */
const BANNED = ['领活', '领走'] as const

/**
 * 两个面里**同名的可见文案**：`新串` ⇒ `旧串` 必须同批同口径（改一侧漏另一侧 ⇒ 红），
 * `anchors` = 各面里**当前口径那一处**的逐字锚（**避开注释**；注入红证按它替换）。
 */
const SAME_SOURCE_STRINGS: readonly {
  from: string
  to: string
  anchors: readonly string[]
}[] = [
  {
    from: '扫码领活',
    to: TITLE,
    anchors: [`<h1 class="wh5-title">${TITLE}</h1>`, `>${TITLE}</Text>`],
  },
  {
    from: '把这道活领走（先领活再生产，做完不用再扫）',
    to: '报一道工序（先报工再生产，做完不用再扫）',
    anchors: [`${H5_SUBTITLE}</p>`, `>${BMini_SUBTITLE}</Text>`],
  },
  {
    from: '工人领活',
    to: LOGIN_TITLE,
    anchors: [`>${LOGIN_TITLE}</h1>`],
  },
] as const

/**
 * 🔴 **本刀范围之外**的可见文案（仍含「领活」二字，**有意不改**）—— 白名单，逐条给理由。
 *
 * 它是**唯一**让「代码面零 `领活`」这条判据可满足的东西：白名单是**冻结**的，
 * 不是「含某字就放行」的宽泛豁免（那种写法实测会把 `扫码领活` 也放过去 = 判据失效）。
 * 将来要清最后两处 ⇒ 改这里 + 改源码（本文件的判据会跟着变红一次，那是**有意**的）。
 */
const OUT_OF_SCOPE_STRINGS: readonly string[] = [
  '本单工序都领完了', // doneNotice 句尾（本刀只改「已领活」前缀，句尾的「领完了」是另一个词）
  '本套工序都领完了', // 同上
  '本部位推断不出待领工序', // 无工序时的说明：说的是**待领状态**，不是入口命名
  '待领', // 本套明细的状态列（工序实例状态标签，供应商服务端 status）
] as const

// ── 判据 ①：每个面的可见文案逐字等于冻结串 ────────────────────────────────────

/**
 * **判定的全部实现**（纯函数 ⇒ 判据可注入合成源自证）。
 *
 * 返回违规清单（空 = 达标）。输入的 `…Source` 是**文件全文**（不是剥离后的），
 * 剥离只发生在旧口径那一条上。
 */
function copyViolations(bmini: string, h5: string, machine: string): string[] {
  const out: string[] = []
  const bminiSub = bmini.match(/worker-home__primary-sub'>([^<]*)<\/Text>/)
  // ⚠️ 必须**限定在 `scanView` 之后**：`loginView` 里也有一个 `<p class="wh5-sub">`
  //（「工号 + PIN 登录…」）—— 不加这个锚会抓到错的那一个（实测踩到，判据具名报错）。
  const scanAt = h5.indexOf('function scanView(')
  const h5Sub =
    scanAt < 0 ? null : h5.slice(scanAt).match(/<p class="wh5-sub">([^<]*)<\/p>/)
  if (!bminiSub) out.push(`${BMiniWorkerHome}：主按钮副标题锚点消失 ⇒ 判据面断了`)
  if (!h5Sub) out.push(`${WorkerH5Render}：scanView 副标题锚点消失（或函数改名）⇒ 判据面断了`)

  if (!bmini.includes(`>${TITLE}</Text>`)) out.push(`${BMiniWorkerHome}：主按钮标题不是「${TITLE}」`)
  if (!h5.includes(`<h1 class="wh5-title">${TITLE}</h1>`)) {
    out.push(`${WorkerH5Render}：扫码页标题不是「${TITLE}」`)
  }
  if (!h5.includes(`<h1 class="wh5-title">${LOGIN_TITLE}</h1>`)) {
    out.push(`${WorkerH5Render}：登录页标题不是「${LOGIN_TITLE}」`)
  }
  if (bminiSub && fold(bminiSub[1]) !== BMini_SUBTITLE) {
    out.push(`${BMiniWorkerHome}：副标题实际「${fold(bminiSub[1])}」≠「${BMini_SUBTITLE}」`)
  }
  if (h5Sub && fold(h5Sub[1]) !== H5_SUBTITLE) {
    out.push(`${WorkerH5Render}：副标题实际「${fold(h5Sub[1])}」≠「${H5_SUBTITLE}」`)
  }
  if (bminiSub && h5Sub && headOf(h5Sub[1]) !== headOf(bminiSub[1])) {
    out.push(
      `两面副标题首段不同源：H5「${headOf(h5Sub[1])}」vs 小程序「${headOf(bminiSub[1])}」`,
    )
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
    [BMiniWorkerHome, bmini],
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

// ── 判据 ①②③：两侧达标（唯一的真语料入口）──────────────────────────────────

describe('工人端「扫码报工」文案跨面同口径（issue #6868 第一刀）', () => {
  it('🔴 两个面的可见文案逐字达标 + 副标题首段同源', () => {
    const violations = copyViolations(read(BMiniWorkerHome), read(WorkerH5Render), machine())
    // 复算：`cd frontend/bmini-app && npx jest tests/worker-scan-report-copy-same-source.test.ts`
    expect(violations).toEqual([])
  })

  // ── 判据 ④：注入式红证（判别力下界）─────────────────────────────────────

  it('④ 注入「H5 标题改回旧串」⇒ 必红（标题 + 旧口径两处同时报出）', () => {
    const h5 = read(WorkerH5Render)
    // ⚠️ 必须钉**标题那一处**：裸 `replace(TITLE, …)` 会先命中**注释**里的同名字样
    //（`render.mjs` 的 #4967 沿革逐字写着「先扫码报工后再真实进行生产」）⇒ 注入变成空跑（实测踩到）。
    const mutated = h5.replace(
      `<h1 class="wh5-title">${TITLE}</h1>`,
      '<h1 class="wh5-title">扫码领活</h1>',
    )
    expect(mutated).not.toBe(h5) // 注入真生效（内容级，不靠 mtime/size）
    const violations = copyViolations(read(BMiniWorkerHome), mutated, machine())
    // 把 H5 标题改回旧串却没被判红 ⇒ 判据是空断言
    expect(violations.length).toBeGreaterThanOrEqual(2)
    expect(violations.join('\n')).toContain('扫码报工') // 具名到期望串
    expect(violations.join('\n')).toContain('领活') // 具名到旧口径
  })

  it('④ 之二 只改一侧副标题 ⇒ 判红到「两面不同源」', () => {
    const bmini = read(BMiniWorkerHome)
    const mutated = bmini.replace(
      `>${BMini_SUBTITLE}</Text>`,
      '>扫一次码 = 把这道活领走（先领活再生产）</Text>',
    )
    expect(mutated).not.toBe(bmini)
    const violations = copyViolations(mutated, read(WorkerH5Render), machine())
    expect(violations.length).toBeGreaterThanOrEqual(1)
    expect(violations.join('\n')).toContain('副标题')
  })

  it('④ 之三 改回登录页标题 `工人领活` ⇒ 判红', () => {
    const h5 = read(WorkerH5Render)
    const mutated = h5.replace(`>${LOGIN_TITLE}</h1>`, '>工人领活</h1>')
    expect(mutated).not.toBe(h5) // 注入真生效（内容级）
    expect(copyViolations(read(BMiniWorkerHome), mutated, machine()).join('\n')).toContain('登录页标题')
  })

  it('④ 之四 两侧同时改回旧串（口径整体回退）⇒ 判红（不只是「不同源」，也可能是「旧词回流」）', () => {
    /** 按**逐字锚**把 `新串` 换回 `旧串`（锚点先自证存在；避开注释里的同名字样） */
    const revert = (source: string, from: string, to: string, anchors: readonly string[]) => {
      for (const anchor of anchors) {
        const hit = source.indexOf(anchor)
        if (hit >= 0) {
          const replaced = anchor.replace(to, from)
          expect(replaced).not.toBe(anchor)
          return source.slice(0, hit) + replaced + source.slice(hit + anchor.length)
        }
      }
      throw new Error(`注入点不存在（本红证会空跑）：${to}`)
    }
    for (const { from, to, anchors } of SAME_SOURCE_STRINGS) {
      const beforeH5 = read(WorkerH5Render)
      const beforeBmini = read(BMiniWorkerHome)
      // 每个面都不许「一个锚都命中不到」：只注入命中的那一面（两面都不命中 ⇒ revert 抛错 ⇒ 红证失败）
      const hitAny = (source: string) => anchors.some((anchor) => source.includes(anchor))
      const h5 = hitAny(beforeH5) ? revert(beforeH5, from, to, anchors) : beforeH5
      const bmini = hitAny(beforeBmini) ? revert(beforeBmini, from, to, anchors) : beforeBmini
      expect(hitAny(beforeH5) || hitAny(beforeBmini)).toBe(true)
      // 具名到哪一处由违反清单给出
      expect(copyViolations(bmini, h5, machine()).join('\n')).not.toBe('')
    }
  })

  // ── 判据 ⑤：注释面允许保留历史沿革（正面对照）────────────────────────────

  it('⑤ 注释面保留历史沿革（不逼人删留痕）', () => {
    const h5 = read(WorkerH5Render)
    // #4967 的语义裁定记录必须还在；沿革里的「领活」按仓库惯例保留
    expect(h5).toContain('issue #4967')
    expect(h5).toContain('领活')
    // 但代码面不得有旧口径
    expect(nonCommentLines(h5).some(({ line }) => line.includes('领活'))).toBe(false)
  })
})
