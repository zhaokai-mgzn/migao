// case_ids: API-004, PR-008, OR-008
/**
 * 图片识别**三端契约同步守卫**（issue #5321 包 1）。
 *
 * 病根（本包**实测**踩到一次）：前端 `lib/api.ts` 打的端点路径与 admin-api 控制器的
 * `@RequestMapping` 是**两份手抄的副本**，没有守卫 ⇒ 改一处忘一处，页面按钮**静默 404**
 * （构建绿、单测绿、tsc 绿 —— 没有任何东西会变红）。同一形态在仓库里已有先例与解法：
 * `frontend/admin-web/tests/unit/lib/craft-calc-formula-sync.test.ts`（#4527）——
 * 把「副本」变成「**有守卫的副本**」。
 *
 * 本文件锁两条链（都逐值读**真值源**源文件比对，任一侧漂移即红）：
 *
 * ```
 * ① admin-web  lib/api.ts                      '/api/admin/image-recognition'
 *    └─ admin-api ImageRecognitionController    @RequestMapping("/api/admin/image-recognition")
 *       └─ admin-api ImageRecognitionClient     /api/internal/vision/recognize
 *          └─ ai-agent app/api/internal.py      @router.post("/vision/recognize")
 *
 * ② 前端读的字段 key ⊂ 内核 TARGET_FIELDS 的 key
 *    （前端读一个内核根本不返回的 key = 那一格永远填不上，且不报错）
 * ```
 *
 * 红证：把任一侧的路径改一个字（或前端 `valueOf(fields,'name')` 写成内核没有的 key）⇒ 本文件红。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** admin-web 根（vitest cwd）；仓库根 = 上溯两级 */
const WEB = process.cwd()
const REPO = resolve(WEB, '../..')

const read = (rel: string) => readFileSync(resolve(REPO, rel), 'utf-8')

const FRONT_API = 'frontend/admin-web/src/lib/api.ts'
const CONTROLLER = 'backend/admin-api/src/main/java/com/migao/admin/controller/ImageRecognitionController.java'
const CLIENT = 'backend/admin-api/src/main/java/com/migao/admin/service/ImageRecognitionClient.java'
const INTERNAL = 'backend/ai-agent-service/app/api/internal.py'
const TARGETS = 'backend/ai-agent-service/app/vision/targets.py'
const PREFILL = 'frontend/admin-web/src/lib/image-recognize.ts'

describe('图片识别 · 端点路径三端同步 (#5321)', () => {
  it('对外路径：admin-web 打的路径 === 控制器注册的路径', () => {
    const front = read(FRONT_API)
    const java = read(CONTROLLER)

    const frontHits = [...front.matchAll(/'(\/api\/admin\/[a-z-]+)'/g)].map((m) => m[1])
    const controllerPath = java.match(/@RequestMapping\("([^"]+)"\)/)?.[1]

    // 前端 api.ts 里唯一的这个新端点
    expect(frontHits).toContain('/api/admin/image-recognition')
    expect(controllerPath).toBe('/api/admin/image-recognition')
    // 两侧必须还能被机器读到同一个串（不是各自硬编码在注释里）
    expect(front).toContain(`'${controllerPath}'`)
  })

  it('控制器只暴露一个 POST 入口，且不带子路径（避免「前端打 /x、后端挂 /x/y」）', () => {
    const java = read(CONTROLLER)
    const mappings = [...java.matchAll(/@(Post|Get|Put|Delete|Patch)Mapping\b(\([^)]*\))?/g)]
      .map((m) => `${m[1]}Mapping${m[2] ?? ''}`)
    expect(mappings).toEqual(['PostMapping'])
  })

  it('对内路径：admin-api 客户端 === ai-agent 内部端点（含 /api 前缀）', () => {
    const java = read(CLIENT)
    const py = read(INTERNAL)

    const clientPath = java.match(/RECOGNIZE_PATH\s*=\s*"([^"]+)"/)?.[1]
    expect(clientPath).toBe('/api/internal/vision/recognize')
    // ai-agent 侧：router 以 prefix=/internal 挂载、main 再挂 /api ⇒ 源里写的是 /vision/recognize
    expect(py).toContain('@router.post("/vision/recognize")')
    expect(clientPath).toBe(`/api/internal${'/vision/recognize'}`)
  })
})

describe('图片识别 · 字段 key 契约同步 (#5321)', () => {
  /** 解析内核 TARGET_FIELDS 的 key（真值源；不 import Python，只读源） */
  function targetKeys(): Record<string, string[]> {
    const py = read(TARGETS)
    const out: Record<string, string[]> = {}
    for (const target of ['product', 'order']) {
      const block = py.match(new RegExp(`"${target}": \\(([\\s\\S]*?)\\n    \\),`))?.[1] || ''
      out[target] = [...block.matchAll(/TargetField\("([a-z_]+)"/g)].map((m) => m[1])
    }
    return out
  }

  it('内核两个 target 的字段表就是我们承诺的那两份（且两份不同 —— 不是一套字段两个页面填）', () => {
    const keys = targetKeys()
    expect(keys.product).toEqual(['name', 'color', 'material', 'craft', 'door_width', 'price'])
    expect(keys.order).toEqual([
      'customer_name',
      'customer_phone',
      'customer_address',
      'items',
      'quantity',
      'spec',
    ])
    const overlap = keys.product.filter((k) => keys.order.includes(k))
    expect(overlap).toEqual([])
  })

  it('前端读的每个 key 都在内核字段表里（读一个不存在的 key = 那格永远填不上且不报错）', () => {
    const known = new Set(Object.values(targetKeys()).flat())
    const front = read(PREFILL)

    // 「前端声称要从**响应**里读」的 key —— 四种写法都收（键是变量/常量的写法也要覆盖，
    // 否则守卫只看得见直写字符串的那几个，等于给了一半的盲区）。
    const consumed = new Set<string>()
    for (const m of front.matchAll(/(?:valueOf|pickField)\(fields,\s*'([a-z_]+)'\)/g)) consumed.add(m[1])
    for (const m of front.matchAll(/for \(const key of \[([^\]]+)\]/g)) {
      for (const k of m[1].matchAll(/'([a-z_]+)'/g)) consumed.add(k[1])
    }
    for (const m of front.matchAll(/fillBlank\('([a-z_]+)'/g)) consumed.add(m[1])
    for (const m of front.matchAll(/ORDER_DETAIL_KEYS\s*=\s*\[([^\]]+)\]/g)) {
      for (const k of m[1].matchAll(/'([a-z_]+)'/g)) consumed.add(k[1])
    }

    // 逐值钉住（不是"非空"）：少读一个键 / 多读一个键都要变红
    expect([...consumed].sort()).toEqual([
      'color', 'craft', 'customer_address', 'customer_name', 'customer_phone',
      'door_width', 'items', 'material', 'name', 'quantity', 'spec',
    ])
    expect([...consumed].filter((k) => !known.has(k))).toEqual([])
  })

  it('`[图片识别]` 标注串两端逐字一致（前端徽标文案 === 内核 FIELD_MARKER）', () => {
    const py = read('backend/ai-agent-service/app/vision/recognizer.py')
    const ts = read(PREFILL)
    const marker = py.match(/FIELD_MARKER\s*=\s*"([^"]+)"/)?.[1]
    expect(marker).toBe('[图片识别]')
    expect(ts).toContain(`RECOGNIZE_SOURCE_TAG = '${marker}'`)
  })
})