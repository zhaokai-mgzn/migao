// case_ids: PG-018, BM-006, DF-017, BM-045
//
// 工人端 H5 报工页 —— **扫码入口解析**（issue #4716 §1.3 / §1.4 / §1.5）。
//
// 三条硬约束逐条落成断言：
//   ① 码 = 标准 HTTPS URL ⇒ 页面**必须**能从 URL 里取出码值（`/w/?t=<token>`、`?t=`、`#t=`）；
//   ② 人可读短码兜底 ⇒ 手输的**裸串**（短码 / 旧 token / 加工单号）必须原样当码值用，
//      **不得**在前端判形态（判形态是服务端 `resolveOrder` 的职责，切片①已实现）；
//   ③ 空/纯空白输入 ⇒ **不发请求**（不得把空串当码去扫）。
import test from 'node:test'
import assert from 'node:assert/strict'

import { enterpriseCodeFromLocation, parseScanInput } from '../src/scan-input.mjs'

test('① 扫一扫：标准 HTTPS URL 的 ?t=<token> 取出 token', () => {
  assert.equal(parseScanInput('https://app.migaozn.com/w/?t=7K3M9QP2ABCDEF', 'https://app.migaozn.com/w/'),
    '7K3M9QP2ABCDEF')
})

test('① URL 路径段也认（/s/<短码> 形态，服务端重定向前后的两种写法都取得到）', () => {
  assert.equal(parseScanInput('https://app.migaozn.com/s/7K3M9QP2', 'https://app.migaozn.com/w/'), '7K3M9QP2')
})

test('① hash 形态（#t=…）同样取得到 —— 扫码工具/短链实现细节不该让页面瞎掉', () => {
  assert.equal(parseScanInput('https://app.migaozn.com/w/#t=abc123', 'https://app.migaozn.com/w/'), 'abc123')
})

test('① 其它 query 键不认（只认 t / token / code）—— 不得把无关参数当码', () => {
  assert.equal(parseScanInput('https://app.migaozn.com/w/?foo=bar', 'https://app.migaozn.com/w/'), '')
})

test('② 手输短码：裸串原样作为码值（前端不判形态）', () => {
  assert.equal(parseScanInput('  7K3M9QP2  ', 'https://app.migaozn.com/w/'), '7K3M9QP2')
  // 存量旧码 = 裸 qr_token（32 位 hex）/ 加工单号 —— 一律原样交给服务端
  assert.equal(parseScanInput('9f8e7d6c5b4a39281706f5e4d3c2b1a0', ''), '9f8e7d6c5b4a39281706f5e4d3c2b1a0')
  assert.equal(parseScanInput('JG20260920001', ''), 'JG20260920001')
})

test('③ 空输入 ⇒ 空串（调用方据此不发请求）', () => {
  for (const v of ['', '   ', null, undefined]) {
    assert.equal(parseScanInput(v, 'https://app.migaozn.com/w/'), '')
  }
})

test('企业编码：从短链 302 的 ?tenant_code= 取值（形态与后端 LoginIdentifiers 同形）', () => {
  assert.equal(enterpriseCodeFromLocation('https://app.migaozn.com/w/?t=x&tenant_code=migao'), 'migao')
  // 存量带下划线的企业编码（tenant_7478359537 形态）必须认
  assert.equal(enterpriseCodeFromLocation('https://app.migaozn.com/w/?tenant_code=tenant_7478359537'),
    'tenant_7478359537')
  // 反向（防恒真）：缺失 / 形态不合法 / 非 URL ⇒ null（由登录表单填）
  assert.equal(enterpriseCodeFromLocation('https://app.migaozn.com/w/?t=x'), null)
  assert.equal(enterpriseCodeFromLocation('https://app.migaozn.com/w/?tenant_code=MIGAO'), null)
  assert.equal(enterpriseCodeFromLocation('https://app.migaozn.com/w/?tenant_code=a'), null)
  assert.equal(enterpriseCodeFromLocation('not a url'), null)
})
