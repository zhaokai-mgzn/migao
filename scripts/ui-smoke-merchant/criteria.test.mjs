// case_ids: MC-012
// 商家冒烟 spec 判据的「最小可执行单元」测试（issue #4226）。
//
// 为什么需要它（本文件存在的理由）：`scripts/ui-smoke-merchant/spec.mjs` 是商家后台的
// 主要 UI 回归网，但它的**判据本身**曾不可信，三处互相独立。三处中有两处（① 单号判据、
// ③ 404 豁免）是**纯函数级**的判定 —— 真跑整条旅程需要线上/真实商家数据（本地起栈成本高，
// 且本轮云 dev 库不可达），故按 issue #4226「红证的替代口径」把判据抽到 `criteria.mjs`，
// 在这里用 node 内置测试器（`node:test` + `node:assert`，**不引入新依赖**）做红证。
//
// 判据口径（每条都要有「改动前必红」的实测输出）：
//   ① `matchProcessingOrderNo('JG-20260918-9049')` 改动前**假**（旧正则 `/PO-…|PG-…/`
//      永不命中真实单号 ⇒ 证据里恒为「加工单可见=false」= 空判据），改动后**真**；
//      并断言旧正则对真实号**不命中**（把「空判据」这件事本身钉成可执行判据）。
//   ③ `{errors:['…404…'], responses:[{status:404}]}` 旧写法**被豁免**（假绿）而新判据**不豁免**；
//      反向 `{errors:[真探测 console 文案], responses:[{status:404}]}` 仍被豁免（防改过头把真豁免拆了）。
//   ② 不在这里判 —— 它是「有没有用 waitFor 取代定长 sleep」的**源码形状**判据，
//      归 `tests/unit_ci_workflows/test_ui_smoke_criteria_trust.py`（静态扫描 spec.mjs 源码）。
//
// 跑法：`node --test scripts/ui-smoke-merchant/criteria.test.mjs`
//（CI 由上述 pytest 守卫以子进程方式执行，故本文件不必自带 runner 入口）
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  ORDER_NO_SHAPE,
  matchProcessingOrderNo,
  isConsoleProbe404,
  isProbe404Exempt,
} from './criteria.mjs'

/** 实测真值（issue #4226 现场）：真实加工单号形态与截图证据里的号 */
const REAL_PO_NO = 'JG-20260918-9049'
/** 旧判据原文（改动前 spec.mjs 第 581 行）：前缀靠猜 ⇒ 永不命中真实号 */
const OLD_LOOSE_LOCATOR = /PO-[0-9-]+|PG-[0-9-]+/
/** 加工单未生成时组件探测的 URL（GET /api/admin/processing-orders/{orderId}） */
const PROBE_URL = 'http://127.0.0.1:8090/api/admin/processing-orders/403fee51621a1460899a9ac98be3f860'
/** 浏览器为 404 响应打印的 console 文案（spec.mjs 里被收进 res.errors 的那条） */
const CONSOLE_PROBE_404 =
  '[console.error] Failed to load resource: the server responded with a status of 404 (Not Found)'

/** 改动前的豁免实现（spec.mjs 第 550~551 行原文，逐字复刻）：用于证明「改动前必绿」 */
function oldExempt(errors, responses) {
  const probe404 = errors.filter((e) => e.includes('Failed to load resource') && e.includes('404'))
  return Boolean(probe404.length && errors.every((e) => e.includes('404')))
}

test('① 真实加工单号（JG- 前缀）必须命中；旧前缀判据对它永不命中', () => {
  // 改动后的判据：按形态取号，不猜前缀
  assert.equal(matchProcessingOrderNo(REAL_PO_NO), REAL_PO_NO)
  assert.equal(matchProcessingOrderNo(`加工单 ${REAL_PO_NO} 已发加工`), REAL_PO_NO)
  assert.equal(matchProcessingOrderNo('该订单无加工单'), null)
  // 红证的另一半：旧判据对真实号**不命中**（这就是「加工单可见=false」恒定的原因）
  assert.equal(OLD_LOOSE_LOCATOR.test(REAL_PO_NO), false)
  // 新判据里不得残留任何前缀白名单（PO-/PG- 除外写法）
  assert.equal(/PO-|PG-/.test(ORDER_NO_SHAPE.source), false)
  // 形态判据本身要能命中非 JG 前缀的真实单号（不把 JG 写死成第二个白名单）
  assert.equal(matchProcessingOrderNo('ZZ-20260101-1'), 'ZZ-20260101-1')
  // ⚠️ 边界判据：**3 字母前缀**的单号（订单号 ORD-… 形态、流水号 FIN-…）不得被「错开一位」命中
  //    （不加边界时 `ORD-20260918-1234` 会匹配出 `RD-20260918-1234` ⇒ 又变成「命中别的单号」的假绿）
  assert.equal(matchProcessingOrderNo('ORD-20260918-1234'), null)
  assert.equal(matchProcessingOrderNo('FIN-20260918-0001'), null)
  assert.equal(matchProcessingOrderNo('订单号 ORD-20260918-1234'), null)
  // 块内文本（真实形态：号 + 状态文案紧邻）仍要能取到
  assert.equal(matchProcessingOrderNo('JG-20260918-9049已发加工加工方：冒烟加工厂'), 'JG-20260918-9049')
})

test('③ 404 豁免必须结构化：旅程自身失败且文案含 404 ⇒ 不得被豁免', () => {
  // 正向（防改过头）：真探测产生的 console 文案 + 结构化 404 响应 ⇒ 仍豁免
  assert.equal(isProbe404Exempt([CONSOLE_PROBE_404], [{ url: PROBE_URL, status: 404 }]), true)
  assert.equal(isConsoleProbe404(CONSOLE_PROBE_404), true)
  // 负向：旅程自身抛出、文案里恰好含 404 ⇒ 旧写法**豁免**（假绿），新判据**不豁免**
  const ownError = '订单详情失败: 等待加工单元素超时 404'
  assert.equal(oldExempt([ownError, CONSOLE_PROBE_404], [{ url: PROBE_URL, status: 404 }]), true)
  assert.equal(isProbe404Exempt([ownError, CONSOLE_PROBE_404], [{ url: PROBE_URL, status: 404 }]), false)
  // 没有结构化 404 响应时，只凭文案不得豁免
  assert.equal(isProbe404Exempt([CONSOLE_PROBE_404], []), false)
  assert.equal(isProbe404Exempt([CONSOLE_PROBE_404], [{ url: PROBE_URL, status: 500 }]), false)
  // 别的资源 404（非加工单探测）混进来：文案条数 > 探测次数 ⇒ 不豁免
  assert.equal(isProbe404Exempt([CONSOLE_PROBE_404, CONSOLE_PROBE_404], [{ url: PROBE_URL, status: 404 }]), false)
  // 非加工单 URL 的 404 响应不算探测（不能拿别的 404 顶包）
  assert.equal(isProbe404Exempt([CONSOLE_PROBE_404], [{ url: 'http://x/api/admin/orders/1/print', status: 404 }]), false)
  // pageerror 里的 404 文案不是「资源加载失败」，不得参与豁免
  assert.equal(isConsoleProbe404('[pageerror] Error: timeout 404'), false)
})
