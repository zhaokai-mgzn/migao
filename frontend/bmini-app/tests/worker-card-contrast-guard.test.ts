// case_ids: BM-034
/**
 * 类级守卫：**卡片形态的类必须有可见边界（`border` 或 `box-shadow`）**（issue #6760）
 *
 * ## 治的形态（2026-10-12 线上读数为证）
 *
 * 工人端 H5 工人工作台（`app.migaozn.com/b/` 登录后那一页）用户报告「页面样式全无」。
 * 线上 390×844 headless Chrome 逐值读数：
 *
 * ```
 * DIV.taro_page            bg=rgb(255,255,255)   ← Taro 运行时注入的页面容器（本仓零规则）
 *   TARO-VIEW.worker-home  bg=rgba(0,0,0,0)
 *     .worker-home__card   bg=rgb(255,255,255) border=0px shadow=none
 *     .worker-home__entry  bg=rgb(255,255,255) border=0px shadow=none
 * BODY                     bg=rgb(245,247,250)   ← 被上面的白底页容器整块盖住
 * ```
 *
 * ⇒ 卡片底色与页面底色**逐值相同**（`255,255,255` = `255,255,255`）、零边框零阴影
 * ⇒ 屏上只剩「白底上一堆裸文本」。`worker-home` 也是 `src/pages/**` 里**唯一**整页
 * 不带自己底色的页面（其余页面根类都有 `background: #f5f7fa` ⇒ 白卡片落在灰底上可见）。
 *
 * 这一族缺陷的共性是：**卡片靠「与页面底色的色差」表达形状**，一旦它落在同色页容器上
 * （H5 的 `.taro_page` 恒为 `#fff`），形状就整个消失 —— 而单测只断言文案 / 跳转时
 * **永远抓不到它**（页面上文字照样渲染，只是没有任何可辨认的卡片/入口视觉）。
 * ⇒ 判据必须落在**形态**上：卡片形态的类，其规则块里必须声明 `border` 或 `box-shadow`。
 *
 * ## 判据
 *
 * | # | 判据 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | 真语料零违规：实测无边界卡片 = 台账登记（两侧都从语料**现算**） | 摘掉任一 `box-shadow`/`border` ⇒ 具名红 |
 * | 2 | 台账只许缩短：每条登记都仍在语料里、且确实仍无边界（不许空口登记） | 修好一处却不删台账条目 ⇒ 红 |
 * | 3 | fail-closed：台账结构坏掉（缺 `why` / `known_exceptions` 非数组 / 条目缺 `class`）⇒ 红 | 删字段「消红」⇒ 红 |
 * | 4 | 具名回归：`worker-home__card` / `worker-home__entry` / `worker-home__gate` 各自有可见边界 | 还原成本单修前形态 ⇒ 红 |
 * | 5 | 判别力自证（**内存变异，不落仓库**）：把 `worker-home__card` 的 `box-shadow` 从语料里摘掉 ⇒ 判红并**具名** | 守卫退化成绿 ⇒ 红 |
 * | 6 | 对照读数：`box-shadow` 换 `border` ⇒ 不红；注释里提到类名 / 假声明 ⇒ 不改变判定；边界只写进注释 ⇒ **仍红** | 守卫被文案喂红 / 注释能伪造边界 ⇒ 红 |
 * | 7 | **`border-radius` 不算可见边界**（白卡片上的圆角在白底页容器里完全不可见） | 谓词退回 `border-\w+` 黑名单 ⇒ 修前语料假绿 ⇒ 红 |
 *
 * ### 判据 8~11：同一族的另一半 —— **白卡片页必须有页面底色**（issue #6760 续，2026-10-13）
 *
 * | # | 判据 | 回归时会怎么红 |
 * |---|---|---|
 * | 8 | 真语料零违规：声明了白底卡片的页面，其**页面根**必须声明**非白**底色（两侧从语料现算） | 摘掉 `worker-home` 的 `background` ⇒ 具名红 |
 * | 9 | 具名回归：`worker-home` 声明了页面底色 + `min-height: 100vh`（内容不足一屏也要铺满） | 还原成修前形态 ⇒ 红 |
 * | 10 | 判别力自证（内存变异）：摘掉底色 / 把底色写成 `#ffffff` / 只把底色写进注释 ⇒ **各自判红** | 守卫退化成绿 ⇒ 红 |
 * | 11 | fail-closed：台账缺 `white_card_pages_without_surface` 或非数组 ⇒ 红 | 删字段「消红」⇒ 红 |
 *
 * **为什么这是独立判据而不是判据 1 的重复**：判据 1 管「卡片有没有边界」，本组管「页面有没有底色」——
 * 两半各自能单独坏掉（卡片有阴影但页面还是白的 ⇒ 卡片仍然"浮"在白上、观感是没做完的页面；
 * 页面有灰底但卡片没边界 ⇒ 卡片形状靠色差勉强可见）。修前语料里**两半同时是坏的**。
 *
 * ## 红证读数（本单实测，可复制；判据 = 本文件）
 *
 * ```
 * cd frontend/bmini-app
 * cp src/pages/worker/home/index.scss /tmp/keep.scss
 * git show origin/main:frontend/bmini-app/src/pages/worker/home/index.scss > src/pages/worker/home/index.scss
 * npx jest tests/worker-card-contrast-guard.test.ts --no-cache --silent
 * # Tests: 3 failed, 9 passed, 12 total（本单实测读数）
 * #   ✕ 真语料零违规：实测无边界卡片 = 台账登记
 * #        Expected(台账) ["metric-card","order-detail__card"]
 * #        Received(实测)  ["metric-card","order-detail__card","worker-home__card","worker-home__entry","worker-home__gate"]
 * #   ✕ worker-home__card / __entry / __gate 都声明了 border 或 box-shadow
 * #        三行 "ok" 全部 false（读数为 false，不是 undefined）
 * #   ✕ 注入前自证坐标：真语料里 worker-home__card 的规则块声明了 box-shadow   Expected true / Received false
 * cp /tmp/keep.scss src/pages/worker/home/index.scss     # 恢复修复
 * npx jest tests/worker-card-contrast-guard.test.ts tests/worker-home-page.test.tsx --silent
 * # Tests: 18 passed, 18 total（guard 12 + worker home 页 6）
 * ```
 *
 * ⚠️ **本守卫第一版曾假绿**（如实登记）：`hasVisibleBoundary` 第一版写成 `border-\w+` 黑名单 ⇒
 * 把 `border-radius` 当成了可见边界 ⇒ 修前语料**不红**（当时实跑 1 failed，只有自证坐标那条会红）。
 * 现已改为白名单（`border` / `border-{top,right,bottom,left}[-{width,style,color}]` / `box-shadow`），
 * 并由「`border-radius` 不算可见边界」一条判据钉住（那条在修前语料上也红）。
 *
 * ## 边界（照实登记）
 *
 * - 判据只看**声明存在**（描边 / 阴影），**判不了观感是否优雅**（`migao-dev-flow` §31.4）。
 * - **不扫全局 `.taro_page`**：改它会改**全站**底色（需全站 15+ 屏读图验收），本单有意不扩面
 *   ⇒ 本单只补「卡片自身可见」这一半。
 * - `src/**\/*.scss` 之外的卡片（如 `src/styles/admin-surfaces.scss` 的 `.admin-card`）不在本守卫射程内。
 * - `metric-card` / `order-detail__card` 按台账**具名例外**保留（它们落在各页自己的灰底上，与底色有色差；
 *   改它们是商家看板的观感验收，本单有意不扩面）—— 每条理由与**重启条件**写在
 *   `tests/worker-card-contrast-ledger.json` 里。
 * - **台账可以是空的**（与 `tests/className-interpolation-ledger.json` 同构）：空 = 真值（此刻真的没有
 *   无边界卡片），**不是**欠账；但对「台账能不能为空」不做断言 —— 真值由「两侧现算相等」承担
 *   （台账乱写 0 条而语料里有 ⇒ 判据 1 当场红），单方面钉「必须为空 / 必须非空」只会制造假红。
 */
import fs from 'fs'
import path from 'path'

const ROOT = path.resolve(__dirname, '..')
const PAGES = path.join(ROOT, 'src', 'pages')
const LEDGER_PATH = path.join(__dirname, 'worker-card-contrast-ledger.json')
const WORKER_HOME = 'src/pages/worker/home/index.scss'

type Ledger = {
  why: string
  known_exceptions: { class: string; reason: string }[]
  /** 判据 8~11：有白卡片却**没有页面底色**的页面（仓库相对路径；只许缩短） */
  white_card_pages_without_surface: string[]
}

/** 规则块：限定名（`&__card` 拼上父选择器） + 本级声明 */
type Rule = { qualified: string[]; decls: string[] }

/**
 * 剥离 `/* *\/` 块注释与 `//` 行注释 —— 注释里出现的类名 / 声明**不算数**
 * （判据 6 的对照读数就靠这一半；不剥 ⇒ 注释能伪造「已有边界」）。
 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
}

/**
 * 逐块抽取规则（递归下降；只做括号配对，不做语义解析）。
 * 限定名 = 整条嵌套路径（`.worker-home` + `&__card` ⇒ `worker-home__card`），
 * 这样唯一化扫描与「摘掉某一块的声明 ⇒ 具名判红」用的是同一份语料。
 */
function extractRules(stripped: string): Rule[] {
  const rules: Rule[] = []

  const parse = (text: string, parentNames: string[]): void => {
    let i = 0
    while (i < text.length) {
      const brace = text.indexOf('{', i)
      if (brace < 0) break
      // 块头 = 上一个 `;`（或 `}`）之后的文本 —— 之前残留的声明不属于选择器
      const head = text
        .slice(Math.max(i, text.lastIndexOf(';', brace) + 1, text.lastIndexOf('}', brace) + 1), brace)
        .trim()
        .replace(/,$/, '')
      const end = matchingBrace(text, brace)
      const body = text.slice(brace + 1, end)

      if (head.startsWith('@')) {
        // 媒体查询 / 变量块：不参与命名，只把内部块按同一父路径继续解析
        parse(body, parentNames)
      } else {
        const parts = head
          .split(',')
          .map((s) => s.replace(/&/g, '').trim())
          .filter(Boolean)
        const qualified = parts.map((p) => `${parentNames.length ? parentNames[parentNames.length - 1] : ''}${p}`)
        if (!body.includes('{')) {
          rules.push({
            qualified,
            decls: body
              .split(';')
              .map((d) => d.trim())
              .filter(Boolean),
          })
        } else {
          rules.push({ qualified, decls: ownDeclarations(body) })
          parse(body, qualified)
        }
      }
      i = end + 1
    }
  }

  parse(stripped, [])
  return rules

  /** 与 `{` 配对的 `}`（找不到 ⇒ 文末，fail-soft） */
  function matchingBrace(text: string, open: number): number {
    let depth = 0
    for (let k = open; k < text.length; k += 1) {
      if (text[k] === '{') depth += 1
      else if (text[k] === '}') {
        depth -= 1
        if (depth === 0) return k
      }
    }
    return text.length
  }

  /** 本级声明 = 第一个嵌套块之前的 `;` 段（嵌套块内部的声明归它自己的规则） */
  function ownDeclarations(body: string): string[] {
    const firstBrace = body.indexOf('{')
    return body
      .slice(0, firstBrace < 0 ? body.length : body.lastIndexOf(';', firstBrace) + 1)
      .split(';')
      .map((d) => d.trim())
      .filter(Boolean)
  }
}

/**
 * 卡片形态的类名（**末段**匹配：`M__card` / `M-card` / `M__entry` / `M__gate`。
 * `M__gate` = 未登录时的引导块，同样是白底卡片形态；`__card-title` 这类文本子元素不算）。
 */
function isCardFormClass(name: string): boolean {
  const last = name.split('__').pop() as string
  return /(?:^|-)(?:card|entry|gate)$/.test(last)
}

/**
 * 本级声明里是否有可见边界。
 *
 * 🔴 **`border-radius` 不算**：白色卡片上的 `border-radius` 在白底页容器里**完全不可见**
 * （本单的缺陷正是「只有 `background` + `border-radius`」）⇒ 必须只认**描边**与**阴影**：
 * `border` / `border-{top,right,bottom,left}[-{width,style,color}]` 与 `box-shadow`。
 * （白名单而非 `border-\w+` 黑名单：后者会把 `border-radius` / `border-image` 误判成边界 ——
 * 本守卫的第一版就是这么写错的，修前语料因此**假绿**，红证由下表「border-radius 不算」一条钉住。）
 */
function hasVisibleBoundary(decls: string[]): boolean {
  return decls.some((d) =>
    /^(?:box-shadow|border(?:-(?:top|right|bottom|left))?(?:-(?:width|style|color))?)\s*:/.test(d),
  )
}

/** 一次扫描的结果：每个卡片形态的类 → 是否有可见边界（同一个类的多个块：只有全都声明了边界才算绿） */
function scanCardClasses(source: string): Map<string, boolean> {
  const out = new Map<string, boolean>()
  for (const rule of extractRules(stripComments(source))) {
    for (const qualified of rule.qualified) {
      const last = qualified.split(' ').pop() as string
      if (!isCardFormClass(last)) continue
      // 这一段的类名（去掉 `:` 后面的伪类 / 状态后缀）
      const bare = last.replace(/\./g, '').split(':')[0]
      const ok = hasVisibleBoundary(rule.decls)
      // 同一个类的多个块：只有全都声明了边界才算绿（`Map.get` 对 `false` 也返回假值 ⇒ 不能用 `?? true`）
      out.set(bare, out.has(bare) ? (out.get(bare) as boolean) && ok : ok)
    }
  }
  return out
}

function scssFiles(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) scssFiles(p, out)
    else if (e.name.endsWith('.scss')) out.push(p)
  }
  return out
}

/** 全页语料里**没有**可见边界的卡片形态类（排序后返回，比较用） */
function findCardClassesWithoutBoundary(): string[] {
  const bad: string[] = []
  for (const file of scssFiles(PAGES).sort()) {
    const rules = scanCardClasses(fs.readFileSync(file, 'utf-8'))
    for (const [name, ok] of rules) if (!ok) bad.push(name)
  }
  return Array.from(new Set(bad)).sort()
}

const ledger: Ledger = JSON.parse(fs.readFileSync(LEDGER_PATH, 'utf-8'))
const offenders = findCardClassesWithoutBoundary()
const workerHomeSource = fs.readFileSync(path.join(ROOT, WORKER_HOME), 'utf-8')

describe('类级守卫：卡片形态的类必须有可见边界（issue #6760 判据 1/2/3）', () => {
  it('真语料零违规：实测无边界卡片 = 台账登记（两侧都从语料现算；空台账也必须两侧同空）', () => {
    // 红证（本单实测，4 failed / 8 passed）：worker home 改回修前形态时，offenders 比台账
    // 多出 `worker-home__card` / `worker-home__entry` / `worker-home__gate` 三条 ⇒ 判红。
    // 台账写死 0 条**不是**免检：两侧都由本文件现算，offenders 一多出来就不等 ⇒ 未登记即红。
    expect(offenders).toEqual(ledger.known_exceptions.map((e) => e.class))
  })

  it('台账只许缩短：每条都仍在语料里、且确实仍无边界（不许空口登记）', () => {
    for (const entry of ledger.known_exceptions) {
      expect({ cls: entry.class, stillOffender: offenders.includes(entry.class) }).toEqual({
        cls: entry.class,
        stillOffender: true,
      })
    }
  })

  it('🔴 fail-closed：台账结构坏掉（缺 `why` / `known_exceptions` / 条数读不出来）⇒ 红', () => {
    // 清空 / 删字段「消红」都会在这里露出：结构不对 ⇒ 红（不是「空 = 通过」）
    expect({ hasWhy: typeof ledger.why === 'string' && ledger.why.length > 0 }).toEqual({
      hasWhy: true,
    })
    expect(Array.isArray(ledger.known_exceptions)).toBe(true)
    expect(ledger.known_exceptions.every((e) => typeof e.class === 'string')).toBe(true)
  })

  it('台账每条必须带具名理由（未登记即红，登记了不许空口）', () => {
    const blank = ledger.known_exceptions.filter((e) => !e.reason || e.reason.trim().length < 10)
    expect(blank).toEqual([])
  })
})

describe('🔴 具名回归：工人工作台三块白底卡各自有可见边界（issue #6760 判据 4）', () => {
  it('worker-home__card / __entry / __gate 都声明了 border 或 box-shadow', () => {
    const scanned = scanCardClasses(workerHomeSource)
    const readout = ['worker-home__card', 'worker-home__entry', 'worker-home__gate'].map((name) => ({
      name,
      ok: scanned.get(name),
    }))
    expect(readout).toEqual([
      { name: 'worker-home__card', ok: true },
      { name: 'worker-home__entry', ok: true },
      { name: 'worker-home__gate', ok: true },
    ])
  })

  it('卡片形态的识别面覆盖 `*__card` / `*-card` / `__entry` / `__gate` 四种命名', () => {
    expect(isCardFormClass('worker-home__card')).toBe(true)
    expect(isCardFormClass('metric-card')).toBe(true)
    expect(isCardFormClass('worker-home__entry')).toBe(true)
    expect(isCardFormClass('worker-home__gate')).toBe(true)
    // 文本子元素不是卡片容器（否则「卡片标题」这种元素会被误判）
    expect(isCardFormClass('worker-home__card-title')).toBe(false)
    expect(isCardFormClass('worker-home__entry-text')).toBe(false)
    expect(isCardFormClass('worker-home__gate-text')).toBe(false)
  })
})

describe('判别力自证（issue #6760 判据 5/6，内存变异 + 对照读数）', () => {
  /** 变异注入用的最小语料（与 `src/pages/worker/home/index.scss` 的卡片块同形） */
  const MINIMAL = ['.worker-home {', '  &__card {', '    background: #ffffff;', '    box-shadow: 0 2px 8px rgba(10, 37, 64, 0.06);', '  }', '}', ''].join(
    '\n',
  )

  /** 语料里所有 **卡片形态** 的规则（限定名 + 本级声明）—— 变异前后各取一次做对照 */
  function cardRulesOf(source: string) {
    return extractRules(stripComments(source)).filter((r) =>
      r.qualified.some((q) => isCardFormClass(q.split(' ').pop() as string)),
    )
  }

  it('注入前自证坐标：真语料里 worker-home__card 的规则块声明了 box-shadow', () => {
    // 变异注入前先自证坐标 = 这一条：目标块在语料里、且它的声明里确实有 `box-shadow`
    const card = cardRulesOf(workerHomeSource).find((r) =>
      r.qualified.some((q) => q.replace(/\./g, '') === 'worker-home__card'),
    )
    expect(card?.decls.some((d) => d.startsWith('box-shadow:'))).toBe(true)
  })

  it('把 `worker-home__card` 的 `box-shadow` 从语料里摘掉 ⇒ 判红并具名（内存变异，不落仓库）', () => {
    const mutated = MINIMAL.replace(/^\s*box-shadow:[^;]*;\s*$/gm, '')
    // 变异真生效（不是空跑）：卡片规则的声明读数确实变了
    expect(cardRulesOf(mutated)).not.toEqual(cardRulesOf(MINIMAL))
    expect(findCardClassesWithoutBoundaryFrom(mutated)).toContain('worker-home__card')
    // 未变异时同一份语料**不红**（反向对照：红是变异带来的，不是函数恒红）
    expect(findCardClassesWithoutBoundaryFrom(MINIMAL)).toEqual([])
  })

  it('对照读数：把 `box-shadow` 换成 `border` ⇒ 不红（border 是等价出口）', () => {
    const mutated = MINIMAL.replace(/^\s*box-shadow:[^;]*;\s*$/gm, '    border: 1px solid #eaeef3;')
    expect(cardRulesOf(mutated)).not.toEqual(cardRulesOf(MINIMAL))
    expect(findCardClassesWithoutBoundaryFrom(mutated)).toEqual([])
  })

  it('对照读数：注释里提到类名 + 假声明 ⇒ 不改变判定（只在注释里加东西不算改动）', () => {
    const commented = MINIMAL.replace(
      '.worker-home {',
      '// worker-home__card 已经有 box-shadow 了\n/* .worker-home__card { box-shadow: none } */\n.worker-home {',
    )
    expect(commented).not.toBe(MINIMAL)
    expect(findCardClassesWithoutBoundaryFrom(commented)).toEqual(
      findCardClassesWithoutBoundaryFrom(MINIMAL),
    )
  })

  it('对照读数：把边界只写进注释 ⇒ 仍判红（注释不算声明）', () => {
    const shadowOnlyInComment = MINIMAL.replace(
      /^(\s*)box-shadow:[^;]*;\s*$/gm,
      '$1// box-shadow: 0 2px 8px rgba(10, 37, 64, 0.06);',
    )
    expect(shadowOnlyInComment).not.toBe(MINIMAL)
    expect(findCardClassesWithoutBoundaryFrom(shadowOnlyInComment)).toContain('worker-home__card')
  })

  it('🔴 `border-radius` 不算可见边界（本守卫第一版曾因此假绿）', () => {
    // 本单修前的真实形态：只有背景 + 圆角 ⇒ 落白底页容器上完全不可见
    expect(hasVisibleBoundary(['background: #ffffff', 'border-radius: 12px'])).toBe(false)
    expect(findCardClassesWithoutBoundaryFrom(MINIMAL.replace(/border-radius|box-shadow/g, 'x'))).toContain(
      'worker-home__card',
    )
    // 等价出口仍然算
    expect(hasVisibleBoundary(['border: 1px solid #eaeef3'])).toBe(true)
    expect(hasVisibleBoundary(['border-bottom: 1px solid #eaeef3'])).toBe(true)
    expect(hasVisibleBoundary(['box-shadow: 0 1px 4px rgba(10, 37, 64, 0.04)'])).toBe(true)
  })

  /** 把内存语料当唯一输入扫一遍（与真语料同一份 `scanCardClasses`，不另写一套） */
  function findCardClassesWithoutBoundaryFrom(source: string): string[] {
    const bad: string[] = []
    for (const [name, ok] of scanCardClasses(source)) if (!ok) bad.push(name)
    return bad.sort()
  }
})

// ══════════════════════════════════════════════════════════════════════════════
// 判据 8~11：白卡片页必须有页面底色（issue #6760 的另一半，2026-10-13）
// ══════════════════════════════════════════════════════════════════════════════
//
// 病灶：卡片补了可见边界之后，若**页面自己没有底色**，白卡仍落在 Taro H5 恒白的 `.taro_page` 上
// —— 与「卡片没有边界」是同一现场的两半。本仓「有卡片的页面」一律自带灰底
//（`dashboard` / `chat` / `profile` / `production` / `sessions-detail` 的页面根都声明 `#f5f7fa`；
// 工人端另三页走共享 `.admin-surface` 同款）⇒ 判据落在**页面根**上。
//
// 射程（照实登记）：只看 `src/pages/**/*.scss` **本文件内**的声明 —— 走共享样式
//（`src/styles/admin-surfaces.scss::.admin-surface` / `.admin-card`）的页面不在射程内（同判据 1 的边界）。

/** 页面根类名 = 该文件**第一条**规则的限定名（去掉前导 `.` 与伪类）。`null` = 一条规则都没有。 */
function pageRootOf(source: string): string | null {
  const first = extractRules(stripComments(source))[0]
  if (!first || !first.qualified.length) return null
  const last = first.qualified[0].split(' ').pop() as string
  return last.replace(/\./g, '').split(':')[0] || null
}

/** 该文件里声明了**白底**（`#fff` / `#ffffff` / `white`）的卡片形态类（排序去重）。 */
function whiteCardClassesOf(source: string): string[] {
  const found: string[] = []
  for (const rule of extractRules(stripComments(source))) {
    for (const qualified of rule.qualified) {
      const last = qualified.split(' ').pop() as string
      if (!isCardFormClass(last)) continue
      const white = rule.decls.some((d) => /^background(?:-color)?\s*:\s*(?:#fff(?:fff)?|white)$/i.test(d))
      if (white) found.push(last.replace(/\./g, '').split(':')[0])
    }
  }
  return Array.from(new Set(found)).sort()
}

/** 页面根是否声明了**非白**底色（`background` / `background-color`，且不是白 / 透明 / 无）。 */
function hasNonWhiteSurface(source: string, rootClass: string): boolean {
  for (const rule of extractRules(stripComments(source))) {
    for (const qualified of rule.qualified) {
      const last = qualified.split(' ').pop() as string
      if (last.replace(/\./g, '').split(':')[0] !== rootClass) continue
      const bad = /^background(?:-color)?\s*:\s*(?:#fff(?:fff)?|white|transparent|none|rgba?\(\s*255\s*,\s*255\s*,\s*255)/i
      if (rule.decls.some((d) => /^background(?:-color)?\s*:/.test(d) && !bad.test(d))) return true
    }
  }
  return false
}

/** 一个页面源码是不是「有白卡片、页面根却没有非白底色」（纯函数 ⇒ 可对内存变异跑）。 */
function whiteCardsOnWhiteSurface(source: string): boolean {
  if (!whiteCardClassesOf(source).length) return false
  const root = pageRootOf(source)
  return !root || !hasNonWhiteSurface(source, root)
}

/** 全页语料里「白卡片落在白底页面上」的页面（仓库相对路径，排序） */
function findPagesWithWhiteCardsOnWhiteSurface(): string[] {
  const bad: string[] = []
  for (const file of scssFiles(PAGES).sort()) {
    if (whiteCardsOnWhiteSurface(fs.readFileSync(file, 'utf-8'))) bad.push(path.relative(ROOT, file))
  }
  return bad.sort()
}

const whiteSurfaceOffenders = findPagesWithWhiteCardsOnWhiteSurface()

describe('类级守卫：白卡片页必须有页面底色（issue #6760 的另一半，判据 8~11）', () => {
  it('真语料零违规：白卡片页的页面根都声明了非白底色（两侧从语料现算；空台账也必须两侧同空）', () => {
    // 红证（本单实测）：把 worker home 改回修前形态（页面根只有 `padding`）⇒
    // whiteSurfaceOffenders 多出 `src/pages/worker/home/index.scss` ⇒ 与空台账不等 ⇒ 判红。
    expect(whiteSurfaceOffenders).toEqual(ledger.white_card_pages_without_surface)
  })

  it('具名回归：worker-home 声明了页面底色 + min-height: 100vh（内容不足一屏也要铺满）', () => {
    expect(pageRootOf(workerHomeSource)).toBe('worker-home')
    expect(hasNonWhiteSurface(workerHomeSource, 'worker-home')).toBe(true)
    expect(/min-height\s*:\s*100vh/.test(stripComments(workerHomeSource))).toBe(true)
  })

  it('🔴 判别力自证：摘掉底色 / 把底色写成白 / 只把底色写进注释 ⇒ 各自判红（内存变异，不落仓库）', () => {
    const noSurface = workerHomeSource.replace(/^\s*background:\s*#f5f7fa;\s*$/m, '')
    expect(noSurface).not.toBe(workerHomeSource) // 注入先自证生效
    expect(whiteCardsOnWhiteSurface(noSurface)).toBe(true)

    const whiteSurface = workerHomeSource.replace('background: #f5f7fa;', 'background: #ffffff;')
    expect(whiteSurface).not.toBe(workerHomeSource)
    expect(whiteCardsOnWhiteSurface(whiteSurface)).toBe(true) // 写白 = 没写

    const commentOnly = workerHomeSource.replace(/^\s*background:\s*#f5f7fa;\s*$/m, '  // background: #f5f7fa;')
    expect(commentOnly).not.toBe(workerHomeSource)
    expect(whiteCardsOnWhiteSurface(commentOnly)).toBe(true) // 注释不算声明
  })

  it('对照读数：没有白卡片的表单页不受本判据波及（不误伤）', () => {
    const loginForm = fs.readFileSync(path.join(PAGES, 'auth', 'login', 'index.scss'), 'utf-8')
    expect(whiteCardClassesOf(loginForm)).toEqual([])
    expect(whiteCardsOnWhiteSurface(loginForm)).toBe(false)
  })

  it('🔴 fail-closed：台账缺 `white_card_pages_without_surface` / 非数组 ⇒ 红', () => {
    expect(Array.isArray(ledger.white_card_pages_without_surface)).toBe(true)
    expect(ledger.white_card_pages_without_surface.every((p) => typeof p === 'string')).toBe(true)
  })
})
