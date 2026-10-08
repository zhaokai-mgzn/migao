// case_ids: UI-055, CH-009
/**
 * @case_ids UI-055, CH-009
 *
 * 声明与仓库既有形态逐字一致（与 `frontend/admin-web/tests/unit/components/NumberInputWiring.test.ts` 同款：
 * `// case_ids:` 行 + JSDoc `@case_ids` 双声明）—— 两种解析口径都认得出「本文件声明了哪些用例」。
 */
/**
 * 静态扫描：Taro 端（mini-app / bmini-app）的**数字键盘**不得把小数点挡在门外（issue #5198 同族，
 * UI-055 判据 5 的**类级**半边）。
 *
 * ## 为什么要有这一条
 *
 * 小程序的 Taro `Input` 有两种数字键盘，`type` 一字之差、能力不同：
 *
 * | `type` | 键盘 | 小数点键 |
 * |---|---|---|
 * | `number` | 纯数字键盘 | ❌ **没有**（「2.5 米」根本打不出来） |
 * | `digit` | 带小数点的数字键盘 | ✅ 有 |
 *
 * UI-055 判据 5 修过**一处**（工人端报工数量，`bmini-app/src/pages/production/index/index.tsx`），
 * 但「同一机制还有没有第二处」当时没问 —— 于是 **`FormCard`（interact form 的通用数字字段，
 * 黄金策在小程序里收集尺寸 / 数量 / 金额的入口）整批漏网**：`const inputType = isNumber ? 'number' : 'text'`
 * ⇒ 用户在真机上**无法输入任何小数**（用户 2026-09-29 报障「输入框无法输入小数点」）。
 * 这正是 `migao-dev-flow` §26 `FM-R12`「只想到一处漏同族」的形态 ⇒ 本文件把它钉成**类级**判据。
 *
 * ## 判据（语义，不是某一种写法）
 *
 * 扫 `src/**` 的 `.tsx`：Taro `Input` 开标签上 `type` 取 `'number'` / `"number"` ⇒ 命中；
 * **豁免 = 纯数字字段**（手机号 / 验证码 / PIN / 工号 —— 它们的键盘本就该没有小数点键），两条各判一次：
 * ① 字段**名**含 `phone` / `mobile` / `tel` / `pin` / `captcha`（大小写不敏感）；
 * ② **中文标签**含 `验证码` / `手机号` / `短信` / `密码` / `PIN` / `工号` / `账号`
 * （② 是实测逼出来的：`bmini-app` 登录页的「验证码」格标签写在**兄弟节点的 `<Text>`** 里，
 * 只按字段名判会把它误判成违规；而它恰恰是纯数字字段的正例）。
 * 判定窗口 = 命中点**前后各 500 字符**（同一 JSX 表达式 + 紧邻的 label / placeholder / 常量名）。
 * 注释里的旧写法先剥掉（说明 ≠ 接线，与 `admin-web` 的 `NumberInputWiring.test.ts` 同法）。
 *
 * ## 本文件自身可红（红证见「红证样本」三条）
 *
 * - ① `type='number'` 且无豁免词 ⇒ 必须扫出；② 有 `phone` 豁免词 ⇒ 不扫出；
 *   ③ 注释里写旧写法 ⇒ 不扫出（剥注释）；④ 真仓（mini-app + bmini-app）零命中。
 *   把 `findNumberTypedInputs` 换成 `() => []` ⇒ ① 必红。
 *
 * ## 已知不覆盖（**显式登记，不许留白**）
 *
 * 1. **不是 Taro `Input` 的输入控件**：`Textarea` / 原生 input / 第三方组件里的 `type` ——
 *    静态文本扫描只认 Taro `Input` 带 `type=` 的形态（本仓 Taro 端数字录入**只有**这一条路子，实测）。
 * 2. **`type` 经变量间接传入**（`type={x}` 形态）：扫不到 —— 本仓实现侧的 `FormCard` 恰是这种形态
 *    ⇒ 由**实例判据**（两个 app 的 `tests/form-card.test.tsx`「数字字段…键盘用 digit」）钉住；
 *    静态扫描只是补漏网面，**不替代**实例判据。
 * 3. **admin-web（H5 / 桌面）不在射程**：浏览器 `type="number"` 不挡小数点键（挡的是中间态，
 *    另有 UI-055 判据 1/6 与共享 `NumberInput` 治理）。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

/** 剥掉块注释与行注释（注释里的旧写法是**说明**，不是接线） */
export function stripComments(code: string): string {
  return code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

/** `phone` / `mobile` / `tel` / `pin` / `captcha`（字段名或属性值，大小写不敏感） */
const INTEGER_ONLY_NAME = /phone|mobile|\btel\b|pin|captcha/i

/** 纯数字字段的**中文标签**（同一窗口内出现即豁免；「工号」写在可从别处解析的 label 变量里，见 docstring） */
const INTEGER_ONLY_LABEL = /验证码|手机号|短信|密码|\bPIN\b|工号|账号/

/** Taro `Input` 开标签 + 其 `type='number'` 属性 */
const NUMBER_TYPED_INPUT_RE = /<Input\b[\s\S]{0,300}?\btype\s*=\s*(['"])number\1/g

/** 豁免判定窗口：命中点**前后各 500 字符**（同一 JSX 表达式 + 紧邻的 aria-label / placeholder / 常量名） */
const WINDOW = 500

/** 扫描样本里用到的标签形态（写成常量，避免 docstring / 样本自身被当成 JSX） */
const OPEN = '<'
const CLOSE = '/>'

/**
 * 扫出一段代码里所有「用纯数字键盘承载非纯数字字段」的 Taro `Input`（返回命中原文，便于归因）。
 */
export function findNumberTypedInputs(code: string): string[] {
  const src = stripComments(code)
  const hits: string[] = []
  for (const m of src.matchAll(NUMBER_TYPED_INPUT_RE)) {
    const at = m.index ?? 0
    const window = src.slice(Math.max(0, at - WINDOW), at + m[0].length + WINDOW)
    if (INTEGER_ONLY_NAME.test(window) || INTEGER_ONLY_LABEL.test(window)) continue
    hits.push(m[0].replace(/\s+/g, ' ').trim())
  }
  return hits
}

/** 递归收集 .tsx（跳过测试 / 声明文件 —— 本判据管的是产品代码） */
function sourceFiles(dir: string, acc: string[] = []): string[] {
  let entries: string[]
  try {
    entries = readdirSync(dir)
  } catch {
    return acc // 某些端在本地没检出（CI 上是完整仓）⇒ 不因此判红
  }
  for (const name of entries) {
    const p = join(dir, name)
    if (name === 'node_modules' || name === 'dist' || name === '.taro') continue
    if (statSync(p).isDirectory()) sourceFiles(p, acc)
    else if (name.endsWith('.tsx') && !name.endsWith('.d.ts')) acc.push(p)
  }
  return acc
}

describe('静态扫描：Taro 数字键盘不得挡小数点（UI-055 判据 5 的类级半边）', () => {
  // ── 红证样本（删判据 ⇒ ① 必红）──────────────────────────────────────────────
  it('① 红证样本：`type="number"` 承载非纯数字字段 ⇒ 必须被扫出', () => {
    const sample = `${OPEN}Input value={v} type='number' placeholder='用料米数' onInput={f} ${CLOSE}`
    expect(findNumberTypedInputs(sample)).toHaveLength(1)
  })

  it('② 红证样本：纯数字字段（手机号 / PIN）豁免 —— 它们的键盘本就该没有小数点键', () => {
    const phone = `${OPEN}Input value={v} type='number' maxlength={11} placeholder='11 位手机号' ${CLOSE}`
    const pin = `${OPEN}Input value={pin} type='number' aria-label='PIN 码' ${CLOSE}`
    expect(findNumberTypedInputs(phone)).toEqual([])
    expect(findNumberTypedInputs(pin)).toEqual([])
  })

  it('③ 红证样本：注释里写旧写法不算违规（剥注释，防假阳性）', () => {
    const line = `${OPEN}Input type='number' placeholder='数量(米)' ${CLOSE}`
    expect(findNumberTypedInputs(`// 旧形态 ${line} 已改 digit\nconst x = 1`)).toEqual([])
    expect(findNumberTypedInputs(`/* ${line} */\nconst y = 1`)).toEqual([])
  })

  // ── 已知不覆盖：**显式登记**（钉成可执行断言，防后人误以为漏）──────────────────
  it('④ 已知不覆盖：`type={x}` 间接形态扫不到（由实例判据承担，不是留白）', () => {
    const sample = `${OPEN}Input value={v} type={inputType} placeholder='数量(米)' ${CLOSE}`
    expect(findNumberTypedInputs(sample)).toEqual([])
  })

  it('⑤ 已知不覆盖：`Textarea` / 原生 input 不在射程', () => {
    expect(findNumberTypedInputs(`${OPEN}Textarea value={v} type='number' ${CLOSE}`)).toEqual([])
    expect(findNumberTypedInputs(`${OPEN}input type="number" placeholder="数量(米)" ${CLOSE}`)).toEqual([])
  })

  // ── 真仓扫描 ───────────────────────────────────────────────────────────────
  it('⑥ 真仓（mini-app / bmini-app 的 src）零命中', () => {
    const roots = ['src', '../bmini-app/src'].map((d) => join(process.cwd(), d))
    const bad = roots.flatMap((root) =>
      sourceFiles(root).flatMap((f) =>
        findNumberTypedInputs(readFileSync(f, 'utf8')).map((hit) => `${f}: ${hit}`)
      )
    )
    expect(bad).toEqual([])
  })
})
