// case_ids: BM-001, BM-006
/**
 * 类级元守卫（issue #5650；AGENTS.md 铁律 8「类级固化」/ `migao-dev-flow` §23）：
 * **本仓用到的小程序专有 API，必须同时给 h5 去处** —— 让「新增一处 h5 没实现的 Taro 调用」进不来。
 *
 * 射程**按实测清单取**，不靠印象列三条（本 issue 立单时正是凭印象写错规格、被评论区更正）：
 *   清单 A（**明确不实现**）= `temporarilyNotSupport('<api>')`，现取 `@tarojs/taro-h5/dist`（313 条）；
 *   清单 B（**只在微信内置浏览器可用**）= `processOpenApi({…})` 且**无 `standardMethod`**，
 *           现取同一实现包（带 `standardMethod` 的如 `getLocation` 有 W3C 兜底，不在面内）。
 * 命中 `(A ∪ B) ∩ 本仓 Taro.* 用法` 的每一处，必须同时满足：
 *   ① 该 API 在 `src/utils/platform.ts` 的 `H5_API_OUTLET_LEDGER` 里登记了 h5 出路；
 *   ② **调用点所在文件**引入了 `utils/platform`（= 真有显式平台分支，不是只在别处写了句注释）。
 * 反向也判：台账条目必须仍然活着（清单∩用法里已不存在 ⇒ 红）—— 台账只许缩短，不许变成自我复制的历史文档。
 *
 * fail-closed：读不到实现包 / 两张清单抽不出来（口径漂移）⇒ 抛错判红，**不允许**退化成「0 命中 = 通过」。
 */
import fs from 'fs'
import path from 'path'
import { H5_API_OUTLET_LEDGER } from '../src/utils/platform'

const ROOT = path.join(__dirname, '..')
const SRC_DIR = path.join(ROOT, 'src')
const TARO_H5_DIST = path.join(ROOT, 'node_modules', '@tarojs', 'taro-h5', 'dist')

const SOURCE_EXT = /\.(ts|tsx)$/

function walk(dir: string, keep: (name: string) => boolean, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(full, keep, out)
    else if (keep(entry.name)) out.push(full)
  }
  return out
}

/** Taro h5 实现包的全部 `.js`（唯一权威清单的来源） */
function distJsFiles(): string[] {
  if (!fs.existsSync(TARO_H5_DIST)) {
    throw new Error(
      `找不到 Taro h5 实现包：${TARO_H5_DIST}（守卫 fail-closed：读不到权威清单的「绿」不算绿 —— 先 npm ci）`,
    )
  }
  const files = walk(TARO_H5_DIST, (name) => name.endsWith('.js'))
  if (files.length === 0) throw new Error(`实现包里一个 .js 都没有：${TARO_H5_DIST}`)
  return files
}

/** 清单 A：Taro h5「明确不实现」的 API 名 */
function unsupportedApis(): Set<string> {
  const out = new Set<string>()
  for (const file of distJsFiles()) {
    const text = fs.readFileSync(file, 'utf8')
    for (const match of text.matchAll(/temporarilyNotSupport\('([A-Za-z_$][\w$]*)'\)/g)) {
      out.add(match[1])
    }
  }
  if (out.size < 100) {
    throw new Error(`清单 A 只抽到 ${out.size} 条（预期数百条）⇒ 抽取口径已漂移，判红而不是判绿`)
  }
  return out
}

/** 清单 B：h5 实现**只**走微信 JS-SDK 的 API 名（`processOpenApi` 且无 `standardMethod`） */
function jsSdkOnlyApis(): Set<string> {
  const out = new Set<string>()
  const re =
    /(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\/\* @__PURE__ \*\/\s*processOpenApi\(\{([\s\S]*?)\n\}\);/g
  for (const file of distJsFiles()) {
    const text = fs.readFileSync(file, 'utf8')
    for (const match of text.matchAll(re)) {
      if (!/standardMethod/.test(match[2])) out.add(match[1])
    }
  }
  // 机制存活读数：抽取口径一漂移就会连扫描码都抽不到 ⇒ 当场判红（而不是「面变窄了但没人知道」）
  if (!out.has('scanCode')) {
    throw new Error('清单 B 抽取失效：连 scanCode 都没抽到 ⇒ 判红而不是判绿')
  }
  return out
}

interface Usage {
  api: string
  file: string
}

/**
 * 去掉注释后再扫用法 —— 否则**说明文字里的引用会被当成使用**
 * （`migao-dev-flow` §17.3：内容扫描式机制分不清「引用」与「使用」；
 *  实证：`src/utils/platform.ts` 的 JSDoc 里写了 `Taro.scanCode` 就被算成一处命中）。
 * 只处理 `//` 与块注释；`https://` 里的 `//` 用 `[^:]` 前缀排除。
 */
function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')
}

/** 本仓 `src/**` 里全部 `Taro.<api>` 用法（含类型引用如 `Taro.RequestTask`，无害） */
function taroUsages(): Usage[] {
  const out: Usage[] = []
  for (const file of walk(SRC_DIR, (name) => SOURCE_EXT.test(name))) {
    const rel = path.relative(ROOT, file)
    const text = stripComments(fs.readFileSync(file, 'utf8'))
    for (const match of text.matchAll(/\bTaro\.([A-Za-z_$][\w$]*)/g)) {
      out.push({ api: match[1], file: rel })
    }
  }
  return out
}

/** 该文件是否引入了平台判别模块（= 有显式平台分支的机械可判形态） */
function hasPlatformBranch(relFile: string): boolean {
  const text = fs.readFileSync(path.join(ROOT, relFile), 'utf8')
  return /from\s+['"][^'"]*\/platform['"]/.test(text) || /from\s+['"]\.\/platform['"]/.test(text)
}

describe('类级守卫：小程序专有 API 必须同时给 h5 去处（issue #5650）', () => {
  const unsupported = unsupportedApis()
  const jsSdkOnly = jsSdkOnlyApis()
  const usages = taroUsages()
  const hazardous = usages.filter((u) => unsupported.has(u.api) || jsSdkOnly.has(u.api))

  it('两张清单现取成功且非空（前提来自实现包，不是人手维护的表）', () => {
    expect(unsupported.size).toBeGreaterThan(100)
    expect(jsSdkOnly.has('scanCode')).toBe(true)
  })

  it('射程非空且确实取到了本仓的命中用法（判据不许空转成「0 命中 = 通过」）', () => {
    expect(usages.length).toBeGreaterThan(50)
    expect(Array.from(new Set(hazardous.map((u) => u.api))).sort()).toEqual([
      'getRecorderManager',
      'login',
      'scanCode',
    ])
  })

  it('命中清单的每一处用法都已在台账登记 h5 出路（新增未登记 ⇒ 红）', () => {
    const unregistered = hazardous.filter((u) => !(u.api in H5_API_OUTLET_LEDGER))
    expect(unregistered.map((u) => `${u.file} → Taro.${u.api}`)).toEqual([])
  })

  it('台账条目必须仍然活着（清单 ∩ 用法里已不存在 ⇒ 红；只许缩短）', () => {
    const live = new Set(hazardous.map((u) => u.api))
    const stale = Object.keys(H5_API_OUTLET_LEDGER).filter((api) => !live.has(api))
    expect(stale).toEqual([])
  })

  it('每一处命中用法所在的文件都有显式平台分支（引入 utils/platform）', () => {
    const files = Array.from(new Set(hazardous.map((u) => u.file))).sort()
    expect(files.length).toBeGreaterThan(0)
    const missing = files.filter((f) => !hasPlatformBranch(f))
    expect(missing).toEqual([])
  })

  it('台账每条都写清了「h5 上用户看到什么」（空值即红，防占位条目）', () => {
    const empty = Object.entries(H5_API_OUTLET_LEDGER)
      .filter(([, outlet]) => String(outlet).trim().length < 10)
      .map(([api]) => api)
    expect(empty).toEqual([])
  })
})
