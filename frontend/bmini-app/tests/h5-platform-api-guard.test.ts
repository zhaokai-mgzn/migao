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
    expect(Array.from(new Set(hazardous.map((u) => u.api))).sort()).toEqual([
      'createOffscreenCanvas',
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

  // ── issue #5750：扫码降级不许退回「只给手输」────────────────────────────
  // 用户在 iPhone 上点「扫一扫」只得到一句「当前浏览器不支持扫码」⇒ 只能手敲单号。
  // 而本仓在拍照入库链路上**早已验证**「拍照 + 本机 jsQR 解码」在任何浏览器都能走通。
  it('scanCode 的 h5 出路必须写清「拍照识别」这条首选降级（退回只给手输 ⇒ 红）', () => {
    expect(H5_API_OUTLET_LEDGER.scanCode).toContain('拍照')
  })

  it('降级必须复用既有解码模块：报工页不得出现第二份解码实现（直接依赖 jsQR ⇒ 红）', () => {
    const page = fs.readFileSync(
      path.join(__dirname, '..', 'src', 'pages', 'production', 'index', 'index.tsx'),
      'utf8',
    )
    // ① 复用：两个既有导出都真的被调用（只 import 不用 = 假接线）
    expect(page).toContain('utils/inbound/barcodeDecode')
    expect(page).toMatch(/loadPixelsFromFileH5\(/)
    expect(page).toMatch(/decodeQrFromImageData\(/)
    // ② 不许绕过它直接依赖解码库（那会与拍照入库那套的平台分支/失败方向分叉成第二份实现）。
    //    判据锚在**依赖形态**上而不是 `jsQR` 这个词 —— 注释里说明「用 jsQR 解码」是合法的。
    expect(page).not.toMatch(/from\s+['"]jsqr['"]/)
    expect(page).not.toMatch(/require\(\s*['"]jsqr['"]\s*\)/)
  })
})
