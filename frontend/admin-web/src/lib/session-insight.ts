/**
 * session-insight — 会话洞察面板（米宝工作助手）数据层纯函数
 *
 * 米宝（B端智能工作助手）的工作范式：
 *   意图路由 → 查询工具 → validate_input → confirm 交互卡 → 写工具 → 追问建议
 *
 * 会话洞察面板基于这条工作链重建「工作台账」：
 *   1. 处理进度 — 工具调用时间线（做了什么 / 做到哪一步 / 哪里失败）
 *   2. 待确认   — 米宝在等待用户确认的交互卡（写操作安全闸）
 *   3. 业务对象 — 会话涉及的订单/商品/物流/售后/客户实体，点击可追问
 *
 * 历史接口只持久化 {tool, args} 形状的 tool_calls（无 status/result），
 * normalizeToolCall 统一归一化为前端形状，保证刷新页面后洞察数据依然可靠。
 */
import type { ChatMessage, ChatCard, InteractiveComponent } from '@/types'

// ═══════════════════════════════════════════════════
// 领域与工具元数据
// ═══════════════════════════════════════════════════

export type InsightDomain =
  | 'order' | 'product' | 'logistics' | 'aftersale' | 'customer'
  | 'inventory' | 'staff' | 'settings' | 'data' | 'workflow'

export const DOMAIN_LABELS: Record<InsightDomain, string> = {
  order: '订单',
  product: '商品',
  logistics: '物流',
  aftersale: '售后',
  customer: '客户',
  inventory: '库存',
  staff: '员工',
  settings: '设置',
  data: '数据',
  workflow: '流程',
}

export interface ToolMeta {
  /** 工具的中文行为描述，如「查询订单」「请求确认」 */
  label: string
  /** 所属业务领域 */
  domain: InsightDomain
  /** 是否为写操作（面板中标记「写」） */
  write: boolean
}

const TOOL_META: Record<string, ToolMeta> = {
  // 订单
  order_query: { label: '查询订单', domain: 'order', write: false },
  order_manage: { label: '订单管理', domain: 'order', write: true },
  order_create: { label: '创建订单', domain: 'order', write: true },
  // 物流
  logistics_track: { label: '查询物流', domain: 'logistics', write: false },
  // 售后
  aftersale_query: { label: '查询售后', domain: 'aftersale', write: false },
  aftersale_create: { label: '创建售后工单', domain: 'aftersale', write: true },
  after_sales_manage: { label: '售后管理', domain: 'aftersale', write: true },
  // 商品 / 库存
  product_search: { label: '搜索商品', domain: 'product', write: false },
  product_detail: { label: '查看商品详情', domain: 'product', write: false },
  product_manage: { label: '商品管理', domain: 'product', write: true },
  product_update: { label: '更新商品', domain: 'product', write: true },
  sku_update: { label: '更新SKU', domain: 'product', write: true },
  category_manage: { label: '分类管理', domain: 'product', write: true },
  processing_item_query: { label: '查询加工项', domain: 'product', write: false },
  query_processing_items: { label: '查询加工项', domain: 'product', write: false },
  processing_item_manage: { label: '加工项管理', domain: 'product', write: true },
  product_processing_item_manage: { label: '商品加工项管理', domain: 'product', write: true },
  inventory_manage: { label: '库存管理', domain: 'inventory', write: true },
  // 客户
  customer_manage: { label: '客户管理', domain: 'customer', write: true },
  // 员工 / 角色
  employee_manage: { label: '员工管理', domain: 'staff', write: true },
  role_manage: { label: '角色管理', domain: 'staff', write: true },
  // 数据
  dashboard_stats: { label: '查询数据看板', domain: 'data', write: false },
  // 设置
  settings_manage: { label: '系统设置', domain: 'settings', write: true },
  session_manage: { label: '会话管理', domain: 'settings', write: true },
  quick_reply_manage: { label: '快捷回复管理', domain: 'settings', write: true },
  notification_manage: { label: '通知管理', domain: 'settings', write: true },
  // 工作流（米宝安全闸：确认 / 校验 / 转人工）
  interact: { label: '请求确认', domain: 'workflow', write: false },
  validate_input: { label: '参数校验', domain: 'workflow', write: false },
  human_handoff: { label: '转人工', domain: 'workflow', write: false },
  // RAG 知识（当前禁用，保留映射）
  knowledge_search: { label: '检索知识库', domain: 'workflow', write: false },
  knowledge_upload: { label: '上传知识', domain: 'workflow', write: true },
  knowledge_delete: { label: '删除知识', domain: 'workflow', write: true },
}

export function getToolMeta(name: string): ToolMeta {
  return TOOL_META[name] || { label: name, domain: 'workflow', write: false }
}

// ═══════════════════════════════════════════════════
// tool_calls 归一化
// ═══════════════════════════════════════════════════

export interface NormalizedToolCall {
  name: string
  input?: Record<string, unknown>
  result?: unknown
  status: 'running' | 'completed' | 'error'
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/**
 * 将 tool_call 条目归一化为前端形状。
 * 兼容两种来源：
 *  - 实时 SSE：{name, input, status, result?}
 *  - 历史接口：{tool, args}（status 缺省视为 completed）
 * 结果明确失败（result.success === false）时状态升级为 error。
 */
export function normalizeToolCall(tc: unknown): NormalizedToolCall | null {
  if (!isRecord(tc)) return null

  const liveName = typeof tc.name === 'string' ? tc.name.trim() : ''
  const persistedName = typeof tc.tool === 'string' ? tc.tool.trim() : ''
  const name = liveName || persistedName
  if (!name) return null

  const input = isRecord(tc.input) ? tc.input : isRecord(tc.args) ? tc.args : undefined
  const result = 'result' in tc ? tc.result : undefined

  let status: NormalizedToolCall['status']
  if (tc.status === 'running' || tc.status === 'completed' || tc.status === 'error') {
    status = tc.status
  } else {
    status = 'completed'
  }
  if (status === 'completed' && isRecord(result) && result.success === false) {
    status = 'error'
  }

  return {
    name,
    ...(input !== undefined ? { input } : {}),
    ...(result !== undefined ? { result } : {}),
    status,
  }
}

export function normalizeToolCalls(tcs: unknown): NormalizedToolCall[] {
  if (!Array.isArray(tcs)) return []
  const out: NormalizedToolCall[] = []
  for (const tc of tcs) {
    const normalized = normalizeToolCall(tc)
    if (normalized) out.push(normalized)
  }
  return out
}

// ═══════════════════════════════════════════════════
// 工具事件时间线（处理进度）
// ═══════════════════════════════════════════════════

export interface ToolEvent {
  tool: NormalizedToolCall
  meta: ToolMeta
  messageId: string
}

/** 提取会话内全部工具调用事件，最新在前 */
export function extractToolEvents(messages: ChatMessage[]): ToolEvent[] {
  const events: ToolEvent[] = []
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    for (const tool of normalizeToolCalls(m.tool_calls)) {
      events.push({ tool, meta: getToolMeta(tool.name), messageId: m.id })
    }
  }
  return events
}

// ═══════════════════════════════════════════════════
// 待确认交互检测（米宝在等你确认）
// ═══════════════════════════════════════════════════

/**
 * 检测米宝是否在等待用户操作。
 * 从消息尾部回扫：遇到用户消息即说明此前的交互已被应答；
 * 遇到带 interactive 的助手消息且未被中断 → 待确认。
 */
export function detectPendingInteraction(messages: ChatMessage[]): InteractiveComponent | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m.role === 'user') return null
    if (m.role === 'assistant' && m.interactive && !m.wasAborted) return m.interactive
  }
  return null
}

// ═══════════════════════════════════════════════════
// 业务对象实体提取
// ═══════════════════════════════════════════════════

export type EntityType = 'order' | 'product' | 'logistics' | 'aftersale' | 'customer' | 'processing'

export interface SessionEntity {
  type: EntityType
  value: string
  label: string
  /** 点击标签后发送的追问消息 */
  followUp: string
}

export const ENTITY_TYPE_LABELS: Record<EntityType, string> = {
  order: '订单',
  product: '商品',
  logistics: '物流',
  aftersale: '售后',
  customer: '客户',
  processing: '加工项',
}

function makeEntity(type: EntityType, value: unknown): SessionEntity | null {
  const v = typeof value === 'string' ? value.trim() : String(value ?? '').trim()
  if (!v) return null
  switch (type) {
    case 'order':
      return { type, value: v, label: `订单 ${v}`, followUp: `查看订单 ${v}` }
    case 'product':
      return { type, value: v, label: `商品 ${v}`, followUp: `查看 ${v} 详情` }
    case 'logistics':
      return { type, value: v, label: `物流 ${v}`, followUp: `查询物流 ${v}` }
    case 'aftersale':
      return { type, value: v, label: `售后 ${v}`, followUp: `查看售后工单 ${v}` }
    case 'customer':
      return { type, value: v, label: `客户 ${v}`, followUp: `查看客户 ${v}` }
    case 'processing':
      return { type, value: v, label: `加工项 ${v}`, followUp: `查看加工项 ${v}` }
  }
}

/** 从记录中取第一个非空字符串字段 */
function firstString(record: Record<string, unknown>, keys: string[]): unknown {
  for (const k of keys) {
    const v = record[k]
    if (typeof v === 'string' && v.trim()) return v
  }
  return ''
}

/** 从工具调用入参（实时 input / 历史 args）提取实体 */
function extractFromToolCall(tc: NormalizedToolCall): SessionEntity[] {
  const input = tc.input || {}
  const meta = getToolMeta(tc.name)
  const out: SessionEntity[] = []
  const push = (e: SessionEntity | null) => { if (e) out.push(e) }

  push(makeEntity('order', firstString(input, ['order_id', 'order_no', 'orderId'])))
  push(makeEntity('logistics', firstString(input, ['tracking_no', 'trackingNo'])))
  push(makeEntity('aftersale', firstString(input, ['ticket_no', 'ticketNo', 'aftersale_id', 'aftersaleId', 'ticket_id'])))
  push(makeEntity('customer', firstString(input, ['customer_name', 'customerName', 'customer_id', 'customerId'])))
  push(makeEntity('processing', firstString(input, ['processing_item_name', 'processingItemName', 'item_name'])))

  const productName = firstString(input, ['product_name', 'productName'])
  if (productName) push(makeEntity('product', productName))
  else if (meta.domain === 'product') push(makeEntity('product', firstString(input, ['name'])))

  return out
}

/** 从已完成的工具结果（仅实时流）提取实体 */
function extractFromResult(result: unknown): SessionEntity[] {
  if (!isRecord(result)) return []
  const data = isRecord(result.data) ? result.data : null
  const out: SessionEntity[] = []
  const push = (e: SessionEntity | null) => { if (e) out.push(e) }

  // 订单：单笔（result / result.data / result.order / result.data.order）
  push(makeEntity('order', firstString(result, ['orderNo', 'order_no'])))
  const order = isRecord(result.order) ? result.order : null
  if (order) push(makeEntity('order', firstString(order, ['orderNo', 'order_no'])))
  if (data) {
    push(makeEntity('order', firstString(data, ['orderNo', 'order_no'])))
    const dataOrder = isRecord(data.order) ? data.order : null
    if (dataOrder) push(makeEntity('order', firstString(dataOrder, ['orderNo', 'order_no'])))
  }

  // 订单：列表
  const orders = Array.isArray(result.orders)
    ? result.orders
    : data && Array.isArray(data.orders) ? data.orders : null
  if (orders) {
    for (const o of orders) {
      if (isRecord(o)) push(makeEntity('order', firstString(o, ['orderNo', 'order_no'])))
    }
  }

  // 物流 / 售后 / 客户 / 商品
  push(makeEntity('logistics', firstString(result, ['tracking_no', 'trackingNo'])))
  const product = isRecord(result.product) ? result.product : null
  if (product) push(makeEntity('product', firstString(product, ['name'])))
  push(makeEntity('aftersale', firstString(result, ['ticket_no', 'ticketNo'])))
  push(makeEntity('customer', firstString(result, ['customer_name', 'customerName'])))
  if (data) {
    push(makeEntity('logistics', firstString(data, ['tracking_no', 'trackingNo'])))
    const dataProduct = isRecord(data.product) ? data.product : null
    if (dataProduct) push(makeEntity('product', firstString(dataProduct, ['name'])))
    push(makeEntity('aftersale', firstString(data, ['ticket_no', 'ticketNo'])))
    push(makeEntity('customer', firstString(data, ['customer_name', 'customerName'])))
  }

  return out
}

/** 从实时卡片提取实体 */
function extractFromCard(card: ChatCard): SessionEntity[] {
  const data = card.data || {}
  const out: SessionEntity[] = []
  const push = (e: SessionEntity | null) => { if (e) out.push(e) }

  switch (card.type) {
    case 'order': {
      const orders = Array.isArray(data.orders)
        ? data.orders
        : Array.isArray(data.items) ? data.items : null
      if (orders) {
        for (const o of orders) {
          if (isRecord(o)) push(makeEntity('order', firstString(o, ['orderNo', 'order_no'])))
        }
      } else {
        const order = isRecord(data.order) ? data.order : data
        push(makeEntity('order', firstString(order, ['orderNo', 'order_no'])))
      }
      break
    }
    case 'product_list': {
      const products = Array.isArray(data.products) ? data.products : []
      for (const p of products) {
        if (isRecord(p)) push(makeEntity('product', firstString(p, ['name'])))
      }
      break
    }
    case 'product_detail': {
      const product = isRecord(data.product) ? data.product : data
      push(makeEntity('product', firstString(product, ['name'])))
      break
    }
    case 'logistics':
      push(makeEntity('logistics', firstString(data, ['tracking_no', 'trackingNo'])))
      break
    default:
      break
  }

  return out
}

/**
 * 提取会话内全部业务对象实体（最新在前，跨来源去重）。
 * 来源优先级：工具入参（历史可用）→ 工具结果（实时）→ 卡片（实时）。
 */
export function extractEntities(messages: ChatMessage[]): SessionEntity[] {
  const seen = new Set<string>()
  const out: SessionEntity[] = []
  const add = (e: SessionEntity | null) => {
    if (!e) return
    const key = `${e.type}:${e.value}`
    if (seen.has(key)) return
    seen.add(key)
    out.push(e)
  }

  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    for (const tc of normalizeToolCalls(m.tool_calls)) {
      for (const e of extractFromToolCall(tc)) add(e)
      for (const e of extractFromResult(tc.result)) add(e)
    }
    for (const card of m.cards || []) {
      for (const e of extractFromCard(card)) add(e)
    }
  }
  return out
}

// ═══════════════════════════════════════════════════
// 实体分组
// ═══════════════════════════════════════════════════

export interface EntityGroup {
  type: EntityType
  label: string
  entities: SessionEntity[]
}

/** 按业务域分组，保持首次出现的顺序 */
export function groupEntities(entities: SessionEntity[]): EntityGroup[] {
  const groups: EntityGroup[] = []
  const indexByType = new Map<EntityType, number>()
  for (const e of entities) {
    let idx = indexByType.get(e.type)
    if (idx === undefined) {
      idx = groups.length
      indexByType.set(e.type, idx)
      groups.push({ type: e.type, label: ENTITY_TYPE_LABELS[e.type], entities: [] })
    }
    groups[idx].entities.push(e)
  }
  return groups
}
