// case_ids: BM-011
/**
 * 工人入库**契约字面量**判据（issue #5052 P3；`migao-dev-flow` §17.3 ⑤「契约里的技术字面量凭语义推测」）
 *
 * 端侧写错一个端点名 / 一个请求头名，类型检查与单测**都不会报**：跑到真机上才是 404 或"幂等静默失效"
 * （重复提交真的入两次库，而两次都返回 200 —— 这一点最贵）。故本守卫不靠印象，直接**解析后端 Java 源**
 * 逐值比对：
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | C1 | 端侧 6 个端点路径 ⊆ 后端控制器（类级 `@RequestMapping` + 方法映射拼出来） | 把 `drafts` 写成 `draft` ⇒ 红 |
 * | C2 | 后端有的端点，端侧**都覆盖**（反向） | 后端新增端点而端侧漏 ⇒ 红（提示补） |
 * | C3 | 每个端点的 **HTTP 方法**与后端注解一致（GET/POST 写反 ⇒ 405） | 把详情读面改成 post ⇒ 红 |
 * | C4 | 幂等头名逐字等于 `WorkerInboundController.IDEMPOTENCY_HEADER` | 沿用报工那条链的 `X-Client-Request-Id` ⇒ 红 |
 * | C5 | 短码字母表 / 长度逐值等于 `WorkerShortLinkService.ALPHABET` / `CODE_LENGTH` | 把字母表写成含 `I` 的 ⇒ 红 |
 */
import fs from 'fs'
import path from 'path'
import { INBOUND_ENDPOINTS, INBOUND_IDEMPOTENCY_HEADER } from '../src/services/workerInboundService'
import { SHORT_CODE_ALPHABET, SHORT_CODE_LENGTH } from '../src/utils/inbound/shortCode'
import { BMINI_ROOT } from './helpers/h5PlatformLists'

const REPO_ROOT = path.join(BMINI_ROOT, '..', '..')
const CONTROLLERS = [
  'backend/admin-api/src/main/java/com/migao/admin/controller/WorkerInboundController.java',
  'backend/admin-api/src/main/java/com/migao/admin/controller/WorkerInboundLabelController.java',
  'backend/admin-api/src/main/java/com/migao/admin/controller/WorkerInboundUploadController.java',
]
const SHORT_LINK_SERVICE =
  'backend/admin-api/src/main/java/com/migao/admin/service/WorkerShortLinkService.java'
const SERVICE_FILE = path.join(BMINI_ROOT, 'src/services/workerInboundService.ts')

function read(rel: string): string {
  const abs = path.join(REPO_ROOT, rel)
  if (!fs.existsSync(abs)) throw new Error(`找不到受管文件：${rel}（路径漂移不得静默跳过 ⇒ 红）`)
  return fs.readFileSync(abs, 'utf8')
}

/** 占位符归一化（`{id}` / `{shortCode}` ⇒ `{}`）：两侧写法不同但语义相同 */
function normalize(endpoint: string): string {
  return endpoint.replace(/\{[^}]+\}/g, '{}')
}

interface Endpoint {
  method: string
  path: string
}

/** 解析一个 Controller 的「HTTP 方法 + 路径」（类级前缀 + 方法级映射） */
function parseController(rel: string): Endpoint[] {
  const source = read(rel)
  const prefix = source.match(/@RequestMapping\("([^"]*)"\)/)?.[1] ?? ''
  const endpoints: Endpoint[] = []
  const re = /@(Get|Post|Put|Patch|Delete)Mapping\(\s*(?:value\s*=\s*)?"([^"]*)"/g
  for (const match of source.matchAll(re)) {
    endpoints.push({ method: match[1].toUpperCase(), path: normalize(prefix + match[2]) })
  }
  return endpoints
}

function javaEndpoints(): Endpoint[] {
  return CONTROLLERS.flatMap(parseController)
}

/** 端侧每个端点常量实际用的 HTTP 方法（从 service 源码里就近取：`await post<` / `await get<` / `Taro.uploadFile`） */
function methodUsedFor(key: string): string | null {
  const lines = fs.readFileSync(SERVICE_FILE, 'utf8').split('\n')
  for (let i = 0; i < lines.length; i += 1) {
    if (!lines[i].includes(`INBOUND_ENDPOINTS.${key}`)) continue
    for (let j = Math.max(0, i - 6); j < Math.min(lines.length, i + 7); j += 1) {
      if (/\bawait post</.test(lines[j])) return 'POST'
      if (/\bawait get</.test(lines[j])) return 'GET'
      if (/Taro\.uploadFile/.test(lines[j])) return 'POST'
    }
  }
  return null
}

describe('工人入库端点/头名与后端逐值一致', () => {
  const java = javaEndpoints()
  const tsEntries = Object.entries(INBOUND_ENDPOINTS) as [string, string][]

  it('前置：后端解析确实取到了这 6 个端点（判据不空转）', () => {
    const paths = java.map((e) => e.path)
    expect(paths).toContain('/api/worker/inbound/recognize')
    expect(paths).toContain('/api/worker/inbound/drafts')
    expect(paths).toContain('/api/worker/inbound/drafts/{}/post')
    expect(paths).toContain('/api/worker/inbound/upload')
    expect(paths).toContain('/api/worker/inbound/labels/{}')
    expect(paths).toContain('/api/worker/inbound/labels/{}/print')
    expect(tsEntries.length).toBe(6)
  })

  it('C1 端侧端点路径都在后端（写错一个字母 ⇒ 红）', () => {
    const known = new Set(java.map((e) => e.path))
    const unknown = tsEntries.filter(([, url]) => !known.has(normalize(url))).map(([key, url]) => `${key}=${url}`)
    expect(unknown).toEqual([])
  })

  it('C2 后端端点端侧都覆盖（漏一个 ⇒ 红）', () => {
    const declared = new Set(tsEntries.map(([, url]) => normalize(url)))
    const missing = java.filter((e) => !declared.has(e.path)).map((e) => `${e.method} ${e.path}`)
    expect(missing).toEqual([])
  })

  it('C3 HTTP 方法与后端注解一致（写反 ⇒ 405）', () => {
    const byPath = new Map(java.map((e) => [e.path, e.method]))
    const mismatched: string[] = []
    for (const [key, url] of tsEntries) {
      const used = methodUsedFor(key)
      const declared = byPath.get(normalize(url))
      if (used !== declared) mismatched.push(`${key}: 端侧=${used} 后端=${declared}`)
    }
    expect(mismatched).toEqual([])
  })

  it('C4 幂等头名逐字等于后端常量（写错 ⇒ 幂等静默失效）', () => {
    const javaHeader = read(CONTROLLERS[0]).match(/IDEMPOTENCY_HEADER\s*=\s*"([^"]+)"/)?.[1]
    expect(javaHeader).toBeTruthy()
    expect(INBOUND_IDEMPOTENCY_HEADER).toBe(javaHeader)
    // 建单与过账都带幂等键（少一处 ⇒ 那次重试会真的入两次库）
    const service = fs.readFileSync(SERVICE_FILE, 'utf8')
    expect(service.match(/INBOUND_IDEMPOTENCY_HEADER/g)?.length || 0).toBeGreaterThanOrEqual(3)
  })

  it('C5 短码字母表 / 长度逐值等于后端（客户端只做校验，不生成）', () => {
    const alphabet = read(SHORT_LINK_SERVICE).match(/ALPHABET\s*=\s*"([^"]+)"/)?.[1]
    const length = Number(read(SHORT_LINK_SERVICE).match(/CODE_LENGTH\s*=\s*(\d+)/)?.[1])
    expect(alphabet).toBeTruthy()
    expect(SHORT_CODE_ALPHABET).toBe(alphabet)
    expect(SHORT_CODE_LENGTH).toBe(length)
    // 人可读性口径：不含容易看错的 I / L / O / U（生成面不产出 ⇒ 校验面必须同样拒绝）
    for (const ch of ['I', 'L', 'O', 'U']) {
      expect(SHORT_CODE_ALPHABET.includes(ch)).toBe(false)
    }
  })

  it('C1 红证：把端点字面量改坏 ⇒ C1 的判定函数必须判红', () => {
    const known = new Set(java.map((e) => e.path))
    expect(known.has(normalize(INBOUND_ENDPOINTS.drafts))).toBe(true)
    expect(known.has(normalize('/api/worker/inbound/draft'))).toBe(false)
    expect(known.has(normalize('/api/worker/inbound/labels/{shortCode}/print'))).toBe(true)
  })
})
