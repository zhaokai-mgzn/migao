// case_ids: BM-040, BM-047
/**
 * 类级守卫：**`className` 里的模板串不许写在单引号/双引号里**（issue #6666 判据 2）
 *
 * ## 治的形态（确定性缺陷，已复核）
 *
 * `frontend/bmini-app/src/pages/sessions/detail/index.tsx` 的会话状态类名写成
 * `className='detail-header__status detail-header__status--${detail?.status}'`
 * —— 引号不是反引号 ⇒ 类名是**字面量**（`--waiting` / `--active` / `--ended` 三套配色
 * **一次都没生效过**，而页面上看不出「坏了」：文字照样渲染，只是颜色永远是默认色）。
 *
 * 这一类缺陷的共性是：**看似动态的类名其实恒为字面量**，而单测若只断言「状态文案正确」
 * 就永远抓不到它。⇒ 判据必须落在**形态**上：`className` 属性值里出现 `${` 时，
 * 承载它的引号必须是反引号。
 *
 * ## 判据
 *
 * | # | 判据 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | 真语料零违规：src 下**所有 .tsx** 里没有「引号内 `${`」的 className | 再写一处（含历史那处复原）⇒ 具名红 |
 * | 2 | 台账（`tests/className-interpolation-ledger.json`）与实测**逐条相等**（只许缩短） | 新增违规 ⇒ 红；修好却不删台账条目 ⇒ 红 |
 * | 3 | 判别力自证：历史坏形态被抓、反引号形态不误报、`className='a' onClick={…}` 不误报 | 守卫退化成绿 ⇒ 红 |
 * | 4 | 具名回归：坐席会话详情页的状态类名必须是模板串（`--${…}`） | 改回单引号 ⇒ 红 |
 */
import fs from 'fs'
import path from 'path'

const ROOT = path.resolve(__dirname, '..')
const SRC = path.join(ROOT, 'src')
const LEDGER_PATH = path.join(__dirname, 'className-interpolation-ledger.json')
const DETAIL_PAGE = 'src/pages/sessions/detail/index.tsx'

type Ledger = { known_offenders: string[] }

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p, out)
    else out.push(p)
  }
  return out
}

/**
 * 扫「`className` 用引号承载、值里却出现 `${`」的行。
 *
 * 形态判据（不是语义判据）：`className=` 后紧跟 `'` 或 `"` ⇒ 取到**同种引号**的下一次出现；
 * 若 `${` 落在它之前 ⇒ 这一处是恒为字面量的类名。
 * 反引号形态（合法）不匹配本函数的第一跳 ⇒ 天然不误报。
 */
function findInterpolationOffenders(source: string): string[] {
  const out: string[] = []
  for (const line of source.split('\n')) {
    const m = /className\s*=\s*(['"])/.exec(line)
    if (!m) continue
    const quote = m[1]
    const rest = line.slice(m.index + m[0].length)
    const close = rest.indexOf(quote)
    const dollar = rest.indexOf('${')
    if (dollar >= 0 && (close < 0 || dollar < close)) out.push(line.trim())
  }
  return out
}

function scanOffenders(files: string[] = walk(SRC)): string[] {
  const out: string[] = []
  for (const f of files) {
    if (!f.endsWith('.tsx')) continue
    const hits = findInterpolationOffenders(fs.readFileSync(f, 'utf-8'))
    hits.forEach((h) => out.push(`${path.relative(ROOT, f).split(path.sep).join('/')} :: ${h}`))
  }
  return out.sort()
}

const ledger: Ledger = JSON.parse(fs.readFileSync(LEDGER_PATH, 'utf-8'))
const offenders = scanOffenders()

describe('类级守卫：className 里的 ${} 必须在反引号里（issue #6666 判据 2）', () => {
  it('真语料零违规（全仓扫 src/**/*.tsx）', () => {
    expect(offenders).toEqual([])
  })

  it('台账与实测逐条相等（只许缩短）', () => {
    expect(ledger.known_offenders).toEqual(offenders)
  })

  it('🔴 具名回归：坐席会话详情页的状态类名是模板串（三套配色才可能生效）', () => {
    const src = fs.readFileSync(path.join(ROOT, DETAIL_PAGE), 'utf-8')
    expect(src).toContain('detail-header__status--${')
    expect(findInterpolationOffenders(src)).toEqual([])
  })
})

describe('判别力自证（issue #6666 判据 3）', () => {
  it('历史坏形态（逐字照修前源码）被抓', () => {
    const bad = "          <Text className='detail-header__status detail-header__status--${detail?.status}'>"
    expect(findInterpolationOffenders(bad)).toHaveLength(1)
  })

  it('修后形态（反引号）不误报', () => {
    const ok = '          <Text className={`detail-header__status detail-header__status--${detail?.status}`}>'
    expect(findInterpolationOffenders(ok)).toEqual([])
  })

  it('同一行后面的事件处理器里出现 `${` 不误报（引号已闭合）', () => {
    const ok = "          <View className='task-item' onClick={() => setX(`${id}`)}>"
    expect(findInterpolationOffenders(ok)).toEqual([])
  })

  it('双引号形态同样被抓（不只管单引号）', () => {
    const bad = '          <View className="card card--${kind}">'
    expect(findInterpolationOffenders(bad)).toHaveLength(1)
  })
})
