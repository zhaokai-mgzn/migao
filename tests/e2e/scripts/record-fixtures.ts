/**
 * Fixture 录制脚本
 *
 * 用法:
 *   cd tests
 *   BASE_URL=http://localhost:8080 npx tsx e2e/scripts/record-fixtures.ts
 *
 * 录制所有关键 API 的实际响应到 fixtures/ 目录。
 * 之后 E2E 测试用真实数据 mock，不再手写 mock 数据。
 */
import { loginViaApi } from '../helpers/auth.helper'
import { recordFixture } from '../helpers/record-replay'

const PHONE = process.env.E2E_ADMIN_PHONE || '13800138000'
const CODE = process.env.E2E_SMS_CODE || '123456'

async function main() {
  console.log('📡 开始录制 API fixtures...')
  console.log(`   BASE_URL: ${process.env.BASE_URL || '默认'}`)
  console.log(`   login: ${PHONE} / ${CODE}`)

  const tokens = await loginViaApi(PHONE, CODE)
  const auth = { Authorization: `Bearer ${tokens.accessToken}` }

  // ====== 订单 ======
  console.log('\n--- 订单 ---')
  const ordersResp = await recordFixture('orders-list', 'GET',
    `${getBaseUrl()}/api/admin/orders?page=1&size=5`, { headers: auth })
  const firstOrderId = ordersResp?.data?.items?.[0]?.id
  if (firstOrderId) {
    await recordFixture('orders-detail', 'GET',
      `${getBaseUrl()}/api/admin/orders/${firstOrderId}`, { headers: auth })
  }

  // ====== 商品 ======
  console.log('\n--- 商品 ---')
  const productsResp = await recordFixture('products-list', 'GET',
    `${getBaseUrl()}/api/admin/products?page=1&size=5`, { headers: auth })
  const firstProductId = productsResp?.data?.items?.[0]?.id
  if (firstProductId) {
    await recordFixture('products-detail', 'GET',
      `${getBaseUrl()}/api/admin/products/${firstProductId}`, { headers: auth })
  }

  // ====== 客户 ======
  console.log('\n--- 客户 ---')
  await recordFixture('customers-list', 'GET',
    `${getBaseUrl()}/api/admin/customers?page=1&size=5`, { headers: auth })

  // ====== 售后 ======
  console.log('\n--- 售后 ---')
  await recordFixture('after-sales-list', 'GET',
    `${getBaseUrl()}/api/admin/after-sales?page=1&size=5`, { headers: auth })

  // ====== 分类/加工项 ======
  console.log('\n--- 分类/加工项 ---')
  await recordFixture('categories-list', 'GET',
    `${getBaseUrl()}/api/admin/categories?page=1&size=10`, { headers: auth })

  const catResp = await recordFixture('categories-tree', 'GET',
    `${getBaseUrl()}/api/admin/categories/tree`, { headers: auth })

  // 用第一个分类 ID 拉加工项
  const catId = catResp?.data?.[0]?.id
  if (catId) {
    // 通用加工项接口 — 直接用列表
  }
  await recordFixture('processing-list', 'GET',
    `${getBaseUrl()}/api/admin/processing-items?page=1&size=10`, { headers: auth })

  // ====== 员工/角色 ======
  console.log('\n--- 员工/角色 ---')
  await recordFixture('employees-list', 'GET',
    `${getBaseUrl()}/api/admin/users?page=1&size=10`, { headers: auth })
  await recordFixture('roles-list', 'GET',
    `${getBaseUrl()}/api/admin/roles?page=1&size=10`, { headers: auth })

  // ====== 知识库 ======
  console.log('\n--- 知识库 ---')
  await recordFixture('knowledge-list', 'GET',
    `${getBaseUrl()}/api/admin/knowledge/documents?page=1&size=10`, { headers: auth })

  console.log('\n✅ 录制完成。fixtures/ 目录已更新。')
}

function getBaseUrl(): string {
  // Playwright 在 test 中有 baseURL，录制脚本用环境变量
  return process.env.BASE_URL || 'http://localhost:8080'
}

main().catch((e) => {
  console.error('录制失败:', e)
  process.exit(1)
})
