// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5 报工页 —— **稳定短链那一跳的跨模块契约**（issue #4802；
// 设计 `docs/design/worker-h5-scan-and-report.md` §1.3 / §1.4）。
//
// 服务端（`WorkerShortLinkController` + `WorkerShortLinkService`）把
//   https://app.migaozn.com/s/<短码>   ──302──▶   /w/?t=<token>&tenant_id=<id>
// 本文件把**那一跳的落地形态**与**页面取码/取租户的口径**钉在一起：
// 服务端改 Location 形状而页面读不到（或反过来）⇒ 工人扫开短链只会看到空页面，
// 而两边各自的单测**都是绿的** —— 这正是本文件存在的理由。
//
// 四条判据（每条都有反向断言，防「恒真」）：
//   ① 302 目标必须被页面取出 token（`?t=`）与租户（`?tenant_id=`）；
//   ② 🔴 页面**自己不能**把短码换成 token（`/w/` 不带 `?t=` ⇒ 空码）
//      ⇒ 「短码 ⇒ token」只可能发生在**服务端 302** 那一跳（用户裁定③：部分扫码工具只认服务端跳转）；
//   ③ 手输短码（裸 8 位）原样当码值 ⇒ 前端**不判形态**（形态判定是服务端的职责）；
//   ④ 🔴 页面源码里**没有**「跳到 /s/」的 JS 跳转实现（静态守卫）—— 短链不得靠前端 JS 跳转。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { parseScanInput, tenantIdFromLocation } from '../src/scan-input.mjs'

const SRC_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', 'src')
const PART_CODE = 'fake-part-code-fixture-4802'
const SHORT_CODE = '7K3M9QP2'
/** 服务端 302 的 Location（`WorkerShortLinkService.reportPageLocation` 的逐字形态）。 */
const REDIRECT_TARGET = `https://app.migaozn.com/w/?t=${PART_CODE}&tenant_id=7`

test('① 服务端 302 的落地 URL：页面取到 token（?t=）', () => {
  assert.equal(parseScanInput(REDIRECT_TARGET), PART_CODE)
})

test('① 服务端 302 的落地 URL：页面取到租户（?tenant_id=，短链域名无租户子域）', () => {
  assert.equal(tenantIdFromLocation(REDIRECT_TARGET), 7)
  // 反向：不带 tenant_id 时判不出（⇒ 服务端必须带上它，否则工人登录判不出租户）
  assert.equal(tenantIdFromLocation(`https://app.migaozn.com/w/?t=${PART_CODE}`), null)
})

test('② 🔴 页面自己没有「短码 ⇒ token」能力 ⇒ 换发只能发生在服务端 302 那一跳', () => {
  // `/w/` 不带 ?t= ⇒ 取不到码（页面不会拿短码去换 token）
  assert.equal(parseScanInput('https://app.migaozn.com/w/?tenant_id=7'), '')
  // 反向自证（防恒真）：同一个函数对带 token 的形态**必须**取得到
  assert.equal(parseScanInput(`https://app.migaozn.com/w/?t=${PART_CODE}`), PART_CODE)
})

test('③ 手输短码：裸 8 位串原样作为码值（前端不判形态，交给服务端）', () => {
  assert.equal(parseScanInput(`  ${SHORT_CODE} `), SHORT_CODE)
})

test('④ 🔴 页面源码里不得有「跳到 /s/」的 JS 跳转（短链 = 服务端 302，不是前端跳转）', () => {
  const files = readdirSync(SRC_DIR).filter((f) => f.endsWith('.mjs'))
  assert.ok(files.length > 0, 'src/ 下必须有 .mjs 源文件（否则本判据是空跑）')

  // 只看「location 写语句」那一行：出现 /s/ 就说明有人把短链实现成了前端跳转
  const LOCATION_WRITE = /location\s*(?:\.href\s*=|\.assign\s*\(|\.replace\s*\()/
  const offenders = []
  for (const file of files) {
    const lines = readFileSync(join(SRC_DIR, file), 'utf8').split('\n')
    lines.forEach((line, i) => {
      if (LOCATION_WRITE.test(line) && line.includes('/s/')) {
        offenders.push(`${file}:${i + 1}: ${line.trim()}`)
      }
    })
  }
  assert.deepEqual(offenders, [], `短链不得靠前端 JS 跳转（服务端 302 是硬要求）：\n${offenders.join('\n')}`)
})
