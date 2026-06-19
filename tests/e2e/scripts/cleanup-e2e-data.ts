/**
 * E2E 测试数据清理脚本
 *
 * 每次 E2E 测试运行前/后执行，清除上一次测试产生的脏数据。
 * 识别规则：名称包含 "E2E" 前缀的均为测试数据，直接删除。
 *
 * 使用方式：
 *   手动:  cd tests && npx tsx e2e/scripts/cleanup-e2e-data.ts
 *   自动:  playwright.config.ts → globalSetup
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'https://api.migaozn.com'
const TEST_PHONE = process.env.E2E_ADMIN_PHONE || '13800138000'
const TEST_SMS_CODE = process.env.E2E_SMS_CODE || '123456'

// ==================== 工具函数 ====================

async function apiPost(path: string, body: unknown, token?: string) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_BASE_URL}${path}`, { method: 'POST', headers, body: JSON.stringify(body) })
  return res.json()
}

async function apiGet(path: string, token: string) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  return res.json()
}

async function apiDelete(path: string, token: string) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  })
  return res.json()
}

async function login(): Promise<string> {
  const json = await apiPost('/api/auth/sms/login', {
    phone: TEST_PHONE,
    code: TEST_SMS_CODE,
  })
  if (!json.success) throw new Error(`Login failed: ${JSON.stringify(json.error)}`)
  return json.data.accessToken
}

const E2E_PATTERN = /^E2E/

function isE2EData(name: string): boolean {
  return E2E_PATTERN.test(name)
}

// ==================== 清理函数 ====================

async function cleanupResource(
  token: string,
  resource: string,
  listPath: string,
  deletePath: (id: string) => string,
  nameField = 'name',
  extraFilter?: (item: Record<string, unknown>) => boolean,
): Promise<number> {
  const json = await apiGet(listPath, token)
  const items: Record<string, unknown>[] = json?.data?.items ?? json?.data ?? []

  const toDelete = items.filter((item) => {
    const name = String(item[nameField] ?? '')
    if (isE2EData(name)) return true
    if (extraFilter) return extraFilter(item)
    return false
  })

  let deleted = 0
  for (const item of toDelete) {
    try {
      const res = await apiDelete(deletePath(item.id as string), token)
      if (res.success) deleted++
    } catch {
      // 删除失败静默跳过（可能已被关联约束保护）
    }
  }

  if (toDelete.length > 0) {
    console.log(`  ${resource}: 删除 ${deleted}/${toDelete.length}`)
  } else {
    console.log(`  ${resource}: 无脏数据`)
  }

  return deleted
}

// ==================== 主流程 ====================

async function main() {
  console.log('\n🧹 E2E 数据清理')
  console.log(`   API: ${API_BASE_URL}`)

  const token = await login()
  console.log('   登录成功\n')

  let total = 0

  // 订单 — E2E 订单客户名含 "E2E"
  total += await cleanupResource(
    token,
    '订单',
    '/api/admin/orders?size=200',
    (id) => `/api/admin/orders/${id}`,
    'customerName',
  )

  // 商品 — 名称含 "E2E" 前缀
  total += await cleanupResource(
    token,
    '商品',
    '/api/admin/products?size=200',
    (id) => `/api/admin/products/${id}`,
    'name',
  )

  // 分类 — 名称含 "E2E" 前缀
  total += await cleanupResource(
    token,
    '分类',
    '/api/admin/categories',
    (id) => `/api/admin/categories/${id}`,
    'name',
  )

  // 客户 — 名称含 "E2E"
  total += await cleanupResource(
    token,
    '客户',
    '/api/admin/customers?size=200',
    (id) => `/api/admin/customers/${id}`,
    'name',
  )

  // 加工项 — 名称含 "E2E"
  total += await cleanupResource(
    token,
    '加工项',
    '/api/admin/processing-items?size=100',
    (id) => `/api/admin/processing-items/${id}`,
    'name',
  )

  // 客户标签 — 名称含 "E2E"
  total += await cleanupResource(
    token,
    '客户标签',
    '/api/admin/customer-tags',
    (id) => `/api/admin/customer-tags/${id}`,
    'name',
  )

  // 加工分类 — 名称含 "E2E"
  total += await cleanupResource(
    token,
    '加工分类',
    '/api/admin/processing-categories',
    (id) => `/api/admin/processing-categories/${id}`,
    'name',
  )

  console.log(`\n✅ 清理完成，共删除 ${total} 条数据\n`)
}

main().catch((err) => {
  console.error('❌ 清理失败:', err.message)
  process.exit(1)
})
