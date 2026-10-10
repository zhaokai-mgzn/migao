// case_ids: BM-030, BM-047, BM-049
/**
 * 类级元守卫：**挂了底栏的页面必须按底栏条高留位**（issue #6666 判据 1）
 *
 * ## 治的形态（真机实测，390×844，线上 `app.migaozn.com/b/`）
 *
 * `MerchantTabBar` 是 `position: fixed; bottom: 0` 的**浮层**，它**不占流内空间** ⇒
 * 挂它的页面不预留就会被压住。实测：数据页滚到底后最靠下的**叶子文本** bottom = **799.5px**，
 * 而底栏 `top = 794px` ⇒ 该行落在底栏之下（按 iPhone 安全区 34px 推算，整行都看不见）。
 *
 * 🔴 **为什么这条判据到今天才补**：既有判据（`tests/tabbar-layout.test.ts` / `tests/merchant-tabbar.test.tsx`
 * / BM-031 / BM-049）只钉**条自身**与**聊天页**，**从不断言「页面内容不被条压住」** ⇒
 * 「新加一个 tab 页忘了留位」永远不会有东西变红。本文件补这一半。
 *
 * ## 判据
 *
 * | # | 判据 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | **未登记即红**：现取「谁 import 了 MerchantTabBar」，每个页面都必须在台账里 | 新加 tab 页不留位/不登记 ⇒ 具名红 |
 * | 2 | **登记必须兑现**：台账每条 `root_class` + `scss` 都要真存在，且该根块含 `box-sizing: border-box` 与 `padding-bottom: calc(50PX + env(safe-area-inset-bottom))` | 撤掉预留（注入 `24px`）⇒ 具名红 |
 * | 3 | **台账只许缩短**：台账里多的条目（页面已不挂底栏）⇒ 红 | 留陈旧条目 ⇒ 红 |
 * | 4 | **空台账 fail-closed**：台账为空（或被清空「消红」）⇒ 红 | 清空台账 ⇒ 红 |
 * | 5 | **单一真值**：底栏那一侧的条高算式与页面预留算式同源（`MerchantTabBar.scss` 逐字） | 改一边不改另一边 ⇒ 红 |
 * | 6 | **判别力自证**：五种坏形态在内存里各自判红，且**合法形态不误报** | 守卫退化成绿 ⇒ 红 |
 *
 * ## 边界（照实登记，§19.1）
 *
 * 本文件是**文本/形态级**：它判「预留算式在不在位」，判不了「真机上到底压没压住」——
 * 后者是几何读数，承载体 = `acceptance/2026-10-09-bmini-three-fixes/bmini-geometry-probe.mjs`
 * 的 `tabbarInset`（滚到底后最靠下叶子文本 bottom vs 底栏 top），读数记在
 * `acceptance/2026-10-10-bmini-6666/README.md`。**不要**把本文件读成「布局已被几何验过」。
 */
import fs from 'fs'
import path from 'path'

const ROOT = path.resolve(__dirname, '..')
const SRC = path.join(ROOT, 'src')
const LEDGER_PATH = path.join(__dirname, 'tabbar-content-inset-ledger.json')
const BAR_SCSS = path.join(SRC, 'components', 'MerchantTabBar.scss')

/** 底栏条高算式（页面预留必须与它**同源同值**） */
const BAR_HEIGHT = /height:\s*calc\(\s*50PX\s*\+\s*env\(safe-area-inset-bottom\)\s*\)\s*;/
const RESERVE = /padding-bottom:\s*calc\(\s*50PX\s*\+\s*env\(safe-area-inset-bottom\)\s*\)\s*;/
const BORDER_BOX = /box-sizing:\s*border-box\s*;/

type LedgerEntry = { root_class: string; scss: string }
type Ledger = { pages: Record<string, LedgerEntry> }

const rel = (p: string) => path.relative(ROOT, p).split(path.sep).join('/')

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p, out)
    else out.push(p)
  }
  return out
}

/** 剔注释后的 SCSS **代码**（注释里提到某条规则不算落实） */
function scssCode(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((line) => !line.trim().startsWith('//'))
    .join('\n')
}

/** 取 `.cls { … }` 的**整块**（含嵌套，按花括号配平收尾） */
function rootBlock(code: string, cls: string): string {
  const m = new RegExp(`\\.${cls}\\s*\\{`).exec(code)
  if (!m) return ''
  let depth = 0
  for (let i = m.index + m[0].length - 1; i < code.length; i += 1) {
    if (code[i] === '{') depth += 1
    else if (code[i] === '}') {
      depth -= 1
      if (depth === 0) return code.slice(m.index, i + 1)
    }
  }
  return ''
}

/** 现取「谁挂了底栏」：`import MerchantTabBar from` 出现在哪个页面文件里 */
function discoverMountingPages(files: string[] = walk(SRC)): string[] {
  return files
    .filter((f) => f.endsWith('.tsx'))
    .filter((f) => /import\s+MerchantTabBar\s+from/.test(fs.readFileSync(f, 'utf-8')))
    .map(rel)
    .sort()
}

const readFile = (p: string) => fs.readFileSync(path.join(ROOT, p), 'utf-8')

/**
 * 纯函数审计（**判据 6 的自证靠它**：同一份逻辑喂内存里的坏形态，必须报红）：
 * 返回违规清单（空 = 通过）。
 */
function auditInset(
  discovered: string[],
  ledger: Ledger,
  read: (p: string) => string,
): string[] {
  const problems: string[] = []
  const names = Object.keys(ledger.pages ?? {})
  if (names.length === 0) problems.push('台账为空（fail-closed）：没有任何页面在为底栏留位')
  for (const page of discovered) {
    const entry = ledger.pages[page]
    if (!entry) {
      problems.push(`未登记：${page} 挂了 MerchantTabBar，但台账里没有它（挂条必须按条高留位 + 登记）`)
      continue
    }
    if (!read(page).includes(entry.root_class)) {
      problems.push(`${page}: 台账声明的根类 ${entry.root_class} 不在该页面里（台账写了个不存在的对象）`)
    }
    let scss = ''
    try {
      scss = read(entry.scss)
    } catch {
      problems.push(`${page}: 台账声明的样式文件读不到（${entry.scss}）`)
      continue
    }
    const block = rootBlock(scssCode(scss), entry.root_class)
    if (!block) {
      problems.push(`${page}: ${entry.scss} 里没有 .${entry.root_class} 根块`)
      continue
    }
    if (!BORDER_BOX.test(block)) {
      problems.push(`${page}: .${entry.root_class} 缺 box-sizing: border-box（状态栏行内 padding 会顶出视口）`)
    }
    if (!RESERVE.test(block)) {
      problems.push(
        `${page}: .${entry.root_class} 未按底栏条高留位（须 padding-bottom: calc(50PX + env(safe-area-inset-bottom))）` +
          ` ⇒ 内容溢出时最后一行会被底栏压住`,
      )
    }
  }
  for (const page of names) {
    if (!discovered.includes(page)) {
      problems.push(`台账陈旧：${page} 已不挂 MerchantTabBar ⇒ 删掉这条（台账只许缩短）`)
    }
  }
  return problems
}

const ledger: Ledger = JSON.parse(fs.readFileSync(LEDGER_PATH, 'utf-8'))
const discovered = discoverMountingPages()

describe('类级守卫：挂底栏的页面必须按条高留位（issue #6666 判据 1）', () => {
  it('真语料上零违规：每个挂底栏的页面都登记了、且根块里预留算式在位', () => {
    expect(discovered.length).toBeGreaterThanOrEqual(4)
    expect(auditInset(discovered, ledger, readFile)).toEqual([])
  })

  it('台账键集合 == 实测挂载集合（双向，未登记/陈旧都红）', () => {
    expect(Object.keys(ledger.pages).sort()).toEqual(discovered)
  })

  it('🔴 底栏条高算式是单一真值：页面预留与 MerchantTabBar.scss 逐字同源', () => {
    const bar = scssCode(fs.readFileSync(BAR_SCSS, 'utf-8'))
    expect(bar).toMatch(BAR_HEIGHT)
  })
})

describe('判别力自证（issue #6666 判据 6）：坏形态必红、合法形态不误报', () => {
  /** 内存里的合法语料：一个挂了底栏 + 已留位的页面 */
  const okLedger: Ledger = { pages: { 'src/pages/x/index.tsx': { root_class: 'x-page', scss: 'src/pages/x/index.scss' } } }
  const okScss = '.x-page { min-height: 100vh; box-sizing: border-box; padding-bottom: calc(50PX + env(safe-area-inset-bottom)); }'
  // 🔴 合成语料里的 import 行**必须**写成「从 tests/ 出发能解析到真身」的形态：
  //    CI 的触发面元守卫（tests/unit_ci_workflows/test_local_gate_matrix.py 的 C5）把测试源码里
  //    **字符串字面量**形式的 `../` 相对路径当**真实输入**静态解析。若写成页面视角的
  //    `../../components/MerchantTabBar` ⇒ 从 tests/ 解析出 `frontend/components/MerchantTabBar`
  //    （**仓里没有这个目录**）⇒ 判「跨目录输入未登记 = 漏面」并卡合并（issue #6681 实测踩过）。
  //    写成 `../src/components/MerchantTabBar` ⇒ 解析 = `frontend/bmini-app/src/components/MerchantTabBar`，
  //    正是真身所在路径、落在触发面 `frontend/bmini-app/` 内 ⇒ 元守卫不报（也**不**去登记假路径）。
  const okTsx = "import MerchantTabBar from '../src/components/MerchantTabBar'\n<View className='x-page'>"
  const okRead = (p: string) => (p === 'src/pages/x/index.tsx' ? okTsx : okScss)
  const mounts = ['src/pages/x/index.tsx']

  it('对照读数：合法形态 ⇒ 零违规', () => {
    expect(auditInset(mounts, okLedger, okRead)).toEqual([])
  })

  it('注入历史坏形态（padding-bottom: 24px，逐字照 #6666 的修前源码）⇒ 具名报出该页', () => {
    const bad = okScss.replace('padding-bottom: calc(50PX + env(safe-area-inset-bottom));', 'padding-bottom: 24px;')
    const problems = auditInset(mounts, okLedger, (p) => (p === 'src/pages/x/index.tsx' ? okTsx : bad))
    expect(problems.join('\n')).toContain('src/pages/x/index.tsx')
    expect(problems.join('\n')).toContain('未按底栏条高留位')
  })

  it('注入「新页面挂条但不登记」⇒ 未登记判红', () => {
    const problems = auditInset([...mounts, 'src/pages/y/index.tsx'], okLedger, okRead)
    expect(problems.join('\n')).toContain('未登记：src/pages/y/index.tsx')
  })

  it('注入「台账陈旧（页面已不挂条）」⇒ 只许缩短判红', () => {
    const problems = auditInset([], okLedger, okRead)
    expect(problems.join('\n')).toContain('台账陈旧')
  })

  it('注入「台账被清空」⇒ fail-closed 判红', () => {
    const problems = auditInset(mounts, { pages: {} }, okRead)
    expect(problems.join('\n')).toContain('台账为空')
  })

  it('注入「台账指向不存在的根类」⇒ 判红（台账不许空转）', () => {
    const bogus: Ledger = { pages: { 'src/pages/x/index.tsx': { root_class: 'nope-page', scss: 'src/pages/x/index.scss' } } }
    const problems = auditInset(mounts, bogus, okRead)
    expect(problems.join('\n')).toContain('nope-page')
  })
})
