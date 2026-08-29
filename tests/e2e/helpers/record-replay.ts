/**
 * Record-Replay Mock 系统
 *
 * 解决问题: E2E mock 数据手写，跟后端实际返回不同步，导致假绿测试。
 *
 * 录制: cd tests && BASE_URL=http://localhost:8080 npx tsx e2e/scripts/record-fixtures.ts
 * 回放: 测试中直接 import fixtures 目录下的 JSON 文件
 *
 * 使用:
 *   import ordersList from '../fixtures/orders-list.json'
 *   await page.route('**\/api/admin/orders*', route => route.fulfill({ body: JSON.stringify(ordersList) }))
 */

import { type Page, type APIRequestContext, request as pwRequest } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'
import { withRetry } from './retry.helper'

const FIXTURE_DIR = path.join(process.cwd(), 'e2e', 'fixtures')

// ========== 敏感数据脱敏（录制即脱敏，2026-08-29 加固）==========
// 确定性映射（同源号码 → 同掩码），保持跨 fixture 文件一致；测试只校验字段存在性，不校验具体值。
const MASK_CACHE: Record<string, string> = {}
const PHONE_RE = /(?<!\d)1\d{10}(?!\d)/

function maskPhone(n: string): string {
  if (MASK_CACHE[n]) return MASK_CACHE[n]
  // 简单确定性散列：md5 前 8 位 hex → 数字 → 4 位中段
  let h = 0
  for (let i = 0; i < n.length; i++) h = (h * 31 + n.charCodeAt(i)) >>> 0
  const mid = String(h % 10000).padStart(4, '0')
  const out = n.slice(0, 3) + mid + n.slice(-4)
  MASK_CACHE[n] = out
  return out
}

function maskValue(v: unknown): unknown {
  if (typeof v === 'string') {
    return v.replace(PHONE_RE, (m) => maskPhone(m))
  }
  if (Array.isArray(v)) return v.map(maskValue)
  if (v !== null && typeof v === 'object') {
    const out: Record<string, unknown> = {}
    for (const [k, val] of Object.entries(v as Record<string, unknown>)) out[k] = maskValue(val)
    return out
  }
  return v
}

function maskSensitiveData(body: unknown): unknown {
  return maskValue(body)
}

// ========== 录制 (仅 tsx 脚本使用，不用于测试) ==========

export async function recordFixture(
  name: string,
  method: 'GET' | 'POST',
  url: string,
  options?: { body?: any; headers?: Record<string, string> },
): Promise<any> {
  const ctx: APIRequestContext = await pwRequest.newContext()
  try {
    const reqOpts: any = { headers: options?.headers || {} }
    if (options?.body) reqOpts.data = options.body

    // Retry on 5xx / network errors — transient dev-server outages
    const body = await withRetry(
      async () => {
        const resp = await ctx[method === 'GET' ? 'get' : 'post'](url, reqOpts)
        if (!resp.ok()) {
          throw new Error(
            `recordFixture ${name} failed (${resp.status()}): ${await resp.text()}`,
          )
        }
        return resp.json()
      },
      {
        maxRetries: 5,
        baseDelayMs: 3000,
        shouldRetry: (err) => {
          const msg = (err as Error).message || ''
          return /5\d\d|ECONNREFUSED|ETIMEDOUT|ENOTFOUND|EPIPE|ECONNRESET/.test(msg)
        },
      },
    )

    const filepath = path.join(FIXTURE_DIR, `${name}.json`)
    if (!fs.existsSync(FIXTURE_DIR)) fs.mkdirSync(FIXTURE_DIR, { recursive: true })
    fs.writeFileSync(filepath, JSON.stringify(maskSensitiveData(body), null, 2))
    console.log(`[record] ✅ ${name} → ${filepath} (sensitive data masked)`)
    return body
  } finally {
    await ctx.dispose()
  }
}

// ========== 回放 (测试中使用) ==========

/**
 * 安装 fixture 到 page route。
 * JSON fixture 文件必须放在 tests/e2e/fixtures/ 目录下。
 *
 * @example
 *   await replayFixture(page, 'orders-list', '**\/api/admin/orders*')
 */
export async function replayFixture(page: Page, fixtureName: string, urlPattern: string) {
  // 动态 import JSON fixture（Playwright 支持）
  const data = await import(`../fixtures/${fixtureName}.json`)
  await page.route(urlPattern, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(data.default ?? data),
    })
  })
}
