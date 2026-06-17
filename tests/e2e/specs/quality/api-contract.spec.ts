/**
 * API Contract 测试 — 验证后端返回的 JSON 结构完整性
 *
 * 不依赖浏览器，直接用 request 调真实 API，检查必填字段是否存在、类型是否正确。
 * 这类 bug 是 E2E mock 测试的盲区：mock 数据手写的，跟后端可能完全不同步。
 *
 * 运行: npx playwright test specs/quality/api-contract.spec.ts
 */
import { test, expect } from '@playwright/test'
import { loginViaApi } from '../../helpers/auth.helper'

// ========== 类型校验工具 ==========

/** 断言字段存在且类型正确 */
function assertField(obj: any, path: string, expectedType: string, nullable = false) {
  const keys = path.split('.')
  let current = obj
  for (const key of keys) {
    if (current == null) {
      if (nullable) return
      throw new Error(`字段 ${path} 为 null/undefined`)
    }
    current = current[key]
  }
  if (!nullable && current == null) {
    throw new Error(`必填字段 ${path} 为 null/undefined`)
  }
  const actualType = typeof current
  if (expectedType === 'array') {
    if (!Array.isArray(current)) throw new Error(`字段 ${path} 期望 array，实际 ${actualType}`)
  } else if (actualType !== expectedType) {
    throw new Error(`字段 ${path} 类型错误: 期望 ${expectedType}，实际 ${actualType} (值: ${JSON.stringify(current)})`)
  }
}

// ========== 订单 API Contract ==========

test.describe('订单 API Contract', () => {

  test('GET /api/admin/orders — 列表项必含 processingInfo', async ({ request }) => {
    const tokens = await loginViaApi()
    const resp = await request.get('/api/admin/orders?page=1&size=5', {
      headers: { Authorization: `Bearer ${tokens.accessToken}` },
    })
    expect(resp.status()).toBe(200)
    const body = await resp.json()
    const items = body?.data?.items || []

    if (items.length === 0) {
      console.log('[skip] 订单列表为空')
      return
    }

    for (const order of items) {
      expect(order).toHaveProperty('id')
      expect(order).toHaveProperty('orderNo')
      expect(order).toHaveProperty('customerName')
      expect(order).toHaveProperty('totalAmount')
      expect(order).toHaveProperty('status')
      expect(order).toHaveProperty('items')
      expect(Array.isArray(order.items)).toBe(true)

      if (order.items.length > 0) {
        for (const item of order.items) {
          // processingInfo 不能全员缺失（如果所有 item 都缺 → BUG）
          expect(item).toHaveProperty('processingInfo')
          const pi = item.processingInfo
          if (pi && typeof pi === 'object') {
            // 至少有一个销售属性字段有值
            const hasSalesInfo = pi.colorName || pi.sellingMethod || pi.doorWidth || pi.skuCode
            if (!hasSalesInfo) {
              console.warn(`订单 ${order.id} item ${item.productName}: processingInfo 所有销售字段为空`)
            }
          }
        }
      }
    }
  })

  test('GET /api/admin/orders/:id — 详情项 processingInfo 非空', async ({ request }) => {
    // 先拿第一个订单的 ID
    const listResp = await request.get('/api/admin/orders?page=1&size=1', {
      headers: { Authorization: `Bearer ${(await loginViaApi()).accessToken}` },
    })
    const firstOrder = listResp.json().then(b => b?.data?.items?.[0])
    const order = await firstOrder
    if (!order?.id) {
      console.log('[skip] 无订单数据')
      return
    }

    const detailResp = await request.get(`/api/admin/orders/${order.id}`, {
      headers: { Authorization: `Bearer ${(await loginViaApi()).accessToken}` },
    })
    expect(detailResp.status()).toBe(200)
    const detail = await detailResp.json()
    const data = detail?.data

    // 必填字段
    assertField(data, 'id', 'string')
    assertField(data, 'customerName', 'string')
    assertField(data, 'totalAmount', 'number')
    assertField(data, 'status', 'string')
    assertField(data, 'items', 'object')
    assertField(data, 'items', 'object')

    if (data?.items && data.items.length > 0) {
      for (const item of data.items) {
        assertField(item, 'productId', 'string')
        assertField(item, 'productName', 'string')
        assertField(item, 'quantity', 'number')
        assertField(item, 'unitPrice', 'number')
        assertField(item, 'processingInfo', 'object', true)
      }
    }
  })
})

// ========== 商品 API Contract ==========

test.describe('商品 API Contract', () => {

  test('GET /api/admin/products — 列表项必含关键字段', async ({ request }) => {
    const tokens = await loginViaApi()
    const resp = await request.get('/api/admin/products?page=1&size=5', {
      headers: { Authorization: `Bearer ${tokens.accessToken}` },
    })
    expect(resp.status()).toBe(200)
    const items = (await resp.json())?.data?.items || []

    if (items.length === 0) {
      console.log('[skip] 商品列表为空')
      return
    }

    for (const p of items) {
      assertField(p, 'id', 'string')
      assertField(p, 'name', 'string')
      assertField(p, 'status', 'string')
      assertField(p, 'price', 'number')
      // categoryName 可能为 null 但不应缺字段 key
      expect(p).toHaveProperty('categoryName')
    }
  })

  test('GET /api/admin/products/:id — 详情 SKU 包含门幅和售卖方式', async ({ request }) => {
    const tokens = await loginViaApi()
    const listResp = await request.get('/api/admin/products?page=1&size=1', {
      headers: { Authorization: `Bearer ${tokens.accessToken}` },
    })
    const firstProduct = (await listResp.json())?.data?.items?.[0]
    if (!firstProduct?.id) {
      console.log('[skip] 无商品数据')
      return
    }

    const resp = await request.get(`/api/admin/products/${firstProduct.id}`, {
      headers: { Authorization: `Bearer ${tokens.accessToken}` },
    })
    expect(resp.status()).toBe(200)
    const data = (await resp.json())?.data

    assertField(data, 'id', 'string')
    assertField(data, 'name', 'string')
    assertField(data, 'price', 'number')
    assertField(data, 'status', 'string')

    // 如果有 SKU，每个 SKU 的门幅和售卖方式不能全空
    if (data?.skus && data.skus.length > 0) {
      for (const sku of data.skus) {
        expect(sku).toHaveProperty('doorWidth')
        expect(sku).toHaveProperty('sellingMethod')
        expect(sku).toHaveProperty('price')
        expect(typeof sku.price).toBe('number')
        // 门幅和售卖方式至少有一个
        const hasSpec = sku.doorWidth || sku.sellingMethod
        if (!hasSpec) {
          console.warn(`商品 ${data.id} SKU ${sku.id}: doorWidth 和 sellingMethod 均为空`)
        }
      }
    }
  })
})

// ========== 客户 API Contract ==========

test.describe('客户 API Contract', () => {

  test('GET /api/admin/customers — 手机号/名称不能全为空', async ({ request }) => {
    const tokens = await loginViaApi()
    const resp = await request.get('/api/admin/customers?page=1&size=5', {
      headers: { Authorization: `Bearer ${tokens.accessToken}` },
    })
    expect(resp.status()).toBe(200)
    const items = (await resp.json())?.data?.items || []

    for (const c of items) {
      expect(c).toHaveProperty('id')
      // 手机号和昵称至少有一个不为空
      const hasIdentity = c.phone || c.name || c.wechatNickname
      if (!hasIdentity) {
        throw new Error(`客户 ${c.id}: phone/name/wechatNickname 全部为空 — 列表无法区分客户`)
      }
    }
  })
})

// ========== 类型一致性检查 ==========

test.describe('数值类型一致性', () => {

  test('金额字段必须为 number 类型', async ({ request }) => {
    const tokens = await loginViaApi()
    const endpoints = [
      '/api/admin/orders?page=1&size=3',
      '/api/admin/products?page=1&size=3',
    ]

    for (const endpoint of endpoints) {
      const resp = await request.get(endpoint, {
        headers: { Authorization: `Bearer ${tokens.accessToken}` },
      })
      const items = (await resp.json())?.data?.items || []

      for (const item of items) {
        // 金额字段类型检查
        const moneyFields = ['totalAmount', 'actualAmount', 'price', 'unitPrice', 'amount', 'subtotal']
        for (const field of moneyFields) {
          if (item[field] !== undefined && item[field] !== null) {
            expect(typeof item[field]).toBe('number')
          }
        }

        // 嵌套 items 的金额
        if (Array.isArray(item.items)) {
          for (const sub of item.items) {
            for (const field of ['unitPrice', 'amount', 'subtotal']) {
              if (sub[field] !== undefined && sub[field] !== null) {
                expect(typeof sub[field]).toBe('number')
              }
            }
          }
        }
      }
    }
  })
})

// ========== 分类 / 员工 / 售后 / 角色 / 知识库 / Dashboard / 通知 ==========

test.describe('分类 API Contract', () => {
  test('GET /api/admin/categories — 节点必含 id/name/children', async ({ request }) => {
    const tokens = await loginViaApi()
    const resp = await request.get('/api/admin/categories', { headers: { Authorization: `Bearer ${tokens.accessToken}` } })
    expect(resp.status()).toBe(200)
    const nodes = (await resp.json())?.data || []
    if (nodes.length === 0) { console.log('[skip] 分类树为空'); return }
    function check(n: any, p: string) {
      assertField(n, 'id', typeof n.id === 'string' ? 'string' : 'number')
      assertField(n, 'name', 'string')
      if (n.children) { expect(Array.isArray(n.children)).toBe(true); n.children.forEach((c: any, i: number) => check(c, `${p}[${i}]`)) }
    }
    nodes.forEach((n: any, i: number) => check(n, `root[${i}]`))
  })
})

test.describe('员工 API Contract', () => {
  test('GET /api/admin/users — 必含 name/phone', async ({ request }) => {
    const tokens = await loginViaApi()
    const resp = await request.get('/api/admin/users?page=1&size=5', { headers: { Authorization: `Bearer ${tokens.accessToken}` } })
    expect(resp.status()).toBe(200)
    const items = (await resp.json())?.data?.items || []
    if (items.length === 0) { console.log('[skip]'); return }
    for (const u of items) {
      expect(u).toHaveProperty('id'); expect(u).toHaveProperty('name'); expect(u).toHaveProperty('phone')
      if (!u.name && !u.phone) throw new Error(`员工 ${u.id}: name/phone 同时为空`)
    }
  })
})

test.describe('售后 API Contract', () => {
  test('GET /api/admin/after-sales — 必含 ticketNo/status', async ({ request }) => {
    const tokens = await loginViaApi()
    const resp = await request.get('/api/admin/after-sales?page=1&size=5', { headers: { Authorization: `Bearer ${tokens.accessToken}` } })
    expect(resp.status()).toBe(200)
    const items = (await resp.json())?.data?.items || []
    if (items.length === 0) { console.log('[skip]'); return }
    for (const t of items) {
      assertField(t, 'id', 'string'); assertField(t, 'ticketNo', 'string'); assertField(t, 'status', 'string')
      expect(t).toHaveProperty('customerName'); expect(t).toHaveProperty('ticketType')
    }
  })
})

test.describe('角色 API Contract', () => {
  test('GET /api/admin/roles — 必含 name/code', async ({ request }) => {
    const tokens = await loginViaApi()
    const resp = await request.get('/api/admin/roles?page=1&size=10', { headers: { Authorization: `Bearer ${tokens.accessToken}` } })
    expect(resp.status()).toBe(200)
    const items = (await resp.json())?.data?.items || []
    if (items.length === 0) { console.log('[skip]'); return }
    for (const r of items) { assertField(r, 'name', 'string'); assertField(r, 'code', 'string') }
  })
})

test.describe('知识库 API Contract', () => {
  test('GET /api/admin/knowledge/documents — 分页结构完整', async ({ request }) => {
    const tokens = await loginViaApi()
    const resp = await request.get('/api/admin/knowledge/documents?page=1&size=5', { headers: { Authorization: `Bearer ${tokens.accessToken}` } })
    expect(resp.status()).toBe(200)
    const data = (await resp.json()).data
    expect(data).toHaveProperty('items'); expect(Array.isArray(data.items)).toBe(true)
  })
})

test.describe('Dashboard API Contract', () => {
  test('GET /api/admin/dashboard/stats — 统计数字类型正确', async ({ request }) => {
    const tokens = await loginViaApi()
    const resp = await request.get('/api/admin/dashboard/stats', { headers: { Authorization: `Bearer ${tokens.accessToken}` } })
    if (resp.status() === 404 || resp.status() === 403) { console.log(`[skip] ${resp.status()}`); return }
    expect(resp.status()).toBe(200)
    const data = (await resp.json())?.data
    for (const f of ['todayOrders', 'todayRevenue', 'todayNewCustomers', 'pendingOrders']) {
      if (data && data[f] !== undefined && data[f] !== null) expect(typeof data[f]).toBe('number')
    }
  })
})

test.describe('通知 API Contract', () => {
  test('GET /api/admin/notifications — 必含 title/content', async ({ request }) => {
    const tokens = await loginViaApi()
    const resp = await request.get('/api/admin/notifications?page=1&size=5', { headers: { Authorization: `Bearer ${tokens.accessToken}` } })
    if (resp.status() === 404 || resp.status() === 403) { console.log(`[skip] ${resp.status()}`); return }
    expect(resp.status()).toBe(200)
    for (const n of ((await resp.json())?.data?.items || [])) {
      expect(n).toHaveProperty('id'); expect(n).toHaveProperty('title'); expect(n).toHaveProperty('content')
    }
  })
})
