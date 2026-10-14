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
import {
  hasPlatformBranch,
  jsSdkOnlyApis,
  taroUsages,
  unsupportedApis,
} from './helpers/h5PlatformLists'

/** 递归收集 `src/**` 下的源码文件（本文件那条类级判据用；不复制 helper 里那份业务扫描） */
function walkSource(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walkSource(full, out)
    else if (/\.(ts|tsx)$/.test(entry.name)) out.push(full)
  }
  return out
}

// 抽取实现（两张清单 / 用法扫描 / 注释剥离 / 平台分支判定）**只有一份** ——
// 共享 helper `tests/helpers/h5PlatformLists.ts`（issue #5654 起被管理面守卫共用；
// 两处各抄一份 = 第二份会漂的口径，见 `migao-dev-flow` §17.3 与 issue #5346）。
// 本文件只保留**本守卫的判据**。

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
    // 🔴 2026-10-14（issue #6868 实现包 D1）：小程序报工页整页删除 ⇒ 它是本仓**唯一**的
    // `Taro.scanCode` 用法（页内「扫一扫」的降级面随页面退场：工人报工面 = H5 `/w/`，
    // 那台屏上**没有页内扫码**）⇒ 命中集合少了 `scanCode`，其余三处仍在射程内。
    expect(Array.from(new Set(hazardous.map((u) => u.api))).sort()).toEqual([
      'createOffscreenCanvas',
      'getRecorderManager',
      'login',
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

  // ── issue #5750：扫码降级不许退回「只给手输」────────────────────────────
  // 用户在 iPhone 上点「扫一扫」只得到一句「当前浏览器不支持扫码」⇒ 只能手敲单号。
  // 而本仓在拍照入库链路上**早已验证**「拍照 + 本机 jsQR 解码」在任何浏览器都能走通。
  // 🔴 2026-10-14（issue #6868 实现包 D1）：原「`scanCode` 的 h5 出路必须写清『拍照识别』降级」
  // 判据随该台账条目一起退场（唯一用法 = 已删除的小程序报工页）。这条**不是**放宽：
  // `scanCode` 已不在本仓射程内（清单 ∩ 用法 = ∅ ⇒ 台账条目必须删），下面那条
  // 「唯一直接依赖 jsqr」的类级判据接手了「不许出现第二份解码实现」这一半。

  it('降级必须复用既有解码模块：全 `src/**` 只有一处直接依赖 jsqr（第二份解码实现 ⇒ 红）', () => {
    // 🔴 2026-10-14（issue #6868 实现包 D1）：原判据锚在**报工页**（页内扫一扫的降级面）；该页已整页
    // 删除 ⇒ 改钉为**类级**形态（射程更宽，不是放宽）：解码库的唯一直接依赖点必须仍是
    // `utils/inbound/barcodeDecode.ts` —— 拍照入库 / 补打两页都 import 它的导出，不自己依赖 jsqr。
    // 判据锚在**依赖形态**上而不是 `jsQR` 这个词（注释里说明「用 jsQR 解码」是合法的）。
    const offenders = walkSource(path.join(__dirname, '..', 'src'))
      .filter((file) => /from\s+['"]jsqr['"]|require\(\s*['"]jsqr['"]\s*\)/.test(fs.readFileSync(file, 'utf8')))
      .map((file) => path.relative(path.join(__dirname, '..'), file).split(path.sep).join('/'))
    expect(offenders).toEqual(['src/utils/inbound/barcodeDecode.ts'])
  })
})
