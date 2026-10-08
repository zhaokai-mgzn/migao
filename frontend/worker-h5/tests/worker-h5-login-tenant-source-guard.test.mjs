// case_ids: BM-045
//
// 类级元守卫（AGENTS.md 铁律 8「类级固化」，issue #6564）：
// 工人端 H5 的登录请求体**租户只由服务端解析** —— 前端不得再送 `tenantId`（默认租户 = 恒 401 的根因），
// 必须送 `enterpriseCode`（企业编码）。
//
// 与 bmini 侧同族守卫：frontend/bmini-app/tests/worker-login-tenant-source-guard.test.ts
// （两边各覆盖自己那份源码；注释一律剥掉后再扫 —— 讲沿革的注释不算请求体）。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', 'src')
const strip = (code) => code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
const code = (rel) => strip(readFileSync(join(SRC_DIR, rel), 'utf8'))

test('🔴 api.mjs 的登录请求体：含 enterpriseCode、不含 tenantId', () => {
  const api = code('api.mjs')
  assert.ok(api.includes('/api/worker/login'))
  assert.ok(api.includes('enterpriseCode'), '登录 body 必须带企业编码（租户只由服务端解析）')
  assert.deepEqual(api.match(/\btenantId\b/g), null, 'api.mjs 不得再出现 tenantId')
  assert.ok(!api.includes('DEFAULT_TENANT_ID'), 'api.mjs 不得引用默认租户常量')
})

test('🔴 工人端 H5 源码里不得有默认租户常量（工人面从不拍租户）', () => {
  for (const rel of ['api.mjs', 'app.mjs', 'render.mjs', 'scan-input.mjs']) {
    assert.ok(!code(rel).includes('DEFAULT_TENANT_ID'), `${rel} 不得引用 DEFAULT_TENANT_ID`)
  }
})

test('登录表单 + 应用装配：企业编码从 URL 初值进 state、提交时读输入框', () => {
  const render = code('render.mjs')
  const app = code('app.mjs')
  assert.ok(render.includes('wh5-enterprise-code'), '登录表单必须有企业编码输入框')
  assert.ok(render.includes('enterpriseCode'), '输入框初值来自 state.enterpriseCode（URL 的 ?tenant_code=）')
  assert.ok(app.includes('enterpriseCodeFromLocation'), 'app.mjs 必须从 URL 取企业编码作初值')
  assert.ok(app.includes('wh5-enterprise-code'), 'app.mjs 提交时读输入框（URL 值只是初值）')
})
