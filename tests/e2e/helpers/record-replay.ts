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
    fs.writeFileSync(filepath, JSON.stringify(body, null, 2))
    console.log(`[record] ✅ ${name} → ${filepath}`)
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
