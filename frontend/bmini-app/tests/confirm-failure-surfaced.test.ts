// case_ids: BM-052
/**
 * 类级元守卫（issue #7822；AGENTS.md 铁律 8「类级固化」/ `migao-dev-flow` §23）：
 * **不可逆动作的二次确认，弹窗失联必须被说出来。**
 *
 * 病灶（2026-10-26 线上实测）：`confirmAdminAction` 把「工人点了取消」与「**确认框根本没弹出来**」
 * 压成同一个 `false` ⇒ 弹窗失败时页面**静默 return**：工人点「提交过账」，屏上什么都不发生
 * （既不建单、也不报错）⇒ 读到的就是「点了没反应」。
 *
 * 判据（双向）：
 * ① **未处理即红**：扫 `src/**` 里所有调用 `confirmAdminAction(` 的文件（注释剥离后），要求同一文件
 *    也出现 `confirmActionResult(`（= 调用方自己分辨「取消」与「弹窗失败」）；不满足者必须登记在
 *    `CONFIRM_FAILURE_UNHANDLED_LEDGER` 里（存量债，**只许缩短**）。
 * ② **台账不许腐烂**：台账里的文件必须仍然调用 `confirmAdminAction(` —— 已迁走 / 文件已删 ⇒ 红。
 * ③ `src/utils/adminConfirm.ts` 自身是实现（两个函数都在里面），不算调用点。
 * fail-closed：一个调用点都扫不到 ⇒ 红（判据不许空转成「0 命中 = 通过」）。
 *
 * 红证（实跑过，见 PR body）：在任何未登记的页面里加一行 `await confirmAdminAction('x','y')` ⇒ 判据 1 红；
 * 把台账里某一条删掉而文件没迁移 ⇒ 判据 2 红。
 */
import fs from 'fs'
import path from 'path'

const SRC_DIR = path.resolve(__dirname, '..', 'src')

/**
 * 豁免台账（issue #7822 之前就存在的「只判 true/false」调用点）。
 *
 * 🔴 **只许缩短**：新调用点必须用 `confirmActionResult`（自己把 `failed` 说出来）；
 * 存量三个商家面页面本次不改（不在本单射程），迁走一个就删一条。
 */
const CONFIRM_FAILURE_UNHANDLED_LEDGER: string[] = [
  'src/pages/admin/after-sales/index.tsx',
  'src/pages/admin/inbound/index.tsx',
  'src/pages/admin/pool/index.tsx',
].sort()

/** 实现文件（两个函数都在这里；不当作调用点） */
const IMPLEMENTATION_FILE = 'src/utils/adminConfirm.ts'

/** 递归收集 `src/**` 下的源码文件 */
function walkSource(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walkSource(full, out)
    else if (/\.(ts|tsx)$/.test(entry.name)) out.push(full)
  }
  return out
}

/**
 * 去掉**块注释**与**整行注释**后返回代码（保留行号无关的文本匹配用）。
 *
 * ⚠️ 有意不剥行尾 `//`：源码里有 `https://…` 这类字符串，按 `//` 切断会把那一行后半段一起吃掉
 * （= 假阴性，本守卫最坏的失败方向）。
 */
function stripComments(code: string): string {
  const withoutBlocks = code.replace(/\/\*[\s\S]*?\*\//g, '')
  return withoutBlocks
    .split('\n')
    .filter((line) => !line.trim().startsWith('//'))
    .join('\n')
}

interface CallSite {
  /** 仓库相对（bmini 根）路径 */
  file: string
  /** 是否处理了 `failed` 态 */
  handlesFailure: boolean
}

/** 现取全部调用点（`file` 相对 `frontend/bmini-app/` 根） */
function confirmCallSites(): CallSite[] {
  const root = path.resolve(SRC_DIR, '..')
  return walkSource(SRC_DIR)
    .map((full) => ({ full, rel: path.relative(root, full).split(path.sep).join('/') }))
    .filter(({ rel }) => rel !== IMPLEMENTATION_FILE)
    .map(({ full, rel }) => ({ rel, code: stripComments(fs.readFileSync(full, 'utf8')) }))
    .filter(({ code }) => code.includes('confirmAdminAction('))
    .map(({ rel, code }) => ({ file: rel, handlesFailure: code.includes('confirmActionResult(') }))
    .sort((a, b) => a.file.localeCompare(b.file))
}

describe('类级守卫：不可逆动作的确认弹窗失联必须被说出来（issue #7822）', () => {
  const callSites = confirmCallSites()

  it('射程非空（判据不许空转成「0 命中 = 通过」）', () => {
    expect(callSites.length).toBeGreaterThan(0)
    // 本单自己那一页是「处理了 failed」的样板 —— 它必须真的在射程内
    expect(callSites.map((c) => c.file)).toContain('src/pages/admin/pool/index.tsx')
  })

  it('新增调用点必须处理 failed 态（未处理即红，除非登记进只许缩短的台账）', () => {
    const unregistered = callSites
      .filter((c) => !c.handlesFailure)
      .map((c) => c.file)
      .filter((f) => !CONFIRM_FAILURE_UNHANDLED_LEDGER.includes(f))
    expect(unregistered).toEqual([])
  })

  it('台账只许缩短：每一条都必须仍然活着（文件在、且仍然只判 true/false）', () => {
    const stillLegacy = callSites.filter((c) => !c.handlesFailure).map((c) => c.file)
    const stale = CONFIRM_FAILURE_UNHANDLED_LEDGER.filter((f) => !stillLegacy.includes(f))
    expect(stale).toEqual([])
  })

  it('台账条数**现取**且不超过基线 3 条（防悄悄加长）', () => {
    expect(CONFIRM_FAILURE_UNHANDLED_LEDGER.length).toBeLessThanOrEqual(3)
    expect([...new Set(CONFIRM_FAILURE_UNHANDLED_LEDGER)]).toHaveLength(CONFIRM_FAILURE_UNHANDLED_LEDGER.length)
  })
})
