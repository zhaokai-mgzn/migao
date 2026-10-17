// case_ids: UI-112
/**
 * 「失败原因必须是**业务文案**」—— 传输层读数不得上屏（2026-10-17 用户裁定）。
 *
 * ## 病灶（用户逐字）
 *
 * 「点击一键合并派单后页面报错了……**这个错误提示非常低级，用户完全看不懂**，
 * 得把报错原因用业务文案写清楚，而不是技术语言」——
 * 页面上留的是 `合并预览失败：Request failed with status code 422`。
 *
 * ## 归因（两层，缺一层都修不掉）
 *
 * ① **调用面**：`production/pool/page.tsx` 的 `dispatchErrorText` 取的是 `e.message`，
 *    而 axios 错误的 `.message` **就是**那句传输层读数；服务端的业务原因在
 *    `error.response.data.error.message`（`GlobalExceptionHandler` 的
 *    `ApiResponse.error(code, message, details)`）里，被那一行丢掉了。
 * ② **共享原语**：`extractApiErrorMessage` 的兜底链里也留着 `err.message` 这一格
 *    ⇒ 就算调用面改用原语，服务端文案缺失时**照样**端出技术语言。
 *
 * ## 判据分两半（都要求会红）
 *
 * - **行为面**：原语的取值顺序（服务端文案优先 / 传输层原文绝不外传 / 本地错误仍可用 message）；
 * - **形态面**：`src/app` + `src/components` 里不得再有「三元表达式直接端 `e.message`」这种写法
 *   —— 它是同一个缺陷的可复制形态（改前 9 处：智能派单 1 / 知识库 8 / 省料看板 1）。
 *
 * ⚠️ **判不了的一面（照实登记）**：服务端**真的**回了什么文案（本次 422 的业务原因）
 * 需要在真实环境里复现；本判据只保证「服务端给了什么，商家就看到什么」。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { extractApiErrorMessage } from '@/lib/api-error'

const ROOT = process.cwd()

/** 递归收集商家后台的源码文件（与 `scripts/user-copy-scan.mjs` 同口径的扫描面） */
function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === '.next') continue
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.(tsx|ts)$/.test(entry)) out.push(full)
  }
  return out
}

/** 形态：`instanceof Error ? <任意>.message`（把**错误对象的 message** 当展示文案） */
const RAW_MESSAGE_SHAPE = /instanceof Error\s*\?[^\n:]*\.message/

describe('失败原因 = 业务文案（UI-112）', () => {
  it('服务端文案优先：业务原因逐字透出（不是 `Request failed with status code 422`）', () => {
    // 真形态（axios 错误）：`message` 是传输层读数，业务原因在 `response.data.error.message`
    const axiosErr = {
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: { success: false, error: { code: 'VALIDATION_ERROR', message: '加急单不能并入合并派单' } },
      },
    }
    // 注入：把 `response.data.error.message` 从取值链里删掉 ⇒ 本条红
    expect(extractApiErrorMessage(axiosErr, '合并派单失败')).toBe('加急单不能并入合并派单')
  })

  it('🔴 服务端没给文案时**绝不**端出传输层原文（落到业务兜底）', () => {
    // 注入：把 `err.message` 那一格放回兜底链 ⇒ 本条红（这正是改前的形态）
    expect(
      extractApiErrorMessage(
        { isAxiosError: true, message: 'Request failed with status code 500', response: { status: 500, data: {} } },
        '合并派单失败，请稍后重试',
      ),
    ).toBe('合并派单失败，请稍后重试')
    expect(
      extractApiErrorMessage({ isAxiosError: true, message: 'Network Error', request: {} }, '网络不通'),
    ).toBe('网络不通')
  })

  it('反向自证：本地错误（客户端校验等，非传输层）仍用自己的 message', () => {
    // 不是「把 message 一律禁掉」—— 那会让本地校验的精确提示消失（判据要能区分两类）
    expect(extractApiErrorMessage(new Error('至少选一张卡'), '保存失败')).toBe('至少选一张卡')
  })

  it('形态面：`src/app` + `src/components` 里不得再有「三元直接端 `e.message`」', () => {
    const files = [...walk(join(ROOT, 'src/app')), ...walk(join(ROOT, 'src/components'))]
    // 自证扫描面非空（空集上的「没有违规」恒真）；现取实测 = 186 个文件，阈值留在它下面一档
    expect(files.length).toBeGreaterThan(150)
    const offenders = files
      .filter((f) => RAW_MESSAGE_SHAPE.test(readFileSync(f, 'utf-8')))
      .map((f) => relative(ROOT, f))
    // 注入：把任意一处改回 `e instanceof Error ? e.message : 'X失败'` ⇒ 具名报出该文件
    expect(offenders).toEqual([])
  })
})
