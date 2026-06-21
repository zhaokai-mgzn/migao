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

// 匹配测试数据 — 含 test / 测试 / E2E / smoke / 新分类 / 新加工项 等明显测试标记
const TEST_NAME_PATTERNS = [
  /E2E/i,
  /test/i,
  /测试/,
  /smoke/i,
  /冒烟/,
  /^默认值测试$/,
  /^名称修复测试$/,
  /^SKU笛卡尔/,
  /^新分类/,
  /^新商品/,
  /^新加工项/,
  /^新客户/,
  /^新标签/,
  /^新订单/,
]

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
 * 递归扁平化分类树（兼容嵌套 children 和扁平 parentId 两种格式）
 */
function flattenCategoryTree(nodes: unknown, depth = 0): Array<{ id: string; name: string; depth: number }> {
  if (!Array.isArray(nodes)) return []
  const result: Array<{ id: string; name: string; depth: number }> = []
  for (const node of nodes) {
    if (!node || typeof node !== 'object') continue
    const n = node as Record<string, unknown>
    result.push({ id: String(n.id ?? ''), name: String(n.name ?? ''), depth })
    // 递归处理嵌套 children
    if (Array.isArray(n.children)) {
      result.push(...flattenCategoryTree(n.children, depth + 1))
    }
  }
  return result
}

/**
 * 清理分类 — 兼容树形/扁平返回，按深度从深到浅删除避免外键约束
 */
async function cleanupCategories(token: string): Promise<number> {
  const json = await apiGet('/api/admin/categories', token)
  const raw = json?.data ?? []

  // 扁平化（兼容嵌套树和扁平 parentId 两种格式）
  let all = flattenCategoryTree(raw)

  // 如果扁平化后为空，尝试兼容 records/items 包装
  if (all.length === 0 && typeof raw === 'object' && !Array.isArray(raw)) {
    const r = raw as Record<string, unknown>
    const inner = r.records ?? r.items ?? r.list ?? []
    all = flattenCategoryTree(inner)
  }

  // 只保留测试数据
  const testNodes = all.filter((c) => isTestData(c.name))

  if (testNodes.length === 0) {
    console.log('  分类: 无脏数据')
    return 0
  }

  // 按深度降序排列：深层先删，避免外键约束
  testNodes.sort((a, b) => b.depth - a.depth)

  let deleted = 0
  const depthGroups = new Map<number, number>()
  for (const cat of testNodes) {
    try {
      const res = await apiDelete(`/api/admin/categories/${cat.id}`, token)
      if (res.success) {
        deleted++
        depthGroups.set(cat.depth, (depthGroups.get(cat.depth) ?? 0) + 1)
      }
    } catch { /* 关联数据导致删除失败，跳过 */ }
  }

  const depthSummary = [...depthGroups.entries()]
    .sort(([a], [b]) => b - a)
    .map(([d, c]) => `L${d}:${c}`)
    .join(' ')
  console.log(`  分类: 删除 ${deleted}/${testNodes.length}（${depthSummary}）`)

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
