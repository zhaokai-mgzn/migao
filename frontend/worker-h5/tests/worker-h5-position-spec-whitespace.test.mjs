// case_ids: MC-139
//
// 🔴 **纯空白串 = 「没填」，不是 0**（issue #7002）。
//
// 病（`origin/main` 实测，坐标 = `frontend/worker-h5/src/position-spec.mjs::formatSpecValue`）：
// 数值路径只挡了空串（`value !== ''`），而 `Number('   ') === 0`
// ⇒ 商家**没填**的部位规格（`'   '`）被编成 `0`（`format: 'm'` 时是 `0.000`），
// 而同一模块 `dataOr('   ')` ⇒ `—` ⇒ **同模块两个口径自相矛盾**。
// 逐字读数（修前）：`specRows({ craft: '   ', width: '   ' })`
// ⇒ `[{宽: '0.000米'}, {安装工艺: '0'}]`（报工屏）；机台屏 `kvRows` 同源同病。
//
// 危害不只是观感：`format: 'm'` 的键（宽 / 高 / 料米数）渲染成 `0.000` 是**给机器的值偏小**
// ⇒ 裁短方向的事故面。⇒ 修法 = 判数**前**先 trim，空 ⇒ 走既有缺值口径（`EMPTY`）；
// 「没填」与「填了 0」是**两件事**（`'0'` 仍是合法值 0）—— 后者由判据 ② 反向钉住。
//
// 🔴 红证（注入式，双向对照；实测读数见 PR body）：
//   · 注入 A（把 trim 删掉）= 把 `const text = typeof value === 'string' ? value.trim() : value`
//     改回 `const text = value` ⇒ 判据 ① / ③ / ④ / ⑤ / ⑥ 必红；
//   · 注入 B（把空白也当缺值之外的方向错）= 在 trim 后加 `if (text === '') return '0'`
//     ⇒ 判据 ① 红、且 ② 的负控被推翻（证明「缺值与 0 分开」是两条独立断言，不是同一条的两面）。
//
// 边界（照实登记）：本文件钉的是**展示口径**（`formatSpecValue` 一族），不判服务端为何会存进空白串
// ——上游是商家录入 / 历史行的数据面（见 PR body 的「上游取值来源」），本包不改数据面。
// 同类「不 trim 直接 parse」的其它点**只登记不扩射程**（清单在 PR body）。

import test from 'node:test'
import assert from 'node:assert/strict'

import { detailRows, initialMachineState, renderMachine } from '../src/machine.mjs'
import { initialState, renderPage } from '../src/render.mjs'
import { dataOr, EMPTY, POSITION_SPEC_KEYS, specRows } from '../src/position-spec.mjs'
import { formatSpecValue } from '../src/position-spec.mjs'

/** 纯空白串的各种形态（`\t` / 换行也是「商家只敲了空白」）。 */
const BLANKS = ['   ', '  ', '\t', '\n', ' \t\n ']

/** 逐个数值口径（`undefined` = 缺省 raw）—— 缺任何一个都会留下未钉的分支。 */
const NUMERIC_FORMATS = [undefined, 'm', 'int', 'number']

// ══════════════════════════════════════════════════════════════════════════════
// ① 判据：`'   '` ⇒ 缺值（`EMPTY`），**不是 0**（逐 format 钉；注入 A ⇒ 红）
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ① 纯空白串 ⇒ 缺值「—」（`undefined` / `m` / `int` / `number` / `bool` 逐个钉，不编 0）', () => {
  for (const blank of BLANKS) {
    for (const format of [...NUMERIC_FORMATS, 'bool']) {
      assert.equal(
        formatSpecValue(blank, format),
        EMPTY,
        `formatSpecValue(${JSON.stringify(blank)}, ${JSON.stringify(format)}) 必须是「${EMPTY}」（没填 ≠ 0）`,
      )
    }
  }

  // 与同模块 `dataOr` 的**同一份口径**：缺值就同一个读数（issue #7002 的病正是这两者自相矛盾）
  for (const blank of BLANKS) {
    assert.equal(formatSpecValue(blank, undefined), dataOr(blank), '缺值读数必须与 dataOr 同口径')
    assert.equal(dataOr(blank), EMPTY, '前置：dataOr 对纯空白本来就是「—」')
  }
})

// ══════════════════════════════════════════════════════════════════════════════
// ② 负控：**填了 0 就是 0**（不许把合法 0 当缺值吞掉 —— 本单最危险的假修方向）
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ② 负控：`0` / `"0"` / `" 0 "` 仍是 **0**（不是缺值），其它既有读数逐字不变', () => {
  // 真 0（数字）与「填了 0」的三种字符串形态
  for (const zero of [0, '0', '0.0', ' 0 ']) {
    assert.equal(formatSpecValue(zero, 'm'), '0.000', `${JSON.stringify(zero)} 是**填了 0** ⇒ m 口径 0.000`)
    assert.equal(formatSpecValue(zero, 'int'), '0', `${JSON.stringify(zero)} ⇒ int 口径 0`)
    assert.equal(formatSpecValue(zero, 'number'), '0', `${JSON.stringify(zero)} ⇒ number 口径 0`)
    assert.equal(formatSpecValue(zero, undefined), '0', `${JSON.stringify(zero)} ⇒ raw 口径 0`)
  }

  // 既有读数逐字不变（issue #7002 的「负控」四条：0 / '0' / '2.5' / 非数文本）
  assert.equal(formatSpecValue(2.5, 'm'), '2.500', '数字 2.5 的机台精度读数不变')
  assert.equal(formatSpecValue('2.5', 'm'), '2.500', '字符串 "2.5" 照旧按数字显示')
  assert.equal(formatSpecValue(' 2.5 ', 'm'), '2.500', '带空白的数字仍是数字（trim 不只挡空串）')
  assert.equal(formatSpecValue('定高买宽', undefined), '定高买宽', '非数文本原样显示（不折成 NaN）')
  assert.equal(formatSpecValue(' 定高买宽 ', undefined), '定高买宽', '非数文本照 `dataOr` 口径 trim')
  assert.equal(formatSpecValue(true, 'bool'), '是', 'bool 口径不变')
  assert.equal(formatSpecValue(false, 'bool'), '否', 'bool 口径不变')
})


// ══════════════════════════════════════════════════════════════════════════════
// ③ 判据：`' 12 '` ⇒ 12（trim 不是「见空白就吞」，而是「先归一再判数」）
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ③ 两端带空白的数字照旧是数字：`" 12 "` ⇒ `12`（各口径）', () => {
  assert.equal(formatSpecValue(' 12 ', 'int'), '12')
  assert.equal(formatSpecValue(' 12 ', 'number'), '12')
  assert.equal(formatSpecValue(' 12 ', 'm'), '12.000')
  assert.equal(formatSpecValue(' 12 ', undefined), '12')
  assert.equal(formatSpecValue('\t12.5\n', 'm'), '12.500', '制表符 / 换行同属空白')
})

// ══════════════════════════════════════════════════════════════════════════════
// ④ 报工屏：缺值的两行**整行不渲染**（与既有缺值口径一致），而「填了 0」那一行照旧在
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ④ 报工屏 `specRows`：纯空白的两行不渲染（不是「宽 0米」）；`" 0 "` 那一行照旧渲染', () => {
  // issue 原文的复现输入：整份部位只有两个**纯空白**规格 ⇒ 一行都不该有
  assert.deepEqual(specRows({ craft: '   ', width: '   ' }), [], '纯空白 ⇒ 整行不渲染（修前是「宽 0.000米 / 安装工艺 0」）')

  // 空白与真值混排：空白行消失、真值行（含**填了 0**）逐字仍在
  const rows = specRows({ width: '   ', craft: '韩褶', open_count: ' 0 ', pattern_repeat: ' 0.32 ' })
  assert.deepEqual(
    rows.map((r) => [r.label, r.text]),
    [['安装工艺', '韩褶'], ['开数', '0'], ['花距', '0.32']],
    '空白行消失、`" 0 "` / `" 0.32 "` 照旧渲染（缺值与 0 分开）',
  )
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑤ 机台屏同源同口径：`detailRows` → `kvRows` 渲染「—」（不是 0.000 米 / 0）
// ══════════════════════════════════════════════════════════════════════════════

/** 机台屏屏一的最小状态（`/api/worker/production/cutting-height` 的形状）。 */
const machineState = (position) => ({
  ...initialMachineState(),
  mode: 'detail',
  worker: { workerName: '张三' },
  data: { order: { customer_name: '张女士', set_count: 1 }, positions: [position] },
})

const BLANK_POSITION = {
  order_item_id: 'oi-blank',
  position_name: '布帘',
  position_kind: '布帘',
  brand: '观星台',
  width: '   ',
  height: ' ',
  craft: '\t',
  open_count: ' 0 ',
  operations: [],
}

test('🔴 ⑤ 机台屏 `kvRows`：同一份空白输入渲染「—」，`" 0 "` 的格仍是 0（负控）', () => {
  const html = renderMachine(machineState(BLANK_POSITION))
  const kvList = html.match(/<dl class="wh5-machine__kv-list">([\s\S]*?)<\/dl>/)?.[1] ?? ''
  const row = (label) => kvList.match(new RegExp(`<div class="wh5-machine__kv"><dt>${label}</dt><dd[^>]*>[\\s\\S]*?</dd></div>`))?.[0] ?? ''

  // 前置：这一块确实渲染了（否则下面的「不含 0.000」是假绿）
  assert.match(kvList, /<dt>品牌<\/dt>/, '前置：机台屏详情块确实渲染了')

  for (const label of ['宽', '高', '安装工艺']) {
    assert.match(row(label), new RegExp(`</dt><dd[^>]*>${EMPTY}</dd>`), `机台屏「${label}」必须是「${EMPTY}」（缺值不编数、也不带单位）`)
    // 反向：这几格绝不出现编出来的数（修前：`0.000米` / `0`）
    assert.equal(/(^|>)(0|0\.000)(米)?</.test(row(label)), false, `机台屏「${label}」不得渲染成 0 / 0.000（那是「填了 0」的读数）`)
  }
  assert.equal(kvList.includes('0.000米'), false, '空白不得渲染成「0.000米」')
  // 负控：同一份输入里**真的填了 0** 的那一格照旧是 0
  assert.equal(row('开数').includes('>0</dd>'), true, '开数填了 `" 0 "` ⇒ 仍是 0（负控）')

  // 两屏同源：`detailRows` 的原始元组也是同一批值（不是渲染层各写一份 trim）
  const values = Object.fromEntries(detailRows(machineState(BLANK_POSITION).data, BLANK_POSITION).map(([label, value]) => [label, value]))
  assert.equal(values['宽'], '   ', '前置：`detailRows` 原样透传服务端值，trim 只发生在展示口径')
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑥ 类级守卫（§23）：**整表**的表意口径对空白一律缺值 —— 新增规格键 / 新增数值口径自动进场
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ⑥ 类级守卫：`POSITION_SPEC_KEYS` **每一个键**（不论什么 format）对纯空白都给「—」', () => {
  assert.ok(POSITION_SPEC_KEYS.length > 0, '前置：规格表非空（表被清空 ⇒ 本条不能空跑成绿）')
  for (const spec of POSITION_SPEC_KEYS) {
    assert.equal(
      formatSpecValue('   ', spec.format),
      EMPTY,
      `规格键 ${spec.key}（format=${spec.format ?? 'raw'}）对纯空白必须缺值 ⇒ 新增键 / 改口径也进这条判据`,
    )
  }
  // 报工屏同一条：整表空白 ⇒ 一行都不渲染（缺值不摆空占位）
  assert.deepEqual(specRows(Object.fromEntries(POSITION_SPEC_KEYS.map((s) => [s.key, '   ']))), [])
})
