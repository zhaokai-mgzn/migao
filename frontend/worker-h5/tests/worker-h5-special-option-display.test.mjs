// case_ids: PG-046
/**
 * 工人屏「特殊选项」的展示口径（issue #8007，用户 2026-10-28 裁定）—— 纯函数判据。
 *
 * 背景：`position-spec.mjs` 的 `special_options` 行此前**没有** format ⇒ 数组走 `String()`
 * （英文逗号并列），且落库的布/纱派生键（`余料带回-布` / `-纱`）会原样印上工人屏。
 * 用户口径：「只需要展示**余料带回**即可，后面的 -布 / -纱 跟随订单套行的帘种」（全系统）。
 *
 * 判据（每条都能红）：
 * ① 派生键在工人屏收回语义名（`余料带回-布` / `-纱` ⇒ `余料带回`；`布绑带` / `纱绑带` ⇒ `绑带`）；
 * ② 多项用**顿号**并列（不是 `String(array)` 的英文逗号）；
 * ③ 形态容错：数组与单串都认（老夹具 / 老载荷不整行变成 `—`）；
 * ④ 空 / 脏值仍显式 `—`（不给 `undefined` / `NaN`）。
 * ⑤ 类级：同族两派生键并存 ⇒ 去重；`余料做绑带` 等独立选项名不得被折叠。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { formatSpecValue } from '../src/position-spec.mjs'

test('#8007/#8108 ①③ 派生键收回语义名；数组/单串两种形态都认', () => {
  assert.equal(formatSpecValue(['余料带回-布'], 'optionList'), '余料带回')
  assert.equal(formatSpecValue(['余料带回-纱'], 'optionList'), '余料带回')
  assert.equal(formatSpecValue('余料带回-布', 'optionList'), '余料带回')
  assert.equal(formatSpecValue(['布绑带'], 'optionList'), '绑带')
  assert.equal(formatSpecValue(['纱绑带'], 'optionList'), '绑带')
  assert.equal(formatSpecValue('纱绑带', 'optionList'), '绑带')
})

test('#8007 ② 多项按顿号并列（不是 String(array) 的英文逗号）', () => {
  assert.equal(formatSpecValue(['拼1次', '加铅块'], 'optionList'), '拼1次、加铅块')
  assert.equal(
    formatSpecValue(['余料带回-纱', '加铅块'], 'optionList'),
    '余料带回、加铅块'
  )
})

test('#8007 ④ 空数组 / 全空串 / 非字符串项 ⇒ 显式 —（不给 undefined / NaN）', () => {
  assert.equal(formatSpecValue([], 'optionList'), '—')
  assert.equal(formatSpecValue(['', '  '], 'optionList'), '—')
  assert.equal(formatSpecValue([null, 3, {}], 'optionList'), '—')
})

test('#8007/#8108 ⑤ 类级：同族两派生键并存 ⇒ 去重；独立选项名不得被折叠', () => {
  // 历史单切过帘体、或手改过 specialOptions ⇒ 同族两键并存；工人屏不印「绑带、绑带」
  assert.equal(formatSpecValue(['布绑带', '纱绑带'], 'optionList'), '绑带')
  assert.equal(formatSpecValue(['余料带回-布', '余料带回-纱'], 'optionList'), '余料带回')
  // 名字里含「绑带」字样但**不是**族成员：各自独立（各一道工序）
  assert.equal(formatSpecValue(['余料做绑带'], 'optionList'), '余料做绑带')
  assert.equal(formatSpecValue(['加立边', '加logo条'], 'optionList'), '加立边、加logo条')
})
