// case_ids: OR-040
/**
 * `frontend/admin-web/src/lib/craft-auto-features.ts` 的**残余面**守卫（issue #5035 收口后）。
 *
 * ## 本模块现在还剩下什么（以及为什么）
 *
 * 用户 2026-09-21 的裁定把「自动识别」整条链搬到了服务端：
 * - **判定**（进加工费组合键）→ 服务端（#5019 切源；`POST /api/admin/orders/auto-features`
 *   → 引擎 `curtain_calc.detect_auto_features`）；
 * - **提示**（notices）→ 服务端（#5036；引擎 `detect_auto_feature_notices`）；
 * - **算例**（算料配置页）→ 服务端（#5043 包 2a）。
 *
 * ⇒ 前端的本地判定实现 `detectAutoFeatures` **已无人调用**，随本单（#5035）删除。
 * 本模块**只保留**「不是判定」的那三件事：
 * 1. **门幅解析** `parseDoorWidth()`（#4877：**没有缺省门幅** —— 解析不到 ⇒ `null` ⇒ 不判）；
 * 2. **余量常量副本**：**已全部退场**（`SIDE_MARGIN` 随 #5030、`HEM_MARGIN` 随 #5043 包 2b）
 *    ⇒ 本文件只留**反向守卫**（它们**不得**回来；真值源在引擎侧，见下）；
 *    跨语言漂移守卫见下）+ 加工类型常量；
 * 3. **自动推导特征名清单** `AUTO_FEATURE_NAMES`（必须与 `processing_items` 目录（V83）**逐值对齐**，
 *    否则组合键永远匹配不到价 ⇒ 加工费恒 ¥0.00 —— issue #4592 的 P0）。
 *
 * ## 判据（每条能单独判红）
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | 1 | **前端不得持有余量常量副本**（`HEM_MARGIN` 已随 #5043 包 2b 删除），且引擎侧真值仍在 | 把 `export const HEM_MARGIN` 加回前端 ⇒ 红；删掉引擎侧定义 ⇒ 红 |
 * | 2 | `parseDoorWidth()` 缺失 / 不可解析 / 非正 ⇒ `null`（**不得回退任何缺省门幅**） | 回退到 2.8 ⇒ 红 |
 * | 3 | `DEFAULT_DOOR_WIDTH` / `resolveDoorWidth` **不得**回到本模块（反向守卫） | 把缺省门幅加回来 ⇒ 红 |
 * | 4 | 引擎「定宽买高」分幅公式**逐字**是 `math.ceil(window_width * fullness / fabric_width)`（**无宽方向余量**，issue #5030） | 引擎改公式而前端不跟 ⇒ 红 |
 * | 5 | `AUTO_FEATURE_NAMES` 与 V83 目录里标「自动推导特征」的行**逐值对齐**（双向、按序） | 清单多一项（如 `正幅`）⇒ 红 |
 *
 * ⚠️ **判定语义（分流 / 含褶倍 / 倒幅 / 几何矛盾）的判据已不在本文件** —— 它们随实现一起搬到
 * **服务端腿**：`backend/ai-agent-service/tests/test_production/test_auto_features.py`（判定）与
 * `test_auto_feature_notices.py`（提示）。**不是删掉，是换腿**。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { AUTO_FEATURE_NAMES, parseDoorWidth } from '@/lib/craft-auto-features'

/** 算料引擎源（真值源）：`backend/ai-agent-service/app/tools/curtain_calc.py` */
const CALC_SRC = resolve(
  __dirname,
  '../../../../../backend/ai-agent-service/app/tools/curtain_calc.py'
)
const source = readFileSync(CALC_SRC, 'utf8')

/**
 * 加工项目录种子（真值源）：`backend/admin-api/src/main/resources/db/migration/V83__seed_processing_item_catalog.sql`。
 * issue #4592：自动推导特征会**进加工费组合键** ⇒ 清单里多一个目录没有的名字 = 商家配不出该组合
 * = 组合价永远匹配不到（P0）。本文件据此把「清单 ↔ 目录」钉成**逐值对齐**。
 */
const V83_SEED_SRC = readFileSync(
  resolve(
    __dirname,
    '../../../../../backend/admin-api/src/main/resources/db/migration/V83__seed_processing_item_catalog.sql'
  ),
  'utf8'
)

/** 从 Python 源里取一个模块级浮点常量（取不到 ⇒ 直接失败，不静默跳过） */
function pyConst(name: string): number {
  const m = source.match(new RegExp(`^${name}\\s*=\\s*([0-9.]+)`, 'm'))
  if (!m) throw new Error(`curtain_calc.py 里找不到常量 ${name}（本守卫必须能读到真值）`)
  return Number(m[1])
}

/** 前端门幅库源（反向守卫用）：`frontend/admin-web/src/lib/craft-auto-features.ts` */
const LIB_SRC = resolve(__dirname, '../../../src/lib/craft-auto-features.ts')

describe('余量常量 —— **前端已无副本**（规则面迁服务端后的反向守卫）', () => {
  // 🔴 issue #5030 改判（用户 2026-09-21 裁定）：订单宽高 = **窗户宽高** ⇒ 成品宽 = 净窗宽、
  // 成品高 = 净窗高；宽度用料 = `窗宽 × 褶倍`（**不再另加左右覆盖余量**）。
  // ⇒ 原判据「SIDE_MARGIN（宽方向）= curtain_calc.SIDE_MARGIN（逐值比对）」的前提**已消失**
  //   （常量两侧都不存在了）⇒ 改成**同强度的反向守卫**：两侧都**不得**再定义这个常量。
  // 红证：在 `curtain_calc.py` 里加回 `SIDE_MARGIN = 0.3`（行首定义形态）⇒ 第一条红；
  //       在 `craft-auto-features.ts` 里加回 `export const SIDE_MARGIN = 0.3` ⇒ 第二条红。
  it('#5030 宽方向余量常量**不得复活**：引擎与前端库都不再有 SIDE_MARGIN 定义（反向守卫）', () => {
    // 只认**行首定义形态**（`^SIDE_MARGIN = …`）—— 引擎注释里以历史记录形式提到这个名字是允许的
    expect(source).not.toMatch(/^SIDE_MARGIN\s*=/m)
    const lib = readFileSync(LIB_SRC, 'utf8')
    expect(lib).not.toContain('export const SIDE_MARGIN')
  })

  // 🔴 issue #5043 包 2b 改判（用户 2026-09-21 裁定「规则面迁服务端」）：`HEM_MARGIN` 的
  // **前端副本已删除**（唯一消费者 `lib/door-width-plan.ts` 退场，规则由服务端给）
  // ⇒ 原判据「前端副本逐值等于引擎」的前提**已消失**。改成**同强度的反向守卫 + 引擎侧存活**：
  // ① 前端库**不得**再定义这个常量（副本回来 ⇒ 红）；
  // ② 引擎侧的定义必须**仍然存在且为正**（真值源被删 ⇒ 红 —— 否则「不许有副本」会退化成
  //    「两边都没有」的假绿）。
  it('#5043 余量常量：前端**不得再持有副本**，且引擎侧真值仍在（反向守卫 + 存活）', () => {
    const lib = readFileSync(LIB_SRC, 'utf8')
    expect(lib).not.toContain('export const HEM_MARGIN')
    expect(source).toMatch(/^HEM_MARGIN\s*=/m)
    expect(pyConst('HEM_MARGIN')).toBeGreaterThan(0)
  })

})

describe('门幅解析（SKU.doorWidth；**缺省已删除** —— 解析不到 ⇒ `null`）', () => {
  it('解析带单位的门幅（「2.8米」/「1.4米」/「2.8 m」）', () => {
    expect(parseDoorWidth('2.8米')).toBe(2.8)
    expect(parseDoorWidth('1.4米')).toBe(1.4)
    expect(parseDoorWidth('2.8 m')).toBe(2.8)
    expect(parseDoorWidth('2.8')).toBe(2.8)
  })

  // 红证（issue #4877，改前必红）：改前这四个输入都返回**缺省门幅 2.8**，判定面据此判超高/超宽
  // （真单实测：门幅 2.8 / 3.2 之差 = 「需接高」vs「单幅可做」两种相反结论）。
  it('#4877 缺失 / 不可解析 / 非正 ⇒ `null`（解析回退到任何默认值 ⇒ 红）', () => {
    expect(parseDoorWidth(undefined)).toBeNull()
    expect(parseDoorWidth(null)).toBeNull()
    expect(parseDoorWidth('')).toBeNull()
    expect(parseDoorWidth('加宽')).toBeNull()
    expect(parseDoorWidth('0')).toBeNull()
  })
})

/**
 * issue #4746 / #4877 —— **门幅真值源**（本仓「副本必须有同步守卫」纪律，同族 #4656）。
 *
 * 🔴 issue #4877 起：**前端不持有任何缺省门幅** —— SKU 未携带门幅 ⇒ `parseDoorWidth()` 返回 `null`
 * ⇒ 判定面**不判**（并显式告知 `missing-door-width`）。「静默按缺省 2.8 米推算」正是要替换掉的
 * 错误做法（真单实测：门幅 2.8 / 3.2 之差 = 「需接高」vs「单幅可做」两种相反结论）。
 *
 * 🔴 issue #5019 / #5036 / #5043 包 2a 起：**判定、提示、算例都已由服务端给** ⇒ 本模块只剩
 * 「门幅解析 + 余量常量副本 + 特征名清单」；「前端用本地常量判超高」这条旧偏差**已消灭**。
 *
 * ⚠️ **仍未做**：引擎试算的门幅是 `backend/ai-agent-service/app/api/internal.py::_FABRIC_WIDTH`
 * **硬编码**（分叉 #4746 / #4652）⇒ 前端**刻意不抄**那个值
 * （守卫 = `tests/unit_ci_workflows/test_fabric_width_truth_source.py`：前端出现该值字面量即红）。
 */
describe('#4746 / #4877 门幅真值源（**前端不持有缺省门幅** + 反向守卫）', () => {
  // 🔴 issue #4877（改判）：**前端不再持有缺省门幅** ⇒ 旧判据（`DEFAULT_DOOR_WIDTH` 逐值锚定算料
  // 引擎默认门幅）随常量一起删除。**反向守卫**：缺省一旦被重新引入（常量或解析回退）⇒ 红
  // （§17.3 ④「豁免必须有死亡条件」的同类形态：判据要能证明旧做法**没有回来**）。
  it('#4877 反向守卫：`DEFAULT_DOOR_WIDTH` / `resolveDoorWidth` **不得**回到本模块', () => {
    const lib = readFileSync(LIB_SRC, 'utf8')
    expect(lib).not.toContain('DEFAULT_DOOR_WIDTH')
    expect(lib).not.toContain('resolveDoorWidth')
  })

})

describe('#4662 分幅口径 —— 钉**引擎侧**真值源（前端判定已退场，本条守公式不被改走）', () => {
  /**
   * 真值源（算料引擎 `curtain_calc.py` 的**定宽买高**分支）：
   * `panels = math.ceil(window_width * fullness / fabric_width)`
   * ⇒ 「要分幅」⟺ `窗宽 × 褶倍 > 门幅` —— **这才是真正多花钱的地方**
   * （用户 2026-09-20 裁定 A：「超宽」要含褶倍；issue #5030：**宽方向无余量**）。
   */
  it('#4662 / #5030 判据与引擎**同源**：定宽买高分支逐字就是 ceil(窗宽 × 褶倍 ÷ 门幅)（漂移即红）', () => {
    // 逐字读真值源（不是抄现值）：引擎改了分幅公式而前端不跟 ⇒ 本断言必红
    expect(source).toContain(
      'panels = math.ceil(window_width * fullness / fabric_width)'
    )
    // 定高可用条件（判定 / 提示的几何依据）：`高 + 上下卷边 <= 门幅` ⇒ 定高买宽，否则回落定宽买高。
    // ⚠️ issue #4976 包 1b 起**上下卷边可配**：引擎读 `cfg["hem_margin"]`（默认值 = 常量 `HEM_MARGIN`）。
    // ✅ issue #5036 起**前端已退场**（判定与提示都由服务端给，且都读**该租户配置**）⇒ 本断言钉的是
    //    **引擎侧**的读取点；「前端用本地常量判」这条偏差已消灭（不是被绕过，是实现没了）。
    expect(source).toContain('if window_height + cfg["hem_margin"] <= fabric_width:')
  })

})

// ⚠️ issue #5036：提示（`missing-door-width` / `missing-fullness` / `cutting-mode-conflict`）自本单起
// 由**服务端**给 ⇒ 「几何矛盾 ⇒ 显式提示」这一整组判据迁到**服务端腿**（同一批断言，**不是删掉**）：
// `backend/ai-agent-service/tests/test_production/test_auto_feature_notices.py`。
// 页面链路（提示真的渲染出来 + 文案逐字）仍在本目录的 `orders-new-auto-features.test.tsx`。
describe('自动推导特征名清单 —— 只可能是 超高/超宽/倒幅，且与 V83 目录逐值对齐（#4592 / #4566）', () => {
  // 红证（issue #4592，修复前必红）：修复前 `AUTO_FEATURE_NAMES` = [..., '正幅']，
  // 而 V83 目录只种了 3 项 ⇒ 下面的 `toEqual` 必红。
  // 判据形态 = **逐值对齐**（清单 == 目录里标着「自动推导特征」的那几行，双向、按序），
  // 不是「清单 ⊆ 目录」—— 后者放不出「目录多了一项而清单少推」的偏差。
  it('#4592 清单与加工项目录（V83）**逐值对齐** —— 目录里没有的名字不得进组合键', () => {
    const autoRowsInCatalog = [...V83_SEED_SRC.matchAll(
      /\('(\d+)'::text,\s*'([^']+)'::text,\s*NULL::varchar\(16\),\s*'自动推导特征/g
    )].map((m) => m[2])
    // 目录侧自证：解析出的正是 V83 已种的三项（解析失配 ⇒ 本守卫必须红，不静默空跑）
    expect(autoRowsInCatalog).toEqual(['超高', '超宽', '倒幅'])
    // 清单侧：推导出的特征名与目录**逐值一致**（顺序也一致 —— 组合键归一化另有唯一实现）
    expect(AUTO_FEATURE_NAMES).toEqual(autoRowsInCatalog)
    // 「正幅」两侧都没有：目录没种 ⇒ 清单不得推（P0 的根因就是这个不对称）
    expect(V83_SEED_SRC).not.toContain("'正幅'")
    expect(AUTO_FEATURE_NAMES).not.toContain('正幅')
  })

  // issue #4566（用户 2026-09-19 裁定「工艺规格中的**工艺，定型**……直接通过加工项来勾选」）：
  // `定型` 是**手选**加工项，不再是自动推导特征 —— 其勾选态单独派生 `isShaped`。
  // 本清单同时是下单页滤出「手选列表」的**单一真值**（目录里必须存在这些项，
  // 但下单页的手选控件必须没有它们）。
  it('#4566 自动推导特征清单 = 超高/超宽/倒幅（**不含定型、也不含正幅**）', () => {
    expect(AUTO_FEATURE_NAMES).toEqual(['超高', '超宽', '倒幅'])
    expect(AUTO_FEATURE_NAMES).not.toContain('定型')
    // issue #4592：正幅是窗帘常态、不在加工项目录里 ⇒ 不得作为组合键加项
    expect(AUTO_FEATURE_NAMES).not.toContain('正幅')
  })

})
