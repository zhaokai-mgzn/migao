/**
 * Test Data — Static constants for E2E tests.
 *
 * All data shapes match the types defined in src/types/index.ts
 * and the API contracts in src/lib/api.ts.
 */

// ────────────────────────────────────────────
// Auth / Login
// ────────────────────────────────────────────

export const VALID_PHONE = '13800138000'
export const INVALID_PHONES = {
  tooShort: '1380013800',
  tooLong: '138001380001',
  wrongPrefix: '12345678901',
  empty: '',
  letters: '1380013abcd',
}

export const VALID_SMS_CODE = '123456'
export const INVALID_SMS_CODES = {
  tooShort: '12345',
  tooLong: '1234567',
  empty: '',
  letters: 'abcdef',
}

export const TEST_CREDENTIALS = {
  admin: { username: 'admin', password: 'admin123', tenantId: 1 },
  employee: { username: 'employee1', password: 'emp123456', tenantId: 1 },
  invalid: { username: 'nobody', password: 'wrong', tenantId: 1 },
}

// ────────────────────────────────────────────
// Products
// ────────────────────────────────────────────

/** Minimal valid product data for creation */
export const TEST_PRODUCT = {
  name: '测试窗帘布料-遮光款',
  skuCode: 'TEST-CL-001',
  brand: '优客测试',
  categoryId: 'cat_test_001',
  description: 'E2E测试用窗帘布料，高密度遮光面料，宽幅2.8米',
  pricingType: 'per_meter' as const,
  price: 128.00,
  costPrice: 68.00,
  unit: '米',
  status: 'on_sale' as const,
  images: ['https://mgzn-admin.oss-cn-hangzhou.aliyuncs.com/test/curtain-001.jpg'],
  specifications: {
    '材质': '涤纶',
    '门幅': '2.8米',
    '遮光率': '95%',
  },
  colors: [
    {
      colorName: '米白色',
      mainColorHex: '#F5F5DC',
      sortOrder: 1,
    },
    {
      colorName: '深灰色',
      mainColorHex: '#4A4A4A',
      sortOrder: 2,
    },
  ],
  sellingMethods: ['bulk_cut' as const],
  doorWidths: ['2.8米'],
  skus: [
    {
      colorId: 1,
      colorName: '米白色',
      sellingMethod: 'bulk_cut' as const,
      doorWidth: '2.8米',
      price: 128.00,
      costPrice: 68.00,
      stock: 100,
      skuCode: 'TEST-CL-001-WHT',
      status: 'active' as const,
    },
  ],
}

/** Product update data */
export const TEST_PRODUCT_UPDATE = {
  name: '测试窗帘布料-遮光款（升级版）',
  price: 138.00,
  description: 'E2E测试用窗帘布料，升级高密度遮光面料',
  categoryId: 'cat_test_001',
  status: 'on_sale' as const,
  images: ['https://mgzn-admin.oss-cn-hangzhou.aliyuncs.com/test/curtain-001.jpg'],
  unit: '米',
}

// ────────────────────────────────────────────
// Orders
// ────────────────────────────────────────────

/** Minimal valid order data for creation */
export const TEST_ORDER = {
  customerName: '测试客户-张三',
  customerPhone: '13800138000',
  customerAddress: '浙江省杭州市西湖区文三路100号',
  remark: 'E2E测试订单',
  items: [
    {
      productName: '测试窗帘布料-遮光款',
      quantity: 5,
      unitPrice: 128.00,
      width: 2.8,
      subtotal: 640.00,
    },
  ],
}

/** Order status update scenarios */
export const ORDER_STATUS_FLOW = [
  { from: 'pending_payment', to: 'pending_shipment', action: '确认付款' },
  { from: 'pending_shipment', to: 'shipped', action: '确认发货' },
  { from: 'shipped', to: 'completed', action: '确认收货' },
] as const

/** Close order test data */
export const TEST_CLOSE_ORDER = {
  reason: '测试关闭-客户取消',
}

/** Logistics data for shipping */
export const TEST_LOGISTICS = {
  company: '顺丰速运',
  trackingNo: 'SF1234567890',
  shippingMethod: 'logistics' as const,
}

// ────────────────────────────────────────────
// Categories
// ────────────────────────────────────────────

export const TEST_CATEGORY = {
  name: '测试分类-窗帘',
  sort: 1,
}

export const TEST_SUBCATEGORY = {
  name: '测试子分类-遮光帘',
  sort: 1,
  // parentId will be set dynamically after parent is created
}

// ────────────────────────────────────────────
// Processing Items
// ────────────────────────────────────────────

export const TEST_PROCESSING_ITEM = {
  name: '测试加工-韩式打褶定型',
  categoryId: 'proc_cat_test_001',
  pricingMethod: 'per_meter' as const,
  unitPrice: 35.00,
  unit: '米',
  status: 'active' as const,
  description: 'E2E测试用加工项，韩式高温定型打褶',
  processingDays: 3,
}

export const TEST_PROCESSING_ITEM_UPDATE = {
  name: '测试加工-韩式打褶定型（升级版）',
  unitPrice: 40.00,
  categoryId: 'proc_cat_test_001',
  pricingMethod: 'per_meter' as const,
  status: 'active' as const,
}

// ────────────────────────────────────────────
// Customers
// ────────────────────────────────────────────

export const TEST_CUSTOMER_SEARCH = {
  keyword: '测试客户',
  channel: 'wechat_mini' as const,
}

// ────────────────────────────────────────────
// Employees / Users
// ────────────────────────────────────────────

export const TEST_EMPLOYEE = {
  username: 'test_employee_e2e',
  password: 'Test123456',
  name: 'E2E测试员工',
  phone: '13900139000',
  email: 'e2e-test@migaozn.com',
  roleIds: [2], // Assuming role ID 2 = "客服"
}

export const TEST_EMPLOYEE_UPDATE = {
  name: 'E2E测试员工（已更新）',
  phone: '13900139001',
  email: 'e2e-updated@migaozn.com',
  roleIds: [2],
}

export const TEST_RESET_PASSWORD = {
  newPassword: 'NewPass123456',
}

// ────────────────────────────────────────────
// Roles
// ────────────────────────────────────────────

export const TEST_ROLE = {
  name: 'E2E测试角色',
  code: 'e2e_test_role',
  description: 'E2E测试专用角色，测试完成后删除',
  permissionIds: [1, 2, 3, 4], // Assumed permission IDs for read operations
}

export const TEST_ROLE_UPDATE = {
  name: 'E2E测试角色（已更新）',
  code: 'e2e_test_role_updated',
  description: 'E2E测试专用角色，权限已更新',
  permissionIds: [1, 2, 3, 4, 5, 6],
}

// ────────────────────────────────────────────
// After-Sales
// ────────────────────────────────────────────

export const TEST_AFTER_SALES = {
  ticketType: 'return' as const,
  description: 'E2E测试售后工单-退货退款',
  priority: 'normal' as const,
  // orderId will be set dynamically
}

export const TEST_AFTER_SALES_STATUS_FLOW = [
  { from: 'pending', to: 'processing', remark: '已开始处理' },
  { from: 'processing', to: 'resolved', remark: '退款完成' },
] as const

// ────────────────────────────────────────────
// Chat / AI
// ────────────────────────────────────────────

export const TEST_CHAT_MESSAGE = '你好，请帮我推荐一款遮光窗帘'

export const TEST_CHAT_QUERIES = {
  product: '帮我看看有什么窗帘布料',
  logistics: '查一下订单 SF1234567890 的物流',
  order: '我想查一下最近的订单',
}

// ────────────────────────────────────────────
// Notifications
// ────────────────────────────────────────────

export const TEST_NOTIFICATION = {
  recipientId: '1',
  recipientType: 'user' as const,
  title: 'E2E测试通知',
  content: '这是一条E2E测试通知消息',
  channel: 'internal' as const,
}

// ────────────────────────────────────────────
// Settings
// ────────────────────────────────────────────

export const TEST_SETTINGS_UPDATE = {
  companyName: 'E2E测试企业',
  notificationEnabled: true,
}

export const TEST_AI_CONFIG_UPDATE = {
  botName: '有客AI助手（测试）',
  greetingTemplate: '您好！我是{botName}，有什么可以帮您？',
}

export const TEST_CHANGE_PASSWORD = {
  oldPassword: 'admin123',
  newPassword: 'NewAdmin456',
  confirmPassword: 'NewAdmin456',
}

// ────────────────────────────────────────────
// Dashboard
// ────────────────────────────────────────────

export const DASHBOARD_EXPECTED_SECTIONS = [
  '今日订单',
  '客户总数',
  '活跃会话',
  '本月营收',
] as const

// ────────────────────────────────────────────
// Pagination defaults
// ────────────────────────────────────────────

export const PAGINATION = {
  defaultPageSize: 10,
  pageSizeOptions: [10, 20, 50, 100],
} as const
