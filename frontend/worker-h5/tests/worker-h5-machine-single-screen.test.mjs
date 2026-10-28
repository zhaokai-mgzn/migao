// case_ids: PG-047
//
// 机台屏「一屏放下」（issue #7990，2026-10-28 用户逐字「要一个屏幕把关键信息都放下」）。
//
// 病灶：详情屏只有「裁高计算器 ▶」一个入口 ⇒ 参数选择藏到第二屏；工人要么漏看、要么来回换屏。
// 改后：**详情屏右侧内联参数 chips**（与计算器同一份勾选状态、同一套命中口径），
//       大字裁高值随勾选**即时变化**；计算器退为「明细 / 手改」入口（不再是必经路径）。
//
// 四条判据（每条都能红）：
//   ① 详情屏直接渲染 chips：命中项逐条带 `data-machine-hit`（红证：只渲染入口按钮 ⇒ 红）；
//   ② 勾掉一条命中 ⇒ 大字值**立刻**变成不含该项的合计（红证：仍用服务端的 `cutting_height` ⇒ 红）；
//   ③ 「宽 / 高 / 用料」三格带放大标记 `is-key`（红证：去掉标记 ⇒ 红；其余格不得带）；
//   ④ 没有命中项时给出**可读的空态**（不渲染空 chips 容器里的空白）。
//
// 零依赖：`node --test` + 字符串断言（不引 DOM 库）。

import test from 'node:test'
import assert from 'node:assert/strict'

import { initialMachineState, machineTotal, renderDetail } from '../src/machine.mjs'

const position = {
  order_item_id: 'it-1',
  position_kind: '布帘',
  position_name: '主卧',
  brand: '观星台',
  product_name: '全光布窗帘',
  product_code: '2659',
  width: 3,
  height: 2.45,
  craft: '韩褶',
  curtain_type: '布帘',
  open_count: 2,
  cutting_mode: '定高买宽',
  fullness: 2,
  fabric_meters: 6.3,
  base: 2.45,
  cutting_height: 2.53,
  rounding: { mode: 'half_up', digits: 3 },
  missing: [],
  hits: [{ key: 'baobuzhe', name: '包布折', value: 0.08, direction: 'add' }],
  misses: [],
}

const stateOf = (overrides = {}) => ({
  ...initialMachineState(),
  mode: 'detail',
  worker: { workerName: '验收工人' },
  data: {
    order: { customer_name: 'zhaoting', set_count: 1 },
    positions: [position],
    batch_required: false,
    batch_no: null,
  },
  unchecked: [],
  ...overrides,
})

test('① 详情屏内联 chips：命中项逐条可勾（不必进第二屏）', () => {
  const html = renderDetail(stateOf())
  assert.match(html, /data-machine-hit="baobuzhe"/, '详情屏没有内联命中项 chip')
  assert.match(html, /包布折/, 'chip 没写名称')
  assert.match(html, /\+0\.080/, 'chip 没写增量值（三位小数）')
})

test('② 勾掉一条命中 ⇒ 大字合计立刻变化（用的是手改合计，不是服务端返回值）', () => {
  const kept = renderDetail(stateOf())
  assert.match(kept, /2\.530/, '未勾掉时应显示 2.450 + 0.080 = 2.530')

  const dropped = renderDetail(stateOf({ unchecked: ['baobuzhe'] }))
  assert.match(dropped, /2\.450/, '勾掉后应显示 2.450')
  assert.equal(/2\.530/.test(dropped), false, '勾掉后仍在显示含该项的合计 ⇒ 大字没用本次合计')
  assert.match(dropped, /已手改/, '手改后没有提示（工人会以为改的是订单）')
})

test('③ 「宽 / 高 / 用料」放大，其余格不带放大标记', () => {
  const html = renderDetail(stateOf())
  const keyCells = html.match(/<div class="wh5-machine__kv"><dt>([^<]+)<\/dt><dd class="is-key">/g) ?? []
  const labels = keyCells.map((cell) => cell.match(/<dt>([^<]+)<\/dt>/)[1])
  assert.deepEqual(labels.sort(), ['用料', '宽', '高'].sort(), `放大格应只有宽/高/用料，实际 = ${labels.join('、')}`)
})

test('④ 没有命中项时给可读空态（不是空白容器）', () => {
  const bare = { ...position, hits: [], cutting_height: 2.45 }
  const html = renderDetail(stateOf({ data: { order: { customer_name: 'zhaoting', set_count: 1 }, positions: [bare], batch_required: false } }))
  assert.match(html, /没有命中的增量项/, '空态没有文案')
  assert.equal(/data-machine-hit=/.test(html), false, '空态仍在渲染 chip')
  assert.equal(machineTotal(bare, []), 2.45)
})
