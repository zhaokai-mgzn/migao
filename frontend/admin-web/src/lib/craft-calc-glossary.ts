/**
 * 「算料配置」页的**口径与术语说明**（issue #4975）—— 单一真值模块。
 *
 * 用户 2026-09-21：「算料配置里面涉及到的参数很多……需要有一些详细的说明性文案，同时一些专业术语的
 * 自动推算方式，比如**超高，超宽，倒幅，拼接 接高**，这些术语的说明和例子，告知用户我们系统是如何
 * 推算的，需要用到哪些参数，都可以在工序配置这个页面上说清楚」。
 *
 * ## 本模块的三条纪律（都可由 `tests/unit/lib/craft-calc-glossary.test.ts` 单独判红）
 *
 * 1. **文案里不出现数字**：所有数值（参数当前值、算例里的米数/门幅）一律**由真值渲染** ——
 *    参数值取自配置对象；算例的 `reason` 自 issue #5036 包 2a 起**逐字转发服务端**判定
 *    （`POST /api/admin/orders/auto-features`，入参带**该租户配置**）—— 本模块**不自己拼、也不自己判**。
 *    写死一个数 = 造第二份口径。
 * 2. **口径与引擎同源**：订单宽高 = **窗户宽高**（净窗宽 / 净窗高）⇒ 成品宽 = 净窗宽、
 *    成品高 = 净窗高。**「左右覆盖余量」这个概念已整体退场**（用户 2026-09-21 裁定，issue #5030
 *    ⇒ 常量 `SIDE_MARGIN` 与配置键 `side_margin` 一并删除），高方向只剩 `HEM_MARGIN`
 *    （上下卷边，配置键 `hem_margin`）。
 * 3. **键集必须覆盖引擎全部配置键**：引擎 `DEFAULT_CRAFT_CALC_CONFIG` 加一个键而不补文案 ⇒ 守卫红
 *    （这样 #4976 把 `hem_margin` 加进键集时，本模块会被**强制**同步补上说明）。
 *
 * 🔴 **2026-09-22 改判（issue #5130）**：`超高` / `超宽` 的判据改为
 * 「**净窗宽 / 净窗高 > 该租户的企业阈值参数**」（`oversize_width_threshold` /
 * `oversize_height_threshold`，默认 `6 / 4`）—— 用户裁定 D1 工艺分档 / D2 做成企业参数 /
 * D3 **替换**判定公式 / D10 三条旧判据一并退役。逐条留档见 {@link AUTO_FEATURE_TERMS}
 * 与 {@link GLOSSARY_FORMULAS} 的注释；判据的唯一实现在**服务端引擎**（本模块只解释与展示）。
 *
 * ⚠️ **自动推算 vs 手选，是本页最需要讲清的一件事**：`超高/超宽/倒幅` 由系统**推算**并进加工费
 * 组合键；`拼接/接高` 是**手选**特征，**系统不推算**（见 {@link MANUAL_FEATURE_TERMS}）。
 * 把这两类混在一起讲，正是商家看不懂这些参数的根因。
 */
import type { AutoFeaturesResult } from '@/lib/api'
import type { CraftCalcConfig } from '@/types'

/**
 * 标量配置键（表单里逐个数字输入框；键名 = 后端列名 = 算料引擎配置键，**逐字同名**）。
 * 清单**单一真值**在本模块 —— 页面不再自带一份（由守卫逐值读引擎源比对）。
 */
export const CALC_SCALAR_KEYS = [
  'per_fold_single',
  'margin_single',
  'margin_multi',
  'min_fullness',
  'hem_margin',
  'meters_rounding_step',
  'oversize_width_threshold',
  'oversize_height_threshold',
] as const

/** 标量配置键（类型 = 上面清单的成员，**不另写一份联合类型**） */
export type CalcScalarKey = (typeof CALC_SCALAR_KEYS)[number]

/** 一个配置键的页面文案（`label` 在表单上，`hint` 在输入框下，`impact` 在说明区块） */
export interface CalcParamCopy {
  /** 表单 label */
  label: string
  /** 输入框下的一行口径 */
  hint: string
  /** 说明区块里的「影响什么」 */
  impact: string
}

/**
 * **全部**引擎配置键的文案（不止六个标量键 —— `tiers` / `default_formula` /
 * `per_fold_mixed_times` 也在键集里，同样要有说明）。
 *
 * ⚠️ 文案里**不得出现数字**（判据 5）：数值由真值渲染。
 */
export const CALC_PARAM_COPY: Record<string, CalcParamCopy> = {
  per_fold_single: {
    label: '单色每折吃布（米）',
    hint: '褶数法：用料 = 每折吃布 × 褶数 + 余量',
    impact: '褶数法每片用料的乘数 —— 改它，所有走褶数法的单米数随之变',
  },
  per_fold_mixed_times: {
    label: '拼色每折吃布（米）',
    hint: '款式为拼色时，按拼次取每折吃布系数；未登记的拼次不插值、不静默退回单色',
    impact: '拼色款的用料系数（拼次 → 每折吃布）；余量与单色同一套，不随拼色变化',
  },
  margin_single: {
    label: '单开余量（米）',
    hint: '单开（一整幅）的包边余量',
    impact: '单开时每片的包边量（加在用料上）',
  },
  margin_multi: {
    label: '多开余量（米）',
    hint: '双开/四开的包边 + 对缝余量',
    impact: '多开时每片的包边 + 内侧对缝量；开数只改余量口径与每片宽，不改「总用料 = 每片用料 × 开数」',
  },
  min_fullness: {
    label: '褶倍下限',
    hint: '行业红线：不得低于系统默认值（低于它用料不足）',
    impact: '护栏：档位褶倍不得低于它（低于它用料不足 = 褶子太平、效果不达标）',
  },
  hem_margin: {
    label: '上下卷边（米）',
    hint: '高方向：定宽买高每幅的上下卷边（脚位 + 止口）',
    impact: '**高方向**的卷边量（引擎 `HEM_MARGIN`）：定高可行性、定宽买高每幅长、罗马帘都用它',
  },
  meters_rounding_step: {
    label: '进位步长（米）',
    hint: '用料只向上进位，不截断、不四舍五入',
    impact: '最终米数的进位步长（只向上）—— 防抹零少算钱',
  },
  oversize_width_threshold: {
    label: '超宽阈值（米）',
    hint: '净窗宽超过它 ⇒ 系统标「超宽」（该特征进加工费组合键）',
    impact:
      '**超宽**判据（按**净窗宽**比）：超过它 ⇒ 特征名进加工费组合键 ⇒ 加工费与标准档不同（工艺分档）',
  },
  oversize_height_threshold: {
    label: '超高阈值（米）',
    hint: '净窗高超过它 ⇒ 系统标「超高」（该特征进加工费组合键）',
    impact:
      '**超高**判据（按**净窗高**比）：超过它 ⇒ 特征名进加工费组合键；**不改用料米数、也不改加工类型**',
  },
  tiers: {
    label: '工艺档位',
    hint: '每档一个名义褶倍；按倍数法算料（如打孔）时用它',
    impact: '打孔（倍数法）等按档位取名义褶倍；档位名只是显示名，真值是这里的褶倍',
  },
  default_formula: {
    label: '兜底用料公式',
    hint: '韩褶 / 打孔按工艺自动推导公式，这里只在该推导不适用时兜底',
    impact: '工艺推导表缺失时的兜底公式（韩褶 ⇒ 褶数法、打孔 ⇒ 倍数法都由工艺推导，不走这里）',
  },
}

/** 一条术语说明 */
export interface GlossaryTerm {
  /** 术语名（与 ERP / 目录**逐字一致**，不"纠正"写法） */
  name: string
  /** 是什么 */
  definition: string
  /** 系统怎么判（符号式；数字由真值渲染） */
  criterion?: string
  /** 影响什么（米数 / 加工费 / 工序） */
  impact: string
  /** 边界与前提（照实登记，不粉饰） */
  boundary?: string
}

/**
 * **系统自动推算**的特征（与 `AUTO_FEATURE_NAMES` 同源 —— 由守卫钉住）。
 *
 * 三者都**进加工费组合键**（商家按「韩折+超宽+定型」这类组合配价），
 * 而 `正幅` **不推导**（它不在加工项目录里，推它 ⇒ 默认订单组合键永远匹配不到价）。
 *
 * 🔴 **2026-09-22 改判（issue #5130，用户裁定 D1 / D2 / D3 / D7 / D10）**：
 * `超高` / `超宽` 的判据由「与**门幅**比」（几何层）换成「与**企业阈值参数**比」
 * （`净窗高 > oversize_height_threshold` / `净窗宽 > oversize_width_threshold`，
 * 默认 `6 / 4`）—— 用户裁定 D2「`6 / 4` 是客户给的口径 ⇒ 做成企业参数」、D3「**替换**判定公式」。
 * 三条旧判据**一并退役**（D10）：
 * ① **#4661 按加工类型分流**（`定高买宽` ⇒ 只判超高；`定宽买高` ⇒ 只判超宽）—— 新判据与加工类型无关，
 *    两者**可同时为真**；`倒幅` 仍只在 `定宽买高` 时产出；
 * ② **#4662 超宽须含褶倍**（`窗宽 × 褶倍 > 门幅`）—— 新判据**不含褶倍**；
 * ③ **#4877 判定面门幅**（缺门幅 ⇒ 都判不了）—— 新判据**不读门幅**（门幅仍是几何层输入）。
 * ⚠️ 判据的唯一实现在**服务端**（`backend/ai-agent-service/app/tools/curtain_calc.py::detect_auto_features`）；
 * 本模块只**解释**与**展示**，不复制判据（旧文「超高 / 超宽 与门幅」的说法已随本条改判删除）。
 */
export const AUTO_FEATURE_TERMS: GlossaryTerm[] = [
  {
    name: '超高',
    definition: '**净窗高**超过「超高阈值」（该租户的企业参数）—— 超高的窗走特殊工艺档',
    criterion: '净窗高 > 超高阈值（`oversize_height_threshold`）',
    impact:
      '① 进加工费组合键（商家按含它的组合配价 ⇒ 加工费与标准档不同）；② **不改用料米数、也不改加工类型**',
    boundary:
      '判据是**客户口径**（企业参数，可配），非 ERP 实证 ⇒ 系统标注为「推算」；改阈值 ⇒ 之后判定的单随之变',
  },
  {
    name: '超宽',
    definition: '**净窗宽**超过「超宽阈值」（该租户的企业参数）—— 超宽的窗走特殊工艺档',
    criterion: '净窗宽 > 超宽阈值（`oversize_width_threshold`）',
    impact:
      '① 进加工费组合键；② 与**分幅**是两件事：分幅由几何决定（决定米数），超宽只看**绝对宽度**（决定取价档）',
    boundary:
      '判据是客户口径（企业参数，可配）；它只看**净窗宽**这一个量，与几何层（分幅 / 用料）互不影响',
  },
  {
    name: '倒幅',
    definition: '定宽买高时布要旋转九十度用，布的门幅方向变成窗帘的宽度方向，花型因此是倒的',
    criterion: '加工类型 = 定宽买高（唯一推导，不设手选项）',
    impact: '进加工费组合键；每幅长按「成品高 + 上下卷边」算',
    boundary: '与它相对的「正幅」是窗帘常态，**不推导、不进组合键**',
  },
]

/**
 * **手选**特征（**系统不推算**）。
 *
 * ⚠️ **死亡条件**：本段写的「当前只影响加工费、不触发工序」钉的是**当下**口径 ——
 * 一旦 issue #4569 裁定改为「加工项也触发工序」，本段必须连同守卫一起改判。
 */
export const MANUAL_FEATURE_TERMS: GlossaryTerm[] = [
  {
    name: '拼接',
    definition: '把两幅布横向接起来凑够宽度（口语也叫「对缝」）—— 由商家或顾客**手选**，系统不推算',
    impact:
      '① 进加工费组合键；② 作为加工项勾选时，**当前只影响加工费，不触发工序**（系统不会因此多排一道工序）',
    boundary: '「拼接」与「拼色」「拼N次」是三件不同的事，见下面的近义词族',
  },
  {
    name: '接高',
    definition: '成品高度不够时接一段布补高，按明细行归属（主布接高 / 配布边接高）—— **手选**，系统不推算',
    impact: '插「接高」工序 + 加工费（按幅计）；**不改用料米数**',
    boundary: 'ERP 的「双眼皮接高」含义**待查明**（客户亦不明）⇒ 系统不凭字面推',
  },
]

/** 近义词族（同一句话里最容易搅在一起的概念 —— 它们不在同一层） */
export const TERM_FAMILY: GlossaryTerm[] = [
  {
    name: '正幅',
    definition: '定高买宽 = 布按高度方向用，花型正着 —— 窗帘的常态',
    impact: '**不作为加工项加项**（它不在加工项目录里）：推它会让每一张默认订单的组合键都匹配不到价',
  },
  {
    name: '定型',
    definition: '打褶后蒸烫固定褶形 —— **手选**加工项（勾选态就是「是否定型」的真值来源）',
    impact: '影响工序（不定型 ⇒ 移除定型与复烫）与加工费；不是由尺寸推算出来的',
  },
  {
    name: '拼色',
    definition: '款式 = 拼色（主布 + 配布分料做一条帘子）—— 它是**款式**，不是加工项',
    impact: '决定「每折吃布」走哪一档系数（单色档 / 拼色档）',
  },
  {
    name: '拼N次',
    definition: '特殊选项里的拼次（一条拼接缝 = 拼一次）—— 它是**选项**，不是款式',
    impact: '与「款式 = 拼色」一起决定每折吃布系数；未登记的拼次不插值（如实告警）',
  },
  {
    name: '对缝',
    definition: '多开时每片内侧要缝合的那道缝 —— 它是**余量口径**的一部分（含在多开余量里）',
    impact: '不单独配置：改「多开余量」即同时改包边与对缝量',
  },
]

/**
 * **特殊选项**（下单页「特殊选项」勾选区里的六项 —— issue #4986）。
 *
 * 用户 2026-09-21：「特殊选项里面被选中的 6 个术语也加进去」。
 *
 * 🔴 这六项**不在同一层**（商家最容易搞混的正是这一点）：
 *
 * | 术语 | 影响用料 | 影响工序 | 影响对客价 | 影响计件 |
 * |---|---|---|---|---|
 * | 拼1次 / 拼2次 | ✅ 每折吃布按拼次取系数 | ✅ 插条件工序 | ✅ 按套 | — |
 * | 拼3次 | ⚠️ **纸表未登记系数** ⇒ 拼色时算料直接拒绝 | ✅ 插条件工序 | ✅ 按套 | — |
 * | 接高 | ❌ 不改米数 | ✅ 插条件工序 | ✅ 按套 | — |
 * | 双眼皮接高 | ❌ | ✅ **与「接高」同一道工序** | ✅ 按套 | — |
 * | 一分为二 | ❌ | ❌ **不加工序** | ❌ 按设计未定价 | ⚠️ 只有**历史**系数档 |
 *
 * ⚠️ **工序映射逐值取自真值源** `backend/ai-agent-service/app/production/routing.py` 的
 * `SPECIAL_OPTION_ROUTINGS`（由守卫读源比对，改一处必红）—— 本模块**不**自己定义映射。
 */
export interface SpecialOptionTerm extends GlossaryTerm {
  /**
   * 勾选后插哪道**条件工序** —— **逻辑工序名**（如 `接高`、`拼1次`）；`null` = **不加工序**。
   *
   * 🔴 **只许写逻辑名，不得写变体名**（`接高-布` / `拼1次-布`）：变体名是**按部位**派生的
   * （布帘 `-布` / 纱帘 `-纱` / 帘头 `-帘头`），前端硬编码它 = 把部位写死。守卫
   * `tests/unit_ci_workflows/test_op_name_registry_guard.py` 判据① 直接判红
   * （本模块第一版就是被它抓到的）。真值源给的是**变体名**，本字段 = 它的**逻辑名**
   * （由守卫按 `变体名.split('-')[0]` 逐值比对）。
   */
  operation: string | null
  /** 插在哪个**逻辑工序**之后；`null` = 不加工序（同上：不得写变体名） */
  after: string | null
  /** 影响哪些层（判据用：**至少一层**，不许出现「什么都不影响」的说明） */
  layers: Array<'用料' | '工序' | '对客价' | '计件'>
}

/** 用户点名的六项特殊选项（顺序即页面顺序，与下单页勾选区一致） */
export const SPECIAL_OPTION_TERMS: SpecialOptionTerm[] = [
  {
    name: '拼1次',
    operation: '拼1次',
    after: '布三边',
    layers: ['用料', '工序'],
    definition: '拼色时的一条拼接缝（口语「拼一次」）—— 它是**特殊选项**，勾了才生效',
    impact:
      '① 进用料：款式为拼色时，每折吃布按拼次取系数；② 插一道条件工序「拼1次」（部位由该行决定，在「布三边」之后）',
    boundary: '选项名是**匹配键**：库里改名而这里不跟 ⇒ 工序不加、用料系数也取不到（不是静默少一道，是算料直接拒绝）',
  },
  {
    name: '拼2次',
    operation: '拼2次',
    after: '布三边',
    layers: ['用料', '工序'],
    definition: '拼色的两条拼接缝（口语「双拼色」）',
    impact: '与拼1次同理：进用料系数（按拼次取）+ 插条件工序「拼2次」（部位由该行决定，在「布三边」之后）',
    boundary: '拼次是**数字**、选项名只是载体：登记了系数的是拼1次与拼2次两档，别的拼次见「拼3次」',
  },
  {
    name: '拼3次',
    operation: '拼3次',
    after: '布三边',
    layers: ['工序'],
    definition: '拼色的三条拼接缝',
    impact: '插条件工序「拼3次」（部位由该行决定，在「布三边」之后）；**用料系数纸表未登记**',
    boundary: '拼色 + 拼3次 时算料**直接拒绝**（**不插值**、也不静默退回单色）—— 纸表只登记了两档，缺依据就不猜',
  },
  {
    name: '接高',
    operation: '接高',
    after: '精裁',
    layers: ['工序', '对客价'],
    definition: '成品高度不够时接一段布补高，按明细行归属（主布接高 / 配布边接高）',
    impact: '插条件工序「接高」（部位由该行决定，在「精裁」之后）+ 对客按套计价；**不改用料米数**',
    boundary: '「接高」作为**加工项**勾选时只进加工费组合键、**不插工序**（加工项与特殊选项是两条路）',
  },
  {
    name: '双眼皮接高',
    operation: '接高',
    after: '精裁',
    layers: ['工序', '对客价'],
    definition: 'ERP 的另一个接高勾选项',
    impact: '与「接高」**同一道工序**（同锚点「精裁」）+ 对客按套计价',
    boundary: '含义**待查明**（客户亦不明）⇒ 系统不凭字面推；勾它与勾「接高」在工序与价格上等价',
  },
  {
    name: '一分为二',
    operation: null,
    after: null,
    layers: ['计件'],
    definition: '把一个部件一分为二（对客价按设计**未定价**）',
    impact: '**不加工序**；只有一条**历史计件系数**档 —— 自系数口径退场后**零消费**（新报工不乘、历史报工按当时快照仍乘）',
    boundary: '⇒ 勾它今天**不改变**订单金额、也不改变加工单工序数（与「接高」「拼N次」的差别就在这）',
  },
]

/** 公式说明（**只写符号**，不写数 —— 数值由真值渲染） */
export const GLOSSARY_FORMULAS: { name: string; formula: string; note: string }[] = [
  {
    name: '褶数法（韩褶公式）',
    formula: '每片用料 = 每折吃布 × 每片褶数 + 每片余量；总用料 = 每片用料 × 开数；每片宽 = 窗宽 ÷ 开数',
    note: '韩褶按工艺自动走这条；折数由倍数意图反算，并按开数取整（对开取偶数、四开取四的倍数）',
  },
  {
    name: '倍数法（褶倍数公式）',
    formula: '总用料 = 窗宽 × 褶倍',
    note: '打孔等按工艺走这条；褶倍取自工艺档位，且不得低于褶倍下限',
  },
  {
    name: '定宽买高：分幅',
    formula:
      '幅数 = ⌈窗宽 × 褶倍 ÷ 门幅⌉（向上取整）；每幅长 = 窗高 + 上下卷边（有花距再加一个花距）；总用料 = 幅数 × 每幅长',
    // 🔴 **2026-09-22 改判（issue #5130）**：旧 note 逐字写着
    // 「成品高加上下卷边超过门幅时，引擎自动从「定高买宽」回落到这条 —— **这就是超高会改米数的原因**」
    // —— 替换判据后这句话**是错的**：「超高」现在是**企业阈值特征**（只看净窗高），
    // **不驱动用料、也不驱动加工类型**；回落只由**几何**（成品高 + 卷边 vs 门幅）决定。
    // ⇒ 按改判纪律**原地留档 + 改写**（不是删掉旧文字让后人不知道口径变过）。
    note: '成品高加上下卷边超过门幅时，引擎自动从「定高买宽」回落到这条（**几何硬约束**）—— ⚠️ 它与「超高」这个特征名**无关**：超高只看净窗高与该租户的超高阈值，不改变用料米数、也不改变加工类型',
  },
  {
    name: '向上进位',
    formula: '最终米数按「进位步长」向上进位（不截断、不四舍五入）',
    note: '只作用在最终回传的米数上；分幅数（几幅布）是整数，不套这条',
  },
]

/**
 * 算例输入（**示例几何**，不是真值）。
 *
 * 🔴 **2026-09-22 改判（issue #5130）**：旧 `doorWidth` 字段**已删除** —— 判定面
 * （`超高` / `超宽`）改成与**企业阈值参数**比之后，算例里**不再需要门幅**
 * （`门幅` 只剩几何层的分幅 / 用料与「几何矛盾」提示，与本节的**特征算例**无关）。
 * 旧值（`doorWidth: 2.8`）曾让本模块被读成「前端持有一份缺省门幅」⇒ 反向守卫
 * （`tests/unit/lib/craft-calc-glossary.test.ts` 判据 9 与
 * `tests/unit_ci_workflows/test_fabric_width_truth_source.py`）一字未放宽。
 *
 * ⚠️ 取值必须**真的超过**引擎默认阈值（否则服务端判不出特征、算例会空转）——
 * 改默认阈值时本算例要一起改（守卫 =
 * `tests/unit/lib/craft-calc-glossary.test.ts` 的「算例覆盖三个特征」判据）。
 */
export const GLOSSARY_EXAMPLE = {
  width: 6.5,
  height: 4.5,
} as const

/** 一条自动推算算例（`reason` **逐字来自服务端判定** —— 与下单页同一份文案） */
export interface AutoFeatureExample {
  name: string
  /** 举例的输入（含真实数字，由常量/配置渲染） */
  given: string
  /** 系统的判定依据（**服务端产出**；本模块只**转发**，不自己拼） */
  reason: string
}

/**
 * 三个自动推算特征的算例 —— **不自己拼文案、也不自己判**：`reason` **逐字转发**服务端
 * `POST /api/admin/orders/auto-features` 的返回（issue #5036 包 2a）。
 *
 * 🔴 迁移前它调**前端** `detectAutoFeatures`，而那个函数读的是**模块常量副本**（宽 / 高余量）
 * ⇒ #5005 把 `hem_margin` 做成可配之后，本页「改完参数保存后，这里的数字会跟着变」的承诺是**假的**。
 * 现在判定入参带**该租户配置** ⇒ 承诺成真。
 *
 * 🔴 **issue #5130 改判**：`given` 由「窗宽/窗高 + 褶倍 + 某商品门幅」改成
 * 「净窗宽/净窗高 + **该租户的阈值**」—— 阈值的数值**由真值渲染**（`config`），不写死。
 */
export function buildAutoFeatureExamples(
  config: CraftCalcConfig,
  fixedHeightFeatures: readonly AutoFeaturesResult['auto_features'][number][],
  fixedWidthFeatures: readonly AutoFeaturesResult['auto_features'][number][]
): AutoFeatureExample[] {
  const givenOf = (name: string): string => {
    if (name === '超高') {
      return `举例：净窗高 ${GLOSSARY_EXAMPLE.height} 米 · 超高阈值 ${config.oversize_height_threshold} 米（企业参数，可改）`
    }
    if (name === '超宽') {
      return `举例：净窗宽 ${GLOSSARY_EXAMPLE.width} 米 · 超宽阈值 ${config.oversize_width_threshold} 米（企业参数，可改）`
    }
    return '举例：加工类型「定宽买高」'
  }

  return [...fixedHeightFeatures, ...fixedWidthFeatures].map((f) => ({
    name: f.name,
    given: givenOf(f.name),
    reason: f.reason,
  }))
}

/** 配置键 → 说明区块里该条的锚点 id（参数旁「说明」链接指向它） */
export function glossaryAnchorOf(key: string): string {
  return `glossary-param-${key}`
}

/** 术语名 → 说明区块里该条的锚点 id */
export function glossaryTermAnchorOf(name: string): string {
  return `glossary-term-${name}`
}

/**
 * 特殊选项名 → 说明区块里该条的锚点 id（**独立命名空间**）。
 *
 * ⚠️ 必须分开：`接高` 在「手选特征」与「特殊选项」两组里都有 —— 共用 `glossary-term-*`
 * 会让两个条目抢同一个 DOM id（锚点跳错、HTML 非法）。守卫
 * `tests/unit/lib/craft-calc-glossary.test.ts` 的判据 8 钉住这一点。
 */
export function glossaryOptionAnchorOf(name: string): string {
  return `glossary-option-${name}`
}

/**
 * **余料回收**域的术语（issue #5146）—— 「参数总览 → 余料回收」**就地查**（`migao-dev-flow` §22 P5）。
 *
 * ⚠️ **独立命名空间**（同 {@link glossaryOptionAnchorOf} 的理由）：`余料` 这类词在别处也可能出现，
 * 与算料域 / 特殊选项域共用 `glossary-term-*` 会让两个条目抢同一个 DOM id。
 *
 * ⚠️ 文案里**不出现数字**（同本模块三条纪律 ①）：尺寸、米数、金额一律由真值渲染
 * —— 本域的参数默认值**就是空**，写死任何一个数都会立刻变成假话。
 */
export const REMNANT_TERMS: GlossaryTerm[] = [
  {
    name: '余料',
    definition: '裁剪之后没被成品用掉、但还**能再用**的布 —— 只有两种形态：门幅余料与端部余料',
    criterion: '余料 = 「这一行已经按行长度整段领下来的布」里的空处',
    impact: '本系统的余料**不是资产**：只记实物可用性（尺寸 / 来源 / 缸号 / 状态），不计价、不进库存金额',
    boundary: '小于物理分辨率（按厘米报的宽高之下的碎边）不登记 —— 那不是余料，是边角碎屑',
  },
  {
    name: '门幅余料',
    definition: '一行料没把门幅占满时，剩下的那条**竖带**',
    criterion: '长 = 该行的行长度；宽 = 门幅 − 该行各块占门幅宽之和',
    impact: '它的米数**当初已随计价口径被客户付过**（每幅按整门幅算）⇒ 用它做小件 = 把已计过价的东西用起来',
    boundary: '行内正好铺满门幅 ⇒ 没有门幅余料（这时的节省已经体现在领料米数上）',
  },
  {
    name: '端部余料',
    definition: '一行里**较短**的那块料，尾部剩下的那条**横带**',
    criterion: '长 = 行长度 − 该块沿卷长；宽 = 该块占门幅宽',
    impact: '同上：它也在已领下来的那一段里 ⇒ 用掉它不新增领料',
    boundary: '行内各块等长 ⇒ 没有端部余料',
  },
  {
    name: '缸号',
    definition: '同一次染色的批号（批次上的一列）',
    impact: '**不同缸号之间可能有色差** ⇒ 余料匹配**优先取同缸号**；取不到同缸号时退到「同色」（同一颜色规格），并在匹配结果里标出来',
    boundary: '缸号可以为空（有些供应商不提供）⇒ 空缸号既不算「相同」也不算「不同」，只按同色判定',
  },
  {
    name: '小件',
    definition: '绑带 / 帘头 / 抱枕这一类**由余料做成**的小配件（系统里以它们的**工序名**为键）',
    criterion: '订单勾了「余料做绑带」「余料做帘头」「抱枕」等特殊选项 ⇒ 该行就有了小件需求',
    impact: '小件需求有了之后，系统先从**余料台账**里找料；找得到就不新领料（不新增批次消耗）',
    boundary: '特殊选项到工序的对应关系不在这里另写一份 —— 它取自工序路线那张表（唯一真值源）',
  },
  {
    name: '小件用料尺寸',
    definition: '做一个小件需要多大一块布：用料长（沿卷长）× 用料宽（沿门幅）',
    criterion: '余料能装下 ⇔ 两条边**都不小于**需求（不旋转、不放宽）',
    impact: '**本参数默认值为空**：填了才启用该小件的余料匹配；不填就完全不产生匹配建议（不会凭空推荐）',
    boundary: '改它**不改对客价、不改加工费、不改成品尺寸** —— 它只决定「余料能不能拿来做这个小件」',
  },
  {
    name: '余料回收额',
    definition: '余料被用掉时，冲减**用它的那张单**面料成本的金额',
    criterion: '回收额 = 用掉米数 × **该批次当时**均价（均价随行快照，事后改价不改历史读数）',
    impact: '只进**内部成本口径**（面料成本 = 领料成本 − 余料回收）；对客售价与加工费一字不动',
    boundary: '来源批次没记均价 ⇒ 拒绝回收（宁可为失败，不许估一个价）',
  },
  {
    name: '客户带走',
    definition: '订单勾了「余料带回」⇒ 余料归**客户**（行业做法：企业零损失）',
    criterion: '该订单的余料状态落「客户带走」',
    impact: '照样登记（账要平），但**不进可用池、不参与匹配、不计回收**',
    boundary: '客户带走的余料企业**无权处置** ⇒ 不能报废、也不能被拿来回收',
  },
  {
    name: '报废',
    definition: '超期或尺寸不合适的余料核销掉',
    criterion: '状态转「已报废」，并记下**谁、何时、为什么**',
    impact: '报废米数进报废率（报废率 = 报废米数 ÷ 余料总米数），便于回头看「还剩多少能用」',
    boundary: '只有「可用」的余料能报废；同一块不能既报废又回收（状态机互斥）',
  },
]

/**
 * 余料回收术语 → 说明区块里该条的锚点 id（**独立命名空间**）。
 *
 * 独立命名的理由同 {@link glossaryOptionAnchorOf}：`余料` / `小件` 这类词在本模块的
 * 算料域与特殊选项域都可能出现，共用 `glossary-term-*` 会让两个条目抢同一个 DOM id。
 */
export function glossaryRemnantAnchorOf(name: string): string {
  return `glossary-remnant-${name}`
}
