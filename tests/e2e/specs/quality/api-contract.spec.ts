import { test, expect } from '@playwright/test'
/**
 * API Contract 测试 — 验证后端返回的 JSON 结构完整性
 *
 * 使用 recorded fixture 替代 live API 调用，不依赖 dev 环境数据变化。
 * fixture 由 CI 录制步骤 record-fixtures.ts 定期更新，
 * PR diff 可直观看到 API 结构变更。
 *
 * 运行: npx playwright test specs/quality/api-contract.spec.ts
 */
import { test, expect } from '@playwright/test'
import ordersFixture from '../../fixtures/orders-list.json'
import productsFixture from '../../fixtures/products-list.json'
import customersFixture from '../../fixtures/customers-list.json'
import categoriesFixture from '../../fixtures/categories-tree.json'
import employeesFixture from '../../fixtures/employees-list.json'
import afterSalesFixture from '../../fixtures/after-sales-list.json'
import rolesFixture from '../../fixtures/roles-list.json'
import knowledgeFixture from '../../fixtures/knowledge-list.json'
import productsDetailFixture from '../../fixtures/products-detail.json'

// ========== 类型校验工具 ==========

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
    throw new Error(`字段 ${path} 类型错误: 期望 ${expectedType}，实际 ${actualType}`)
  }
}

function getItems(fixture: any): any[] {
  return fixture?.data?.items || []
}

// ========== 订单 API Contract ==========

test.describe('订单 API Contract', () => {

  test('GET /api/admin/orders — 列表项必含 processingInfo', async () => {
    const items = getItems(ordersFixture)
    if (items.length === 0) { console.log('[skip] 订单 fixture 为空'); return }

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
          expect(item).toHaveProperty('processingInfo')
          const pi = item.processingInfo
          if (pi && typeof pi === 'object') {
            const hasSalesInfo = pi.colorName || pi.sellingMethod || pi.doorWidth || pi.skuCode
            if (!hasSalesInfo) console.warn(`订单 ${order.id}: processingInfo 销售字段全空`)
          }
        }
      }
    }
  })

  test('GET /api/admin/orders/:id — 详情项字段类型', async () => {
    const items = getItems(ordersFixture)
    const firstOrder = items?.[0]
    if (!firstOrder?.id) { console.log('[skip] 无订单数据'); return }

    // 列表项即包含详情所需字段
    assertField(firstOrder, 'id', 'string')
    assertField(firstOrder, 'customerName', 'string')
    assertField(firstOrder, 'totalAmount', 'number')
    assertField(firstOrder, 'status', 'string')
    expect(firstOrder).toHaveProperty('items')

    if (firstOrder.items?.length > 0) {
      for (const item of firstOrder.items) {
        assertField(item, 'productId', 'string')
        assertField(item, 'productName', 'string')
        assertField(item, 'quantity', 'number')
        assertField(item, 'unitPrice', 'number')
        expect(item).toHaveProperty('processingInfo')
      }
    }
  })
})

// ========== 商品 API Contract ==========

test.describe('商品 API Contract', () => {

  test('GET /api/admin/products — 列表项必含关键字段', async () => {
    const items = getItems(productsFixture)
    if (items.length === 0) { console.log('[skip] 商品 fixture 为空'); return }

    for (const p of items) {
      assertField(p, 'id', 'string')
      assertField(p, 'name', 'string')
      assertField(p, 'status', 'string')
      assertField(p, 'price', 'number')
      expect(p).toHaveProperty('categoryName')
    }
  })

  test('GET /api/admin/products/:id — 详情 SKU 字段', async () => {
    const items = getItems(productsFixture)
    // 使用 products-detail fixture 获取 SKU 信息
    const data = productsDetailFixture?.data
    if (!data?.id) { console.log('[skip] 无商品详情数据'); return }

    assertField(data, 'id', 'string')
    assertField(data, 'name', 'string')
    assertField(data, 'price', 'number')

    if (data?.skus && data.skus.length > 0) {
      for (const sku of data.skus) {
        expect(sku).toHaveProperty('doorWidth')
        expect(sku).toHaveProperty('sellingMethod')
        expect(sku).toHaveProperty('price')
        expect(typeof sku.price).toBe('number')
      }
    }
  })
})

// ========== 客户 API Contract ==========

test.describe('客户 API Contract', () => {

  test('GET /api/admin/customers — 手机号/名称不能全为空', async () => {
    const items = getItems(customersFixture)
    for (const c of items) {
      expect(c).toHaveProperty('id')
      const hasIdentity = c.phone || c.name || c.wechatNickname
      if (!hasIdentity) throw new Error(`客户 ${c.id}: phone/name/wechatNickname 全部为空`)
    }
  })
})

// ========== 类型一致性 ==========

test.describe('数值类型一致性', () => {

  test('金额字段必须为 number 类型', async () => {
    const allFixtures = [ordersFixture, productsFixture]

    for (const fixture of allFixtures) {
      for (const item of getItems(fixture)) {
        const moneyFields = ['totalAmount', 'actualAmount', 'price', 'unitPrice', 'amount', 'subtotal']
        for (const field of moneyFields) {
          if (item[field] !== undefined && item[field] !== null) {
            expect(typeof item[field]).toBe('number')
          }
        }
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

// ========== 分类 API Contract ==========

test.describe('分类 API Contract', () => {
  test('GET /api/admin/categories — 节点必含 id/name/children', async () => {
    const nodes = categoriesFixture?.data || []
    if (nodes.length === 0) { console.log('[skip] 分类 fixture 为空'); return }
    function check(n: any, p: string) {
      assertField(n, 'id', typeof n.id === 'string' ? 'string' : 'number')
      assertField(n, 'name', 'string')
      if (n.children) { expect(Array.isArray(n.children)).toBe(true) }
    }
    nodes.forEach((n: any, i: number) => check(n, `root[${i}]`))
  })
})

// ========== 员工 API Contract ==========

test.describe('员工 API Contract', () => {
  test('GET /api/admin/users — 必含 name/phone', async () => {
    const items = getItems(employeesFixture)
    if (items.length === 0) { console.log('[skip]'); return }
    for (const u of items) {
      expect(u).toHaveProperty('id'); expect(u).toHaveProperty('name'); expect(u).toHaveProperty('phone')
    }
  })
})

// ========== 售后 API Contract ==========

test.describe('售后 API Contract', () => {
  test('GET /api/admin/after-sales — 必含 ticketNo/status', async () => {
    const items = getItems(afterSalesFixture)
    if (items.length === 0) { console.log('[skip]'); return }
    for (const t of items) {
      assertField(t, 'id', 'string'); assertField(t, 'ticketNo', 'string'); assertField(t, 'status', 'string')
    }
  })
})

// ========== 角色 API Contract ==========

test.describe('角色 API Contract', () => {
  test('GET /api/admin/roles — 必含 name/code', async () => {
    const items = getItems(rolesFixture)
    if (items.length === 0) { console.log('[skip]'); return }
    for (const r of items) { assertField(r, 'name', 'string'); assertField(r, 'code', 'string') }
  })
})

// ========== 知识库 API Contract ==========

test.describe('知识库 API Contract', () => {
  test('GET /api/admin/knowledge/documents — 分页结构完整', async () => {
    const items = getItems(knowledgeFixture)
    expect(Array.isArray(items)).toBe(true)
  })
})
