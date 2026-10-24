// case_ids: PG-046, PG-091
//
// 「部位规格**上屏**」判据 —— 母单 #6901 面① 的判据补丁（issue #6999）。
//
// 为什么要有这个文件（**实测**的假绿形态，不是推断）：#6901 交付了「部位规格」这一块
// （扫后屏 `#wh5-position-spec`「本部位生产信息」+ 机台屏屏一的新增规格行），
// 但当时的判据只钉了**下发了**（后端键集、共享表内容），没钉**上屏了**。
// 独立复核在**仓外隔离副本**里注入两种「改回改前形态」：
//   · 注入 A：`src/position-spec.mjs::specRows` 恒空
//     ⇒ 扫后屏「本部位生产信息」**整块一个字节都不渲染**；
//   · 注入 C：`src/machine.mjs::detailRows` 摘掉**全部** #6901 新增规格行
//     （即删掉那段 `...POSITION_SPEC_KEYS.filter(…).map(…)` 展开）。
// 两种注入下 `node --test "tests/*.test.mjs"` 都是 **236 pass / 0 fail（一条不红）**
// ⇒ 这块交付物的判据是**空跑**（违背 #6901 自述的「示例判据必须会红：改回改前形态 ⇒ 该条必红」）。
//
// 本文件把这两条钉在**渲染结果**上（每条都有红证，读数见 PR body）：
//   ① 扫后屏组 1/2/3/5 代表键 label + 值 + 单位 + **顺序**逐字上屏 ⇒ 注入 A 红；
//   ② 反向断言防编数（缺值该行不渲染 / 空快照整块不出现 / `0` 与 `false` 反过来**必须**渲染）
//      ⇒ 注入 A 红、把「缺值也摆一行」改回来也红；
//   ③ 同一 `order_item_id` 在 `mainView` + `overviewView` 恰好上屏一次 ⇒ 注入 A 红；
//   ④ 机台屏新增行上屏 + 缺值 `—`（既有 12 行逐字不变 = **负控**）⇒ 注入 C 红；
//   ⑤ 未登记键不上工人屏（`migao-dev-flow` §31 P3：不摆内部标识）⇒ 让未知键透传的注入红。
//   ⑥ 报工屏数值**去尾零**（`3.000` → `3`、`6.300` → `6.3`），机台屏仍三位小数 ⇒ 摘掉去尾零即红。
//
// 2026-10-24（issue #7636，用户逐字四条）：① 只印实际褶倍（删理论褶倍）；② 去掉无效的 0；
// ③ 删用料公式 / 算料档位（屏上是 pleat / standard 这类英文）；④ 货号 = **商品货号**（不是 SKU 码）。
//
// 🔴 期望值一律是**手写字面量**，**不** import `POSITION_SPEC_KEYS` 来比对：拿被测表去比被测表 =
//    恒真（表改了屏上也照改 ⇒ 判据不红 = 空断言）。改标签 / 改单位 / 改精度 / 改顺序 / 删行
//    ⇒ 逐字不等 ⇒ 当场红。
//
// 🔴 本文件只承担「上屏」这一半。另一半（「服务端 `positions[]` 追加新键而共享表没跟上 ⇒
//    未登记即红」）的真值源在**后端**：`backend/admin-api/src/test/java/com/migao/admin/service/PositionDetailFieldsTest.java`
//    的 `frontendLabelTableCoversTheWholeKeySet`（它拿服务端真源键集逐键比对本表）。
//    本文件**不**复制它（复制 = 第二份会漂的口径）。
//
// 零依赖：`node --test` + 纯函数渲染产物（`renderPage` 就是 `src/app.mjs` 赋给
// `#worker-h5-root` 的那份 HTML；`renderMachine` 同理）。不引 jsdom —— 最少代码阶梯：原生特性优先。

import test from 'node:test'
import assert from 'node:assert/strict'

import { initialMachineState, renderMachine } from '../src/machine.mjs'
import { initialState, renderPage } from '../src/render.mjs'

// ══════════════════════════════════════════════════════════════════════════════
// 夹具：扫后屏（`set_overview.positions[]`，键 = 服务端 `ProductionScanService` 的 snake_case）
// ══════════════════════════════════════════════════════════════════════════════

/** 已登录态（未登录时 `renderPage` 一律回登录页 —— 那是正确行为，不是被测量的东西）。 */
const LOGGED_IN = () => ({ ...initialState(), mode: 'report', worker: { workerName: '张三', workerNo: 'A017' } })

/** 本套工序（`set_overview.positions[].operations[]`）—— 只为让「本套工序」那一块照常渲染。 */
const operations = (id) => [
  { operation_id: id, logical_name: '定型', position: '布帘', qty: 11, unit: '米', unit_price: 3.5, status: 'pending', done_qty: 0 },
]

/**
 * 扫到的那个部位（布帘）：**组 1 / 2 / 3 / 5 每种都有代表键**，值都是**可逐字认人**的字面量。
 *
 * 组 4（算料 / 排料：`fabric_meters` / `processing_meters` / `formula_text`）**有意不设值** ——
 * 本单口径照 issue #6999 正文（组 1/2/3/5 代表键）；要钉组 4 时按同一形态加一行期望即可
 * （它们同样走这一块，白名单驱动，没有第二份标签表）。
 */
const clothPosition = (over = {}) => ({
  order_item_id: 'oi-cloth',
  position_name: '布帘',
  position_kind: '布帘',
  // ── 组 1 商品身份 ──
  product_name: '全遮光布窗帘',
  product_code: PRODUCT_CODE_CLOTH,
  // SKU 码仍随服务端下发 ⇒ 留在夹具里是为了**反向断言它不上屏**
  sku: SKU_CLOTH,
  color_name: '米白',
  door_width: '2.8米定宽',
  selling_method: '定高买宽',
  // 整卷卷数（issue #7523）：批次号即卷号 ⇒ 工人屏显示「整卷 3 卷」
  roll_count: 3,
  unit: '片',
  // ── 组 2 规格尺寸 ──
  width: 2.8,
  height: 2.65,
  // ── 组 3 加工信息 ──
  curtain_type: '布帘',
  craft: '韩褶',
  cutting_mode: '定高买宽',
  open_count: 2,
  is_shaped: true,
  style: '韩式',
  fullness: 2,
  fullness_actual: 2.05,
  pleat_count: 48,
  per_panel_pleats: 24,
  panels: 2,
  has_pattern: true,
  pattern_repeat: 0.32,
  formula: 'W×F÷门幅',
  craft_tier: 'B',
  special_options: '加铅线',
  // ── 组 5 派工 ──
  batch_no: 'B-20261014-01',
  batch_meters: 12.5,
  component_role: '主帘',
  // ── 组 6 部位备注（**本块不渲染**：`SCAN_BLOCK_EXCLUDED_KEYS`；工人端另有一条更精确的
  //    `render.mjs::positionRemark` 呈现，issue #5685 逐字钉住 —— 同一屏同一事实两次 = §31 P2 禁）──
  remark: '公式--48个折',
  operations: operations('op-cloth'),
  ...over,
})

/** 另一个部位（纱帘）：规格键**故意各不相同** ⇒ 「谁的那一份上屏了」可逐字分辨。 */
const gauzePosition = (over = {}) => ({
  order_item_id: 'oi-gauze',
  position_name: '纱帘',
  position_kind: '纱帘',
  product_name: '雪纺纱',
  product_code: PRODUCT_CODE_GAUZE,
  sku: SKU_GAUZE,
  color_name: '本白',
  width: 2.8,
  height: 2.4,
  curtain_type: '纱帘',
  fullness: 2,
  operations: operations('op-gauze'),
  ...over,
})

/** 一屏解析结果（键与 `ProductionScanService#setOverview` 逐字同形）。 */
const viewWith = (positions, over = {}) => ({
  granularity: 'set_position',
  order_id: 'o-1',
  processing_order_no: 'JG20260920001',
  set_no: 14,
  set_index: 13,
  position: { order_item_id: 'oi-cloth', position_kind: '布帘', position_name: '布帘' },
  operation: {
    operation_id: 'op-cloth', logical_name: '定型', position: '布帘', unit: '米', qty: 11,
    unit_price: 3.5, seq: 1, status: 'pending', determined_by: 'inferred', rerouted: false,
  },
  alternatives: [],
  set_progress: { total: 3, done: 1, percent: 33 },
  set_overview: { set_no: 14, set_index: 13, positions },
  completed: false,
  needs_selection: [],
  ...over,
})

/** 屏上第一块「本部位生产信息」的 HTML（扫后屏 = `mainView` 顶上那一块）。 */
const firstSpecBlock = (html) => html.match(/<dl class="wh5-spec" id="wh5-position-spec">[\s\S]*?<\/dl>/)?.[0] ?? ''

const specRow = (label, text) => `<div class="wh5-spec-row"><dt>${label}</dt><dd>${text}</dd></div>`
const specBlock = (rows) =>
  `<dl class="wh5-spec" id="wh5-position-spec"><div class="wh5-spec-title">本部位生产信息</div>${rows
    .map(([label, text]) => specRow(label, text))
    .join('')}</dl>`

/** 商品货号（`products.sku_code`）—— 屏上「货号」取它（2026-10-24 用户逐字「货号实际是2659」）。 */
const PRODUCT_CODE_CLOTH = '2659'
const PRODUCT_CODE_GAUZE = '2740'
/**
 * **SKU 码**（`{货号}-{色序2位}-{门幅}` = 颜色 × 门幅 的组合，`ProductService#generateSkuCode`）——
 * 服务端仍下发（工序读面 `sku` 键还在用），但**工人屏不再印它**：颜色 / 门幅已各自成行，
 * 再印一串组合码 = 重复 + 内部标识（`migao-dev-flow` §31 P2 / P3）。
 */
const SKU_CLOTH = '2659-01-28'
const SKU_GAUZE = '2740-01-29'

// ══════════════════════════════════════════════════════════════════════════════
// ① 扫后屏：组 1/2/3/5 代表键 label + 值**逐字**上屏
// ══════════════════════════════════════════════════════════════════════════════

/**
 * 期望的**整块** HTML（顺序 = 共享表登记顺序，全部手写）。
 *
 * 红证：`src/position-spec.mjs::specRows` 里把 `for (const spec of POSITION_SPEC_KEYS)` 改成
 * `for (const spec of [])`（= 整块不渲染，正是 #6901 复核用的**注入 A**）⇒ 本测试红（块取不到 /
 * 与期望不等）；改任一 label / 单位 / 精度（如 `m` 从三位小数改两位）⇒ 也红。
 */
const EXPECTED_CLOTH_SPEC_BLOCK = specBlock([
  // 组 1 商品身份
  ['商品名称', '全遮光布窗帘'],
  // 货号 = **商品货号**（不是 SKU 码 2659-01-28，见文件里 SKU_CLOTH 的说明）
  ['货号', PRODUCT_CODE_CLOTH],
  ['颜色', '米白'],
  ['门幅', '2.8米定宽'],
  ['售卖方式', '定高买宽'],
  ['卷数', '3卷'],
  ['数量单位', '片'],
  // 组 2 规格尺寸（报工屏口径 = **去掉无效的 0**：2.800 → 2.8、2.650 → 2.65；机台屏仍三位小数）
  ['宽', '2.8米'],
  ['高', '2.65米'],
  // 组 3 加工信息
  ['部位', '布帘'],
  ['安装工艺', '韩褶'],
  ['加工类型', '定高买宽'],
  ['开数', '2'],
  ['是否定型', '是'],
  ['款式', '韩式'],
  // 褶倍只印**这一单实际用的**那一个（理论褶倍已删，2026-10-24 用户逐字裁定）
  ['实际褶倍', '2.05倍'],
  ['总褶数', '48'],
  ['每片褶数', '24'],
  ['幅数', '2'],
  ['是否对花', '是'],
  ['花距', '0.32'],
  // 用料公式 / 算料档位**已删**（引擎内部标识：屏上是 pleat / standard 这类英文）
  ['特殊选项', '加铅线'],
  // 组 5 派工
  ['批号', 'B-20261014-01'],
  ['指派米数', '12.5米'],
  ['组件', '主帘'],
])

test('🔴 ① 扫后屏「本部位生产信息」：组 1/2/3/5 代表键的 label + 值 + 单位 + 顺序**逐字**上屏（注入 A ⇒ 红）', () => {
  const html = renderPage(LOGGED_IN(), viewWith([clothPosition(), gauzePosition()]))

  // 前置：这一块必须真的在屏上（本单要治的正是「整块不渲染而一条判据都不红」）
  const block = firstSpecBlock(html)
  assert.equal(block, EXPECTED_CLOTH_SPEC_BLOCK, '整块必须与期望逐字相同（label / 值 / 单位 / 顺序）')

  // 它在「本套工序」之前（= mainView 顶上那一块，不是别处的块）
  const [head] = html.split('id="wh5-set-overview"')
  assert.equal(head.split('id="wh5-position-spec"').length - 1, 1, 'mainView 顶部恰好一块')
  assert.equal(head.includes(EXPECTED_CLOTH_SPEC_BLOCK), true, '顶部那块的正文就是本部位的规格行')

  // 反向：组 6「部位备注」**不在本块**（同一屏同一事实两次 = §31 P2 禁；它由 `positionRemark` 另承）
  assert.equal(block.includes('<dt>部位备注</dt>'), false, '部位备注不得在规格块里再印一遍')

  // 反向：三行**按现场口径删掉**的键一个都不许回来（2026-10-24 用户逐字裁定）
  for (const gone of ['理论褶倍', '用料公式', '算料档位']) {
    assert.equal(block.includes(`<dt>${gone}</dt>`), false, `「${gone}」不得再上工人屏（用户 2026-10-24 逐字删除）`)
  }
  // 反向：**SKU 码**不上屏（货号那一行取的是商品货号；颜色 / 门幅已各自成行 ⇒ 组合码 = 重复 + 内部标识）
  assert.equal(block.includes(SKU_CLOTH), false, `SKU 码 ${SKU_CLOTH} 不得上屏（货号 = 商品货号 ${PRODUCT_CODE_CLOTH}）`)
  // 反向：报工屏不印三位小数的无效 0（`2.800米` / `12.500米` 这类形态）
  assert.equal(block.includes('2.800米'), false, '报工屏数值必须去尾零（2.800米 ⇒ 2.8米）')
})

// ══════════════════════════════════════════════════════════════════════════════
// ② 反向断言防编数：缺值不渲染该行 / 空快照整块不出现 / `0` 与 `false` **必须**渲染
// ══════════════════════════════════════════════════════════════════════════════

/**
 * ⚠️ **附带发现（本文件有意不钉，钉它必须先改产品代码 —— 本单边界 = 只加测试）**：
 * 缺值的第 4 种形态「**纯空白串**」目前**会编出数**：`position-spec.mjs::formatSpecValue` 的
 * 数值路径只挡了空串（`value !== ''`），没挡纯空白，而 `Number('   ') === 0`
 * ⇒ `'   '` 渲染成 `0`（`format: 'm'` 则是 `0.000`），与同模块 `dataOr` 的口径（`'   '` ⇒ `—`）
 * **自相矛盾**。实测：`specRows({ craft: '   ', width: '   ' })` ⇒
 * `[{宽: '0.000米'}, {安装工艺: '0'}]`（复现命令与逐字读数见 PR body / 另单）。
 * ⇒ 本测试的缺值集**只**收「`null` / `undefined` / 缺键 / 空串」这四种**当前就正确**的形态；
 * 「纯空白」留给另单（它要改 `formatSpecValue`，且要有自己的红证）。
 */
test('🔴 ②-a 缺值不渲染该行（`null` / `undefined` / 缺键 / 空串 ⇒ 整行不出现，绝不摆空占位、不编数）', () => {
  const partial = clothPosition({
    open_count: null,
    color_name: '',
    door_width: undefined,
    batch_no: undefined,
    craft: '',
  })
  const html = renderPage(LOGGED_IN(), viewWith([partial]))
  const block = firstSpecBlock(html)

  assert.equal(block.includes('<dt>货号</dt>'), true, '前置：这一块确实渲染了（有值的行照旧在）')
  for (const label of ['开数', '颜色', '门幅', '批号', '安装工艺']) {
    assert.equal(block.includes(`<dt>${label}</dt>`), false, `缺值的「${label}」不得渲染该行（缺值不造值，也不摆空占位）`)
  }
  // 缺值绝不落成「—」「0」「undefined / null / NaN」这类**编出来的数**
  for (const pseudo of ['<dd>—</dd>', '<dd>0</dd>']) {
    assert.equal(block.includes(pseudo), false, `缺值不得渲染成 ${pseudo}（报工屏口径 = 缺值整行不渲染，不是占位符）`)
  }
  assert.equal(/undefined|null|NaN/.test(block), false, '缺值不得渲染成 undefined / null / NaN')
})

test('🔴 ②-b 空快照整块不出现（`set_overview` 缺 / `positions` 空 / 本部位规格全缺 ⇒ 连标题一个字节都不出现）', () => {
  const bare = { order_item_id: 'oi-cloth', position_name: '布帘', operations: operations('op-cloth') }
  const cases = [
    ['set_overview 缺失', viewWith([clothPosition()], { set_overview: undefined })],
    ['positions 为空数组', viewWith([])],
    ['本部位一行规格全缺', viewWith([bare])],
  ]
  for (const [name, view] of cases) {
    const html = renderPage(LOGGED_IN(), view)
    assert.equal(html.includes('id="wh5-position-spec"'), false, `${name} ⇒ 规格块不得出现（含标题）`)
    assert.equal(html.includes('本部位生产信息'), false, `${name} ⇒ 连标题都不出现（不渲染空块 / 空网格）`)
  }
  // 前置：最后那种形态下屏**不是**空的（否则「块不出现」会因为别的原因而假绿）
  const stillThere = renderPage(LOGGED_IN(), viewWith([bare]))
  assert.equal(stillThere.includes('id="wh5-set-overview"'), true, '前置：本套工序照常渲染 ⇒ 上面的「不出现」是规格块自己的事')
})

test('🔴 ②-c 反过来：`0` 与 `false` 是**真值**，必须渲染（不许把 0 / 否 当缺值吞掉）', () => {
  const html = renderPage(
    LOGGED_IN(),
    viewWith([clothPosition({ open_count: 0, is_shaped: false, pattern_repeat: 0 })]),
  )
  const block = firstSpecBlock(html)

  assert.equal(block.includes(specRow('开数', '0')), true, '开数 0 必须上屏（0 ≠ 缺值；吞掉 = 工人照错的数干活）')
  assert.equal(block.includes(specRow('是否定型', '否')), true, '是否定型 false 必须上屏「否」（缺值与「否」是两件事）')
  assert.equal(block.includes(specRow('花距', '0')), true, '花距 0 必须上屏')
  // 与 ②-a 成对：同一条键「有值 ⇒ 有行」「缺值 ⇒ 无行」，两个方向都钉住才不会退化成空断言
  assert.equal(block.includes('<dt>开数</dt><dd>—</dd>'), false, '有值时不得渲染成「—」')
})

// ══════════════════════════════════════════════════════════════════════════════
// ③ 同一 `order_item_id` 恰好上屏一次（顶部块 + 本套工序不重复）
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ③ 同一 order_item_id 在 mainView + overviewView **只出现一次**（`render.mjs::currentSpecBlock` 与排除同源）', () => {
  const view = viewWith([clothPosition(), gauzePosition()])
  const html = renderPage(LOGGED_IN(), view)

  // 两块 = 顶上（扫到的那个部位）+ 本套工序里**另一个**部位；扫到那一份不得在里面再来一遍
  assert.equal(html.split('id="wh5-position-spec"').length - 1, 2, '屏上恰好两块规格（一个部位一块）')
  assert.equal(html.split(PRODUCT_CODE_CLOTH).length - 1, 1, `扫到那个部位的货号（${PRODUCT_CODE_CLOTH}）在整屏只出现一次`)
  assert.equal(html.split(PRODUCT_CODE_GAUZE).length - 1, 1, `另一个部位的货号（${PRODUCT_CODE_GAUZE}）也只出现一次`)
  // 反向：两块的**SKU 码**一个都不许出现（服务端下发了也不印 —— 见文件里 SKU_CLOTH 的说明）
  assert.equal(html.includes(SKU_CLOTH), false, `SKU 码 ${SKU_CLOTH} 不得上屏`)
  assert.equal(html.includes(SKU_GAUZE), false, `SKU 码 ${SKU_GAUZE} 不得上屏`)

  const [head, tail] = html.split('id="wh5-set-overview"')
  assert.equal(head.split('id="wh5-position-spec"').length - 1, 1, 'mainView 顶部恰好一块')
  assert.equal(tail.split('id="wh5-position-spec"').length - 1, 1, '本套工序里恰好一块（扫到的那个部位被排除）')
  assert.equal(head.includes(PRODUCT_CODE_CLOTH), true, '顶部那块 = 扫到的那个部位')
  assert.equal(head.includes(PRODUCT_CODE_GAUZE), false, '顶部不得混进别的部位的规格')
  assert.equal(tail.includes(PRODUCT_CODE_CLOTH), false, '本套工序里不得把扫到那一份再印一遍（同一屏同一事实两次）')

  // 另一条分支：工序未确定（`operation == null`）⇒ `overviewView` 不带排除参数 ⇒ 仍不得重复
  const noOp = viewWith([clothPosition(), gauzePosition()], { operation: null })
  const noOpHtml = renderPage({ ...LOGGED_IN(), view: noOp }, noOp)
  assert.equal(noOpHtml.split(PRODUCT_CODE_CLOTH).length - 1, 1, '工序未确定态照旧只出现一次（该分支不另印一份）')
  assert.equal(noOpHtml.split(PRODUCT_CODE_GAUZE).length - 1, 1, '另一个部位同样只出现一次')
})

// ══════════════════════════════════════════════════════════════════════════════
// ④ 机台屏屏一（订单详情）：#6901 新增行上屏 + 缺值 `—`（既有 12 行逐字不变 = 负控）
// ══════════════════════════════════════════════════════════════════════════════

const kvRow = (label, text) => `<div class="wh5-machine__kv"><dt>${label}</dt><dd>${text}</dd></div>`

/**
 * 机台屏**既有 12 行**（#6901 之前就在那儿的真值：文案 / 顺序 / `m` 三位小数 / 缺值形态）。
 * **负控**：本单只加判据、不动它们 ⇒ 注入 C 下这 12 行必须**逐字仍绿**。
 */
const LEGACY_12_ROWS = [
  kvRow('品牌', '观星台'),
  kvRow('收货人', '张女士'),
  kvRow('款式', '全遮光布窗帘'),
  kvRow('套数', '3套'),
  kvRow('宽', '2.800米'),
  kvRow('高', '2.650米'),
  kvRow('加工类型', '定高买宽'),
  kvRow('开数', '2'),
  kvRow('安装工艺', '韩褶'),
  kvRow('褶倍', '2倍'),
  kvRow('用料', '8.100米'),
  kvRow('部位备注', '全遮光布窗帘 · 左窗'),
]

/**
 * #6901 在机台屏**追加**的规格行（label → 期望 `<dd>`）。
 *
 * 红证：删掉 `src/machine.mjs::detailRows` 里那段
 * `...POSITION_SPEC_KEYS.filter(…).map(…)`（= **注入 C**，把机台屏新增行全部摘掉）⇒ 本测试红。
 * 🔴 负控必须与「新增行」分开断言：`货号` / `颜色` / `门幅` 在 `detailRows` 里有**手写行**，
 *    只断言它们的话，注入 C 会**照样绿**（这就是当初 236 / 0 不红的成因之一）⇒ 下表必须含
 *    **只由共享表提供**的键（`批号` / `指派米数` / `组件` / `算料公式` …）。
 */
const ADDED_ROWS = [
  // 货号 = 商品货号（本单起机台屏手写行也读 `product_code`；SKU 码不再上屏）
  ['货号', PRODUCT_CODE_CLOTH],
  ['颜色', '米白'],
  ['门幅', '2.8米定宽'],
  ['商品名称', '全遮光布窗帘'],
  ['售卖方式', '定高买宽'],
  ['卷数', '3卷'],
  ['数量单位', '片'],
  ['是否定型', '是'],
  ['款式', '韩式'],
  ['实际褶倍', '2.05倍'],
  ['总褶数', '48'],
  ['每片褶数', '24'],
  ['幅数', '2'],
  ['是否对花', '是'],
  ['花距', '0.32'],
  ['特殊选项', '加铅线'],
  ['批号', 'B-20261014-01'],
  // 机台屏**不去尾零**（机器精度三位小数 = mm，既有真值）—— 这条同时是报工屏去尾零的**负控**
  ['指派米数', '12.500米'],
  ['组件', '主帘'],
  ['加工费米数', '—'],
  ['算料公式', '—'],
]

/** 机台屏屏一的状态（`/api/worker/production/cutting-height` 的形状）。 */
const machineDetailState = () => ({
  ...initialMachineState(),
  mode: 'detail',
  worker: { workerName: '张三' },
  data: {
    order: { customer_name: '张女士', set_count: 3 },
    positions: [
      {
        ...clothPosition(),
        brand: '观星台',
        position_remark: '左窗',
        fabric_meters: 8.1,
        base: 2.7,
        cutting_height: 3.028,
        rounding: { mode: 'half_up', digits: 3 },
        hits: [],
        misses: [],
        missing: [],
        missing_reason: null,
      },
      {
        ...gauzePosition(),
        brand: null,
        position_remark: null,
        fabric_meters: null,
        base: 2.4,
        cutting_height: 2.48,
        rounding: { mode: 'half_up', digits: 3 },
        hits: [],
        misses: [],
        missing: [],
        missing_reason: null,
      },
    ],
  },
})

/**
 * ⚠️ **附带发现（本文件有意不钉，钉它必须先改产品代码 —— 本单边界 = 只加测试）**：
 * 机台屏目前把 `货号` / `颜色` / `门幅` / `款式` / `部位备注` **各印两遍** ——
 * `machine.mjs::MACHINE_DETAIL_COVERED` 未收 `sku` / `color_name` / `door_width`（这三个键在
 * `detailRows` 里已有手写行），`style` 与既有手写行「款式」同名、共享表的 `remark` 与
 * `remarkText(position)` 复用同一标签。复现（读数写在 issue #6999 的 PR body 里）：
 * `node --input-type=module -e "…detailRows(…).map(r=>r[0])"` ⇒ 38 行、重复标签 5 个。
 * 本文件的 ④ 只钉「新增行上屏 / 缺值 `—` / 既有 12 行逐字不变」，**不替产品做取舍**。
 */
test('🔴 ④ 机台屏屏一：#6901 新增规格行上屏 + 缺值 `—`（既有 12 行逐字不变 = 负控；注入 C ⇒ 红）', () => {
  const html = renderMachine(machineDetailState())
  const kvList = html.match(/<dl class="wh5-machine__kv-list">([\s\S]*?)<\/dl>/)?.[1] ?? ''
  const rows = kvList.match(/<div class="wh5-machine__kv">[\s\S]*?<\/div>/g) ?? []

  // 负控：既有 12 行仍是最前面的 12 行，且逐字不变（文案 / 顺序 / 精度 / 缺值形态）
  assert.equal(rows.slice(0, 12).join(''), LEGACY_12_ROWS.join(''), '既有 12 行逐字不变（本单只加判据、不动它们）')

  // 新增行上屏（逐行逐字）
  for (const [label, text] of ADDED_ROWS) {
    assert.equal(kvList.includes(kvRow(label, text)), true, `#6901 新增行「${label}」必须以「${text}」上屏`)
  }

  // 缺值一律显式 `—`（不猜 0、不留空、不接单位）
  assert.equal(kvList.includes(kvRow('算料公式', '—')), true, '缺值行显式 `—`（机台屏口径 = `EMPTY`，与报工屏「整行不渲染」是**有意**的两态）')
  assert.equal(kvList.includes('—米'), false, '缺值不得在 `—` 后面再缀单位')
  assert.equal(/undefined|null|NaN/.test(kvList), false, '缺值不得渲染成 undefined / null / NaN')
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑤ 未登记键不上工人屏（`migao-dev-flow` §31 P3：不摆内部标识）
// ══════════════════════════════════════════════════════════════════════════════

/**
 * 红证：往 `src/position-spec.mjs::specRows` 里加一句「白名单外的键也上屏、标签就用原始键名」
 * （`if (!POSITION_SPEC_KEYS.some(s => s.key === k)) rows.push({ key: k, label: k, text: String(v) })`）
 * ⇒ 本测试红（原始键名 = 内部标识照上了工人屏）。
 */
test('🔴 ⑤ 未登记键不上工人屏：服务端多给的键不得把**原始键名**透上屏（§31 P3 不摆内部标识）', () => {
  const html = renderPage(
    LOGGED_IN(),
    viewWith([clothPosition({ internal_batch_key: 'a61daac3', new_spec_key: '新字段' })]),
  )
  const block = firstSpecBlock(html)

  assert.equal(block.includes('<dt>货号</dt>'), true, '前置：已登记的键照旧上屏（证明这条不是「整块没渲染」的假绿）')
  for (const unknown of ['internal_batch_key', 'new_spec_key']) {
    assert.equal(block.includes(unknown), false, `未登记的键「${unknown}」不得上屏（键名 = 内部标识，人话标签无从谈起）`)
  }
  assert.equal(block.includes('a61daac3'), false, '未登记键的**值**也不得借道任何一行漏上屏')
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑥ 报工屏数值去尾零（issue #7636），机台屏仍机器精度三位小数（负控）
// ══════════════════════════════════════════════════════════════════════════════

/**
 * 红证：把 `src/position-spec.mjs::specRows` 里的去尾零摘掉（`shown` 直接用 `formatSpecValue`）
 * ⇒ 报工屏回到 `3.000米` / `6.300米` ⇒ 本测试红（用户 2026-10-24 逐字「3.600 就展示 3.6，
 * 不要把无效的 0 展示出来」）。负控：机台屏 `m` 精度**不许**跟着改 —— 那是机器读数（mm）。
 */
test('🔴 ⑥ 报工屏去尾零：`3.000` → `3`、`6.300` → `6.3`；机台屏保持三位小数（负控）', () => {
  const html = renderPage(
    LOGGED_IN(),
    viewWith([clothPosition({ width: 3, height: 2.6, fabric_meters: 6.3 })]),
  )
  const block = firstSpecBlock(html)

  assert.equal(block.includes(specRow('宽', '3米')), true, '3.000 ⇒ 3米（无效的 0 不展示）')
  assert.equal(block.includes(specRow('高', '2.6米')), true, '2.600 ⇒ 2.6米')
  assert.equal(block.includes(specRow('面料米数', '6.3米')), true, '6.300 ⇒ 6.3米')
  for (const stale of ['3.000米', '2.600米', '6.300米']) {
    assert.equal(block.includes(stale), false, `报工屏不得再印 ${stale}`)
  }
  assert.equal(block.includes(specRow('宽', '3.米')), false, '去尾零不得留下孤立的小数点')

  // 负控：机台屏是机器读数（mm 级三位小数）—— 去尾零只发生在报工屏
  const machine = renderMachine(machineDetailState())
  const kvList = machine.match(/<dl class="wh5-machine__kv-list">([\s\S]*?)<\/dl>/)?.[1] ?? ''
  assert.equal(kvList.includes(kvRow('宽', '2.800米')), true, '机台屏保持三位小数（既有真值，本单不动）')
})
