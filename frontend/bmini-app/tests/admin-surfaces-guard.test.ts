// case_ids: BM-009
/**
 * 管理面手机端的**类级元守卫**（issue #5654；AGENTS.md 铁律 8「类级固化」/ `migao-dev-flow` §23）
 *
 * 一条缺陷只修一处 = 没修。本单的 4 个管理面会**继续增加**（管理面共 11 项），
 * 所以「4 项各自能用」之外必须钉住**同类进不来的那一层**：
 *
 * 判据 1·**登记即可达**：`ADMIN_SURFACES[].route` 必须逐字出现在 `src/app.config.ts` 的 pages 里
 *   （页面没登记 ⇒ 点进去是空白 —— 手机端最常见的一种「静默失败」）；`pageFile` 必须存在。
 * 判据 2·**平台能力面：声明 == 实测**（双向）：射程内用到的 Taro API 集必须**逐值等于**
 *   `ADMIN_SURFACE_TARO_APIS`。新增一处 Taro 调用而不同步声明 ⇒ 红（这才是 #5654 判据 3/4 的
 *   机械面：**h5 下不调 `Taro.login`** 这类要求不能靠人记得）。
 * 判据 3·**缺口必须显式**：声明的 API 若命中 #5650 的清单（h5 未实现 / 只走微信 JS-SDK），
 *   必须在 `ADMIN_SURFACE_PLATFORM_GAP_HINTS` 登记「用户看到什么」，且该文案被射程内文件**引用**
 *   （登记而不接线 = 台账自我复制的历史文档）。
 * 判据 4·**台账只许缩短且条目必须活着**：hints 的键 ⊆ 清单 ∩ 声明。
 * 判据 5·**权限码真值在后端注解**：台账 `readPermission`/`writePermission` 与
 *   `@RequirePermission` + `@XxxMapping` 逐值相等（改一处不改另一处 ⇒ 红）。
 * 判据 6·**售后状态机镜像**：`afterSalesFlow.ts` 与 `AfterSalesTicketService.java` 的两个
 *   Java 字面量逐值相等。
 * 判据 7·**机制存活读数**：清单 A 条数、射程实测 API 数、每个面的读端点在后端解析得出来
 *   —— 防「面变窄了但没人知道」。
 */
import fs from 'fs'
import path from 'path'
import {
  ADMIN_SURFACES,
  ADMIN_SURFACE_PLATFORM_GAP_HINTS,
  ADMIN_SURFACE_SCOPE_FILES,
  ADMIN_SURFACE_TARO_APIS,
  type AdminEndpoint,
} from '../src/utils/adminPermission'
import {
  AFTER_SALES_STATUS_LABELS,
  AFTER_SALES_STATUS_TRANSITIONS,
} from '../src/utils/afterSalesFlow'
import {
  BMINI_ROOT,
  jsSdkOnlyApis,
  taroApisInFile,
  unsupportedApis,
} from './helpers/h5PlatformLists'

/** `<repo>`（本文件在 `frontend/bmini-app/tests/`） */
const REPO_ROOT = path.join(BMINI_ROOT, '..', '..')

const AFTER_SALES_SERVICE =
  'backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java'

interface Mapping {
  index: number
  method: string
  path: string
}

interface ParsedController {
  mappings: Mapping[]
  /** 每个 mapping 的生效权限码（就近 ±3 行的方法级注解优先，否则类级） */
  codeOf(method: string, endpointPath: string): string | null
}

/**
 * 解析一个 Controller 的「端点 → 权限码」（唯一真值 = 后端注解）。
 *
 * 顺序**不假设**：两种写法在仓库里都存在 —— `ProductionPoolController` 是
 * `@RequirePermission` 在 `@GetMapping` **之前**，`ProductionController#pieceworkSummary`
 * 是**之后**。故按「就近 ±3 行」关联，取不到的映射回落类级注解。
 */
function parseController(relPath: string): ParsedController {
  const abs = path.join(REPO_ROOT, relPath)
  if (!fs.existsSync(abs)) throw new Error(`找不到 Controller：${relPath}（判红，不静默跳过）`)
  const lines = fs.readFileSync(abs, 'utf8').split('\n')
  const prefix = lines.join('\n').match(/@RequestMapping\("([^"]*)"\)/)?.[1] ?? ''

  const mappings: Mapping[] = []
  const perms: { index: number; code: string }[] = []
  lines.forEach((line, index) => {
    const mapping = line.match(/@(Get|Post|Put|Patch)Mapping(?:\("([^"]*)"\))?/)
    if (mapping) {
      mappings.push({ index, method: mapping[1].toUpperCase(), path: prefix + (mapping[2] ?? '') })
    }
    const perm = line.match(/@RequirePermission\("([^"]+)"\)/)
    if (perm) perms.push({ index, code: perm[1] })
  })

  const isMethodLevel = (permIndex: number) =>
    mappings.some((mapping) => Math.abs(mapping.index - permIndex) <= 3)
  const classLevel = perms.find((perm) => !isMethodLevel(perm.index))?.code ?? null

  return {
    mappings,
    codeOf(method: string, endpointPath: string) {
      const mapping = mappings.find((m) => m.method === method && m.path === endpointPath)
      if (!mapping) return null
      const nearest = perms
        .filter((perm) => Math.abs(perm.index - mapping.index) <= 3)
        .sort((a, b) => Math.abs(a.index - mapping.index) - Math.abs(b.index - mapping.index))[0]
      return nearest?.code ?? classLevel
    },
  }
}

function describeEndpoint(endpoint: AdminEndpoint): string {
  return `${endpoint.method} ${endpoint.path}`
}

function findEndpoint(controller: ParsedController, endpoint: AdminEndpoint): string | null {
  return controller.codeOf(endpoint.method, endpoint.path)
}

/** Java `Map<String, Set<String>> NAME = Map.of(...)` → 逐值对象 */
function javaSetMap(java: string, name: string): Record<string, string[]> {
  const start = java.indexOf(`${name} = Map.of(`)
  if (start < 0) throw new Error(`Java 里找不到 ${name} = Map.of( ⇒ 抽取口径漂移，判红`)
  const body = java.slice(start, java.indexOf(');', start))
  const out: Record<string, string[]> = {}
  for (const match of body.matchAll(/"([a-z_]+)",\s*Set\.of\(([^)]*)\)/g)) {
    out[match[1]] = Array.from(match[2].matchAll(/"([^"]+)"/g)).map((m) => m[1])
  }
  if (Object.keys(out).length < 5) {
    throw new Error(`${name} 只解析出 ${Object.keys(out).length} 个状态（预期 5）⇒ 判红`)
  }
  return out
}

/** Java `Map<String, String> NAME = Map.of("k", "v", ...)` → 逐值对象 */
function javaStringMap(java: string, name: string): Record<string, string> {
  const start = java.indexOf(`${name} = Map.of(`)
  if (start < 0) throw new Error(`Java 里找不到 ${name} = Map.of( ⇒ 抽取口径漂移，判红`)
  const body = java.slice(start, java.indexOf(');', start))
  const out: Record<string, string> = {}
  for (const match of body.matchAll(/"([a-z_]+)",\s*"([^"]+)"/g)) out[match[1]] = match[2]
  if (Object.keys(out).length < 5) {
    throw new Error(`${name} 只解析出 ${Object.keys(out).length} 条（预期 5）⇒ 判红`)
  }
  return out
}

describe('管理面手机端类级守卫（issue #5654）', () => {
  const unsupported = unsupportedApis()
  const jsSdkOnly = jsSdkOnlyApis()
  const hazardous = new Set([...unsupported, ...jsSdkOnly])

  it('判据 7·机制存活读数：两张清单现取成功，射程实测到 Taro 用法（判据不许空转）', () => {
    expect(unsupported.size).toBeGreaterThan(100)
    expect(jsSdkOnly.has('scanCode')).toBe(true)
    const measured = new Set(
      ADMIN_SURFACE_SCOPE_FILES.flatMap((rel) => taroApisInFile(path.join(BMINI_ROOT, rel))),
    )
    expect(measured.size).toBeGreaterThan(0)
    expect(ADMIN_SURFACE_TARO_APIS.length).toBeGreaterThan(0)
    expect(ADMIN_SURFACES.length).toBe(4)
  })

  it('判据 1·每个管理面的路由都登记在 app.config.ts，且页面文件存在', () => {
    const appConfig = fs.readFileSync(path.join(BMINI_ROOT, 'src', 'app.config.ts'), 'utf8')
    const missing: string[] = []
    for (const surface of ADMIN_SURFACES) {
      const routeLiteral = `'${surface.route.replace(/^\//, '')}'`
      if (!appConfig.includes(routeLiteral)) missing.push(`${surface.key}: app.config 未登记 ${routeLiteral}`)
      if (!fs.existsSync(path.join(BMINI_ROOT, surface.pageFile))) {
        missing.push(`${surface.key}: 页面文件不存在 ${surface.pageFile}`)
      }
      // route ↔ pageFile 必须指同一个文件（否则「登记的入口」和「被测的页面」是两处，判据会滑走）
      if (`src${surface.route}.tsx` !== surface.pageFile) {
        missing.push(`${surface.key}: route(${surface.route}) 与 pageFile(${surface.pageFile}) 不指向同一文件`)
      }
    }
    expect(missing).toEqual([])
  })

  it('判据 1·每个管理面的端点都能在后端 Controller 里解析出来（拒绝「凭印象写端点」）', () => {
    const unresolved: string[] = []
    for (const surface of ADMIN_SURFACES) {
      const controller = parseController(surface.controllerFile)
      if (findEndpoint(controller, surface.readEndpoint) === null) {
        unresolved.push(`${surface.key}: 读端点解析不到 ${describeEndpoint(surface.readEndpoint)}`)
      }
      if (surface.writeEndpoint && findEndpoint(controller, surface.writeEndpoint) === null) {
        unresolved.push(`${surface.key}: 写端点解析不到 ${describeEndpoint(surface.writeEndpoint)}`)
      }
    }
    expect(unresolved).toEqual([])
  })

  it('判据 2·平台能力面：射程内实测的 Taro API 集 == 声明集（双向，多一个少一个都红）', () => {
    const measured = Array.from(
      new Set(
        ADMIN_SURFACE_SCOPE_FILES.flatMap((rel) => taroApisInFile(path.join(BMINI_ROOT, rel))),
      ),
    ).sort()
    expect(measured).toEqual([...ADMIN_SURFACE_TARO_APIS].sort())
  })

  it('判据 3·命中 h5 清单的 API 必须登记缺口文案，且**用到它的文件**必须接线该台账', () => {
    const hazardousDeclared = ADMIN_SURFACE_TARO_APIS.filter((api) => hazardous.has(api))
    const unregistered = hazardousDeclared.filter(
      (api) => !(api in ADMIN_SURFACE_PLATFORM_GAP_HINTS),
    )
    expect(unregistered).toEqual([])

    // 「登记了」不够：**真的调用该 API 的文件**必须引用台账（否则用户看不到那段文案，
    // 台账就成了自我复制的历史文档）。判据刻意只取「有调用的文件」——
    // `src/utils/adminPermission.ts` 自己只声明不调用，故不入选 ⇒ 这条断言**不是恒真**。
    const usingFiles = ADMIN_SURFACE_SCOPE_FILES.filter((rel) =>
      taroApisInFile(path.join(BMINI_ROOT, rel)).some((api) => hazardous.has(api)),
    )
    const notWired = usingFiles.filter(
      (rel) =>
        !fs
          .readFileSync(path.join(BMINI_ROOT, rel), 'utf8')
          .includes('ADMIN_SURFACE_PLATFORM_GAP_HINTS'),
    )
    expect(notWired).toEqual([])
  })

  it('判据 3·缺口文案非空（占位条目即红）', () => {
    const empty = Object.entries(ADMIN_SURFACE_PLATFORM_GAP_HINTS)
      .filter(([, hint]) => String(hint).trim().length < 10)
      .map(([api]) => api)
    expect(empty).toEqual([])
  })

  it('判据 4·台账条目必须仍然活着（清单 ∩ 声明里已不存在 ⇒ 红；只许缩短）', () => {
    const live = new Set(ADMIN_SURFACE_TARO_APIS.filter((api) => hazardous.has(api)))
    const stale = Object.keys(ADMIN_SURFACE_PLATFORM_GAP_HINTS).filter((api) => !live.has(api))
    expect(stale).toEqual([])
  })

  it('判据 5·权限码台账 == 后端 @RequirePermission 注解（读写逐值）', () => {
    const mismatched: string[] = []
    for (const surface of ADMIN_SURFACES) {
      const controller = parseController(surface.controllerFile)
      const readCode = findEndpoint(controller, surface.readEndpoint)
      if (readCode !== surface.readPermission) {
        mismatched.push(
          `${surface.key}: 读码台账 ${surface.readPermission} ≠ 注解 ${readCode}（${describeEndpoint(surface.readEndpoint)}）`,
        )
      }
      if (surface.writeEndpoint) {
        const writeCode = findEndpoint(controller, surface.writeEndpoint)
        if (writeCode !== surface.writePermission) {
          mismatched.push(
            `${surface.key}: 写码台账 ${surface.writePermission} ≠ 注解 ${writeCode}（${describeEndpoint(surface.writeEndpoint)}）`,
          )
        }
      }
    }
    expect(mismatched).toEqual([])
  })

  it('判据 6·售后状态机与状态文案 == 后端 Java 字面量（逐值）', () => {
    const java = fs.readFileSync(path.join(REPO_ROOT, AFTER_SALES_SERVICE), 'utf8')
    expect(AFTER_SALES_STATUS_TRANSITIONS).toEqual(javaSetMap(java, 'STATUS_TRANSITIONS'))
    expect(AFTER_SALES_STATUS_LABELS).toEqual(javaStringMap(java, 'TICKET_STATUS_LABELS'))
  })
})
