// case_ids: UI-011, CH-009, DF-007
/**
 * 页面上下文（issue #5371 族 4）—— 前端只递交最小面：**路径** + **像 id 的段**。
 *
 * ## 为什么前端这一侧也要有判据
 *
 * 「读得到」不等于「可以注入」：前端是**唯一**能看到真实 URL 的地方，也是**PII 唯一的入口**。
 * 两条纪律都落在这 40 行里，且都能单独判红：
 * - **只取路径**：查询串/片段必须丢弃（`?phone=13800138000` 绝不进上下文与日志）；
 *   URL 编码（`%`）/空格/非 ASCII **拒绝**（夹带 PII 的形态连递交都不递交）。
 * - **只取 id**：只认**含数字**的段 ⇒ `new` / `edit` / `routings` / `production` 这类
 *   **路由词**永远不会被当成对象 id（「猜错页面比不猜更烦」，这是本族最贵的失效模式）。
 *
 * ## 语料是**两侧共用**的（跨语言同源守卫）
 *
 * `ENTITY_ID_CORPUS` / `ROUTE_CORPUS` 与后端 `backend/ai-agent-service/tests/test_page_context.py`
 * 的同名语料**逐条相同**：两侧（`page-context.ts` 与 `app/context/page_registry.py`）对同一组
 * 样本的判决必须一致 —— 任一侧漂移，它自己的判据就红（口径同 #5151 的语料一致性守卫）。
 */
import { describe, it, expect } from 'vitest'
import {
  entityIdFromRoute,
  normalizeRoute,
  pageContextPayload,
} from '@/lib/page-context'

const UUID = '8f3c1a2e-4b5d-4f6a-9c7e-1d2b3a4c5d6e'

/** 路径 → 期望的实体 id（`undefined` = 该页没有「像 id 的对象」）。**与后端同语料。** */
const ENTITY_ID_CORPUS: ReadonlyArray<readonly [string, string | undefined]> = [
  [`/orders/${UUID}`, UUID],
  ['/orders/12345', '12345'],
  ['/orders/new', undefined],
  [`/orders/${UUID}/edit`, UUID],
  ['/products/test-order-123/edit', 'test-order-123'],
  ['/production/routings', undefined],
  ['/production/pool', undefined],
  ['/production/processing', undefined],
  ['/products', undefined],
  ['/products/item1', 'item1'],
]

/**
 * 实体 id **形态语料**（token → 是否算 id）。**与后端 `backend/ai-agent-service/tests/test_page_context.py`
 * 的 `ENTITY_ID_CORPUS` 逐条相同** —— 两侧对同一组 token 的判决必须一致（跨语言同源守卫，
 * 后端那条判据还会从本文件里逐条认这些 token，缺一个就红）。
 */
const ENTITY_ID_TOKENS: ReadonlyArray<readonly [string, boolean]> = [
  [UUID, true],
  ['12345', true],
  ['test-order-123', true],
  ['item1', true],
  ['new', false],
  ['edit', false],
  ['create', false],
  ['ship', false],
  ['production', false],
  ['routings', false],
  ['pool', false],
  ['processing', false],
  ['orders', false],
  ['products', false],
  ['张三', false],
  ['郑 州', false],
  ['<script>', false],
  ['', false],
]

/** 路径 → 期望的规范化结果（`''` = 非法形态，**不递交**）。**与后端同语料。** */
const ROUTE_CORPUS: ReadonlyArray<readonly [string, string]> = [
  ['/orders/123', '/orders/123'],
  ['/orders/123?phone=13800138000', '/orders/123'],
  ['/orders/123?phone=13800138000#top', '/orders/123'],
  ['/products/abc/', '/products/abc'],
  ['/production/routings', '/production/routings'],
  ['/', '/'],
  ['orders/123', ''],
  ['', ''],
  ['/orders/%E5%BC%A0%E4%B8%89', ''],
  ['/orders/张 三', ''],
  ['/orders/../etc/passwd', ''],
  ['/orders//123', ''],
]

describe('route 规范化：只取路径（防 PII 进日志）', () => {
  it.each(ROUTE_CORPUS)('%s → %s', (pathname, expected) => {
    expect(normalizeRoute(pathname)).toBe(expected)
  })

  it('查询串**绝不**出现在递交载荷里', () => {
    const payload = pageContextPayload('/orders/123?phone=13800138000&note=张三')
    expect(payload).toEqual({ route: '/orders/123', entityId: '123' })
    expect(JSON.stringify(payload)).not.toContain('13800138000')
    expect(JSON.stringify(payload)).not.toContain('phone')
  })
})

describe('实体 id：只认「像 id 的段」', () => {
  it.each(ENTITY_ID_CORPUS)('%s → %s', (pathname, expected) => {
    expect(entityIdFromRoute(pathname)).toBe(expected)
  })

  it.each(ENTITY_ID_TOKENS)('形态语料 %s → %s', (token, expected) => {
    expect(entityIdFromRoute(`/x/${token}`)).toBe(expected ? token : undefined)
  })

  it('路由词不会被当成 id（new / edit / routings / production / pool）', () => {
    const routeWords = ['new', 'edit', 'create', 'ship', 'production', 'routings', 'pool', 'processing']
    expect(routeWords.filter(w => entityIdFromRoute(`/x/${w}`) !== undefined)).toEqual([])
  })

  it('没有 uid 形态的段 ⇒ entityId 键**缺席**（不是空串占位）', () => {
    const payload = pageContextPayload('/production/routings')
    expect(payload).toEqual({ route: '/production/routings' })
    expect(Object.keys(payload ?? {})).toEqual(['route'])
  })
})

describe('递交载荷：page_context（只含 route / entityId）', () => {
  it('载荷键集**只有** route / entityId —— 没有问题文本、没有角色、没有快照', () => {
    const payload = pageContextPayload('/products/12345')
    expect(Object.keys(payload ?? {}).sort()).toEqual(['entityId', 'route'])
    expect(JSON.stringify(payload)).not.toContain('role')
    expect(JSON.stringify(payload)).not.toContain('snapshot')
    expect(JSON.stringify(payload)).not.toContain('permission')
  })

  it('没有「像 id 的段」时 entityId 键**缺席**（不是空串占位）', () => {
    const payload = pageContextPayload('/production/routings')
    expect(payload).toEqual({ route: '/production/routings' })
    expect(Object.keys(payload ?? {})).toEqual(['route'])
  })

  it('非法路径 ⇒ `null`（**不递交**，由服务端的默认拒绝接手）', () => {
    expect(pageContextPayload('')).toEqual(null)
    expect(pageContextPayload('orders/123')).toEqual(null)
    expect(pageContextPayload('/orders/%E5%BC%A0%E4%B8%89')).toEqual(null)
  })

  it('载荷可被 JSON 序列化（它就是 fetch body 里那个字段的值）', () => {
    const encoded = JSON.stringify({ page_context: pageContextPayload('/orders/123') })
    expect(encoded).toBe('{"page_context":{"route":"/orders/123","entityId":"123"}}')
  })
})