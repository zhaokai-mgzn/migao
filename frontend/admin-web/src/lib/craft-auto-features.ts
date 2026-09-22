/**
 * 下单页「自动识别」的**残余面**（issue #4526 包 B 的遗产；issue #5035 收口）—— 纯函数，无副作用。
 *
 * 🔴 **本模块已不做判定**：用户 2026-09-21 的裁定把整条链搬到了**服务端** ——
 * **判定**（#5019 切源）/ **提示**（#5036）/ **算例**（#5043 包 2a）都由服务端给，前端只**展示**。
 * ⇒ 前端的本地判定实现 `detectAutoFeatures` 已无人调用，随本单（#5035）**删除**。
 * 本模块只剩三件**不是判定**的事：
 * 1. `parseDoorWidth()` —— 门幅解析（#4877：**没有缺省门幅**，解析不到 ⇒ `null` ⇒ 不判）；
 * 2. `HEM_MARGIN` / `CUTTING_MODE_*` —— **常量副本**（各有跨语言守卫）；
 *    ⚠️ 宽方向余量 `SIDE_MARGIN` 已按 issue #5030 **整体退场**（订单宽 = 净窗宽 ⇒ 宽方向没有余量）；
 * 3. `AUTO_FEATURE_NAMES` —— 自动推导特征名清单（须与 `processing_items` 目录（V83）**逐值对齐**）。
 *
 * ⚠️ **`定型` 不在清单里**（issue #4566，用户 2026-09-19 裁定「工艺、定型…直接通过加工项来勾选」）：
 * 它是**手选**加工项，勾选态即 `isShaped`。
 *
 * ⚠️ **`正幅` 不在清单里**（issue #4592，用户 2026-09-19 裁定「正幅不用作为加工项的加项，
 * 但是倒幅是需要的」）：清单里的名字会**进加工费组合键**，而 `正幅` **不在** `processing_items`
 * 目录（V83 只种了 `超高` / `超宽` / `倒幅`）⇒ 商家配不出含它的组合 ⇒ 组合键永远匹配不到价
 * ⇒ 加工费恒 ¥0.00（P0）。本清单因此与 V83 目录**逐值对齐**。
 *
 * ⚠️ **本文件是 admin-web 专属**，刻意**不放进** `lib/craft-display.ts`：那个文件在
 * admin-web / mini-app / bmini-app **三端逐字同源**（设计 §4.9「一份 spec，三处渲染」，
 * 当前三份 sha 全等、**尚无同步守卫** = 既有 issue #4393）。把下单页的**取价口径**塞进去
 * 会静默破坏那个不变量；而且这些常量是**取价逻辑**，不是**展示**逻辑（YAGNI：另两端今天不用它）。
 */

/**
 * ⚠️ **宽方向没有余量常量**（用户 2026-09-21 裁定，issue #5030）：订单宽 = **净窗宽**、
 * 成品宽 = 净窗宽 ⇒ 超宽判据 = `窗宽 × 褶倍 > 门幅`。原先的 `SIDE_MARGIN = 0.3`
 * （左右覆盖余量）与配置键 `side_margin` **一并退场**，不得以任何名字复活。
 */

/**
 * ## 门幅口径（issue #4877 **改判：前端不再持有「缺省门幅」**）
 *
 * | 口径 | 值 | 来源 | 谁在读 |
 * |---|---|---|---|
 * | 商品/SKU 门幅（**权威**） | 商品可配（种子 2.8；窄幅布 1.4） | 商品 `doorWidths` ⇒ `product_skus.door_width` | 本页判定（{@link parseDoorWidth}）、规则（`door-width-plan.ts`）、SKU 定位 / 加工费组合键 |
 * | 引擎**端点**门幅 | **硬编码**（`backend/ai-agent-service/app/api/internal.py` 的 `_FABRIC_WIDTH`） | 算料试算通路 | **尚未按 SKU 门幅接线** = 分叉 #4652 |
 *
 * 🔴 **「缺省门幅」已删除**（issue #4877；用户 2026-09-21 裁定「如果所有门幅都不满足，
 * 那必然走接高」+「加工类型是显式输入」）：SKU 未携带门幅 ⇒ {@link parseDoorWidth} 返回 `null`
 * ⇒ **几何层**判不了（显式告知：②`door-width-missing` + ①`size-door-width-missing`）、
 * 规则面返回 `undecidable` —— **不得**回退任何默认门幅继续推算。
 * 旧行为「静默按缺省门幅判超高/超宽」正是 #4877 要替换掉的错误做法（真单实测：同一张 3.0×2.75 的
 * 单子，门幅按 2.8 / 3.2 之差会得到「需接高」与「单幅可做」两种相反结论，用料 9.15 / 6.3 米）。
 *
 * 🔴 **2026-09-22 改判（issue #5130）**：**判定面**已与门幅**彻底脱钩** —— 「超高 / 超宽」的判据
 * 换成 `净窗宽/净窗高 > 该租户的企业阈值参数`（`oversize_width_threshold` / `oversize_height_threshold`）。
 * ⇒ 门幅**只剩几何层**的三处用途：用料（分幅 / 定高可行性）、加工类型、门幅规则面，
 * 以及**几何矛盾提示**（`cutting-mode-conflict`）。旧判定面口径（#4661 按加工类型分流 /
 * #4662 超宽含褶倍 / #4877 缺门幅不判）**三条一并退役** —— 留档见引擎
 * `backend/ai-agent-service/app/tools/curtain_calc.py::detect_auto_features` 的 docstring。
 *
 * ⚠️ **口径分裂照实登记**：引擎端点按它自己的硬编码值算分幅，本页按 **SKU 门幅** 判
 * ⇒ 两者可能不一致（组合键与实际算料对不上）。**权威 = SKU/商品门幅**；引擎侧改为**接收**该值
 * = **分叉 #4652**（本单不动 ai-agent）。⇒ 本文件**刻意不抄**那个值
 * （抄一份 = 第二份会漂移的口径，同族 #4656）：守卫
 * `tests/unit_ci_workflows/test_fabric_width_truth_source.py`（前端出现该值字面量即红）。
 */

/**
 * **自动推导**特征名清单（**推导产生**，不是商家勾选项 —— 判据 8：出现手选项 ⇒ 红）。
 *
 * ⚠️ 单一真值：下单页用**本清单**把加工项目录里这几项**滤出**手选列表
 * （它们在目录里**必须存在** —— 商家配「加工费组合」时要能选到 `韩折+超高+定型` 这种名字，
 * 但下单页的手选控件必须没有它们）。**别在下单页再抄一份名字数组**。
 *
 * 🔴 **本清单必须与 `processing_items` 目录（V83）逐值对齐**（issue #4592，P0）：
 * 推导出的特征会**进加工费组合键**（`processingDetailsOf` 把它并进
 * `processingInfo.processingItems[]`，服务端 `ProcessingFeeQueryService.featureNames()` 只读这个数组），
 * 而商家只能在**目录已种**的项里配组合 ⇒ 清单里多出一个目录没有的名字
 * （`正幅`）⇒ **组合键永远匹配不到价** ⇒ 加工费恒 ¥0.00。
 * V83 已种的自动推导特征 = `超高` / `超宽` / `倒幅` **三项**，本清单与它**一一对应**。
 *
 * ⚠️ `正幅` **不在**本清单里（issue #4592，用户 2026-09-19 裁定「窗帘默认都是正幅，
 * **正幅不用作为加工项的加项**」）：默认加工类型就是 `定高买宽`（= 正幅）⇒ 若推导它，
 * **每一张默认订单**的组合键都会被它污染。`正幅` 既不在目录里、也不进组合键。
 *
 * ⚠️ `定型` **不在**本清单里（issue #4566，用户 2026-09-19 裁定）：它是**手选**加工项
 * （ERP 91 项加工费名单里的特征词），其勾选态就是 `isShaped` 的真值来源 —— 与
 * 「按宽高 vs 门幅推导」的超高/超宽不是一类东西。
 */
export const AUTO_FEATURE_NAMES = ['超高', '超宽', '倒幅'] as const

/** 自动推导特征名（类型 = 上面清单的成员，**不另写一份联合类型**） */
export type AutoFeatureName = (typeof AUTO_FEATURE_NAMES)[number]

/** 一条自动识别特征（`source` 一律「推算」：推理非实证，照实标注） */
export interface AutoFeature {
  name: AutoFeatureName
  source: '推算'
  /** 可读依据（哪两个数比出来的）—— 商家要能核对判定 */
  reason: string
}

/** 取有限正数（容忍 JSON 里以字符串承载的数字）；其余 ⇒ `null` */
function positiveNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = typeof value === 'number' ? value : Number(String(value).trim())
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

/**
 * 门幅解析 —— 解析 SKU 的 `doorWidth`（可带单位，如 `2.8米`）。
 * 缺席 / 不可解析 / 非正数 ⇒ `null`（**不默认成任何值**）。
 *
 * ⚠️ **门幅选择规则必须用本函数**（`door-width-plan.ts`）：缺失 = **不可判定** ——
 * 「静默按缺省 2.8 推算」正是 issue #4877 要替换掉的错误做法。
 */
export function parseDoorWidth(doorWidth: unknown): number | null {
  if (doorWidth === null || doorWidth === undefined) return null
  const match = String(doorWidth).match(/(\d+(?:\.\d+)?)/)
  if (!match) return null
  return positiveNumber(match[1])
}

/** 加工类型 `定高买宽` —— **高**方向受门幅约束（**宽**按米买、无上限）⇒ 只判 `超高` */
export const CUTTING_MODE_FIXED_HEIGHT = '定高买宽'
/** 加工类型 `定宽买高` —— **宽**方向受门幅约束（分幅数 = `(宽+余量)×褶倍 ÷ 门幅`）⇒ 只判 `超宽` */
export const CUTTING_MODE_FIXED_WIDTH = '定宽买高'

/**
 * 系统识别的**提示**（issue #4662 / #5036；**issue #5130 改判**）—— 只说明**系统实际会按哪种算**，
 * **不是特征**：不进 `AUTO_FEATURE_NAMES`、不进加工费组合键、不影响判定结果
 * （组合键只能含 `processing_items` 目录里有的名字 —— #4592 的 P0）。
 *
 * 🔴 **issue #5036 起：本类型描述的是「服务端返回什么」**（用户 2026-09-21 裁定「提示统一迁移到
 * 服务端；**未来 agent 也需要**」）—— 提示由引擎 `curtain_calc.detect_auto_feature_notices` 产出，
 * 读的是**该租户配置**的 `hem_margin`；前端只**展示**（`api.ts::AutoFeaturesResult.notices`）。
 *
 * 🔴 **issue #5130 改判：只剩 `cutting-mode-conflict` 一条**（它说的是**几何层**：
 * 成品高 + 卷边 vs 门幅 ⇒ 引擎实际按哪种算，仍然为真）。两条**已退役**：
 * ① `missing-door-width`（旧文案「该 SKU 未维护门幅 ⇒ **超高/超宽都判不了**」）——
 *    新判据（净窗宽/净窗高 vs **企业阈值参数**）**不读门幅** ⇒ 那句话成了假话；
 * ② `missing-fullness`（旧文案「缺褶倍 ⇒ **未判超宽**」）—— 新判据**不含褶倍** ⇒ 同样是假话。
 * 「门幅未维护」的告知改由**门幅规则面**承担（下单页 `door-width-missing` /
 * `size-door-width-missing` 徽标 + `door-width-plan` 端点 —— 它们说的是**几何层**能不能算，仍为真）。
 */
export interface AutoFeatureNotice {
  kind: 'cutting-mode-conflict'
  /** 可读依据（哪两个数比出来的 + 前提）。口径一律来自算料引擎的同款判据，**前端不编** */
  reason: string
}


