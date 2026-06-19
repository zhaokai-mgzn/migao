/**
 * E2E 测试数据清理脚本
 *
 * 每次 E2E 测试运行前/后执行，清除上一次测试产生的脏数据。
 * 识别规则：
 *   - 名称包含 "E2E"（大小写不敏感）
 *   - 名称包含 "测试" / "smoke" / "test-"
 *   - 名称以 "E2E" 开头（含子分类如 "E2E测试分类_xxx"）
 *   - 特定测试名称模式（默认值测试、名称修复测试、SKU笛卡尔等）
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

// 匹配所有 E2E / 测试 / smoke 相关数据
const TEST_NAME_PATTERNS = [/E2E/i, /测试/, /smoke/i, /test-/i, /^默认值测试$/, /^名称修复测试$/, /^SKU笛卡尔/, /^试试看$/]

function isTestData(name: string): boolean {
  if (!name) return false
  return TEST_NAME_PATTERNS.some((p) => p.test(name))
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
    if (isTestData(name)) return true
    if (extraFilter) return extraFilter(item)
    return false
  })

  let deleted = 0
  for (const item of toDelete) {
    try {
      const res = await apiDelete(deletePath(item.id as string), token)
      if (res.success) deleted++
    } catch {
      // 网络错误跳过
    }
  }

  if (toDelete.length > 0) {
    console.log(`  ${resource}: 删除 ${deleted}/${toDelete.length}`)
  } else {
    console.log(`  ${resource}: 无脏数据`)
  }

  return deleted
}

/**
 * 递归清理分类（处理子分类，按层级从深到浅删除避免外键约束）
 */
async function cleanupCategories(token: string): Promise<number> {
  const json = await apiGet('/api/admin/categories', token)
  const all: Record<string, unknown>[] = json?.data ?? []

  // 按 parentId 分层：子分类先删
  const topLevel = all.filter((c) => !c.parentId)
  const children = all.filter((c) => c.parentId)

  let deleted = 0

  // 先删子分类中的测试数据
  for (const cat of children) {
    const name = String(cat.name ?? '')
    if (isTestData(name)) {
      try {
        const res = await apiDelete(`/api/admin/categories/${cat.id}`, token)
        if (res.success) deleted++
      } catch { /* skip */ }
    }
  }

  // 再删顶层测试分类
  for (const cat of topLevel) {
    const name = String(cat.name ?? '')
    if (isTestData(name)) {
      try {
        const res = await apiDelete(`/api/admin/categories/${cat.id}`, token)
        if (res.success) deleted++
      } catch { /* skip */ }
    }
  }

  const testChildren = children.filter((c) => isTestData(String(c.name ?? '')))
  const testTop = topLevel.filter((c) => isTestData(String(c.name ?? '')))
  const totalTest = testChildren.length + testTop.length

  if (totalTest > 0) {
    console.log(`  分类: 删除 ${deleted}/${totalTest}（子分类 ${testChildren.length} + 顶层 ${testTop.length}）`)
  } else {
    console.log('  分类: 无脏数据')
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

  // 商品 — 名称含 E2E/测试/smoke 等
  total += await cleanupResource(
    token,
    '商品',
    '/api/admin/products?size=200',
    (id) => `/api/admin/products/${id}`,
    'name',
  )

  // 分类 — 递归清理（子分类先删，避免外键约束）
  total += await cleanupCategories(token)

  // 客户 — 名称含 E2E
  total += await cleanupResource(
    token,
    '客户',
    '/api/admin/customers?size=200',
    (id) => `/api/admin/customers/${id}`,
    'name',
  )

  // 加工项 — 名称含 E2E
  total += await cleanupResource(
    token,
    '加工项',
    '/api/admin/processing-items?size=100',
    (id) => `/api/admin/processing-items/${id}`,
    'name',
  )

  // 客户标签 — 名称含 E2E
  total += await cleanupResource(
    token,
    '客户标签',
    '/api/admin/customer-tags',
    (id) => `/api/admin/customer-tags/${id}`,
    'name',
  )

  // 加工分类 — 名称含 E2E
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
