// case_ids: BM-045
/**
 * 类级元守卫（AGENTS.md 铁律 8「类级固化」，issue #6564）：
 * **工人登录 / 切换工人的租户只由服务端解析** —— 让「前端再拍一个默认租户」这类缺陷进不来。
 *
 * ## 病灶（生产实测）
 * `workerService.ts` 的 `workerLogin(..., tenantId: number = DEFAULT_TENANT_ID)` 默认发租户 1，
 * 而 B 端 H5（`app.migaozn.com/b/`，无租户子域、无 `X-Tenant-Id` 头）⇒ 服务端按 body 租户 1
 * 注入租户谓词 ⇒ 租户 25（企业编码 `migao`）的工人**输入正确 PIN 也恒 401**。
 *
 * ## 判据（每条都会红；红证见本文件下方 `describe` 的注入读数）
 * | # | 判据 | 怎么让它单独红 |
 * |---|---|---|
 * | 1 | `services/workerService.ts` 两条工人请求体 = `{ workerNo, pin, deviceLabel, enterpriseCode }`（各一次） | 把 `enterpriseCode` 删掉 / 换回 `tenantId` ⇒ 红 |
 * | 2 | 工人登录链路任何文件都**不引用** `DEFAULT_TENANT_ID` | 把默认租户塞回去 ⇒ 红 |
 * | 3 | 三个入口（独立工人登录页 / 工人 tab / WorkerBar）都把企业编码传下去 | 摘掉传参 ⇒ 红 |
 *
 * ## 边界（照实登记）
 * · 只判**端侧源码**：服务端的解析优先级由 `WorkerAuthControllerTest` / `WorkerTenantResolver` 承担。
 * · 不判「输入框长什么样」（那是登录页既有判据的面）。
 * · 注释被剥掉后再扫：注释里提到 `tenantId` 是在讲沿革，不是请求体（`stripComments` 与
 *   `h5-platform-api-guard.test.ts` 共用同一份实现）。
 */
import fs from 'fs'
import path from 'path'
import { stripComments } from './helpers/h5PlatformLists'

const SRC = path.join(__dirname, '..', 'src')
const code = (rel: string): string => stripComments(fs.readFileSync(path.join(SRC, rel), 'utf8'))

/** 工人登录 / 切换工人链路涉及的文件（新前端不得在其中拍租户）。 */
const WORKER_LOGIN_FILES = [
  'services/workerService.ts',
  'pages/worker/login/index.tsx',
  'pages/auth/login/index.tsx',
  'components/WorkerBar.tsx',
]

describe('类级守卫 · 工人登录租户来源（issue #6564）', () => {
  it('🔴 workerService.ts 两条工人请求体：含 enterpriseCode、不含 tenantId/DEFAULT_TENANT_ID', () => {
    const service = code('services/workerService.ts')

    expect(service).toContain("'/api/worker/login'")
    expect(service).toContain("'/api/worker/session/switch'")
    // 请求体逐个钉死：登录 + 切换**各一次**（少一处或换回 tenantId ⇒ 当场红）
    const bodies = service.split('{ workerNo, pin, deviceLabel, enterpriseCode }').length - 1
    expect(bodies).toBe(2)
    expect(service).not.toMatch(/\btenantId\b/)
    expect(service).not.toContain('DEFAULT_TENANT_ID')
  })

  it('🔴 工人登录链路任何文件都不得引用 DEFAULT_TENANT_ID（默认租户 = 本缺陷的根因）', () => {
    for (const rel of WORKER_LOGIN_FILES) {
      expect(code(rel)).not.toContain('DEFAULT_TENANT_ID')
    }
  })

  it('三个入口都把企业编码传给服务（独立工人登录页 / 工人 tab / WorkerBar 切换）', () => {
    for (const rel of ['pages/worker/login/index.tsx', 'pages/auth/login/index.tsx']) {
      const src = code(rel)
      expect(src).toMatch(/[Ee]nterpriseCode/)
      expect(src).toMatch(/workerLogin\(/)
    }
    const bar = code('components/WorkerBar.tsx')
    expect(bar).toMatch(/[Ee]nterpriseCode/)
    expect(bar).toMatch(/switchWorker\(/)
  })
})
