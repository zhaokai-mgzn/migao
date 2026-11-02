// 2026-10-06 岗位 × 页面 深度验收 · 共享库
//
// 底座复用 2026-10-02 的 harness/lib.mjs（chromium / psql / loginUi / employeeLoginApi / shot / Recorder），
// 只覆盖「环境」与「产物目录」两件事。**不复制**那份 lib 的实现（避免第二份判定）。
//
// 纪律：**不落活 token**（issue #6303）—— 产物一律经 scrub() 脱敏，token 只留进程内存。
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { writeFileSync } from 'node:fs'

const HERE = dirname(fileURLToPath(import.meta.url))
export const ROUND_DIR = join(HERE, '..')

process.env.OUT_DIR ??= join(ROUND_DIR, 'out')
process.env.API_BASE ??= 'https://api.migaozn.com'
process.env.BASE_URL ??= 'https://merchant.migaozn.com'
process.env.REPO_ROOT ??= join(ROUND_DIR, '..', '..')

const BASE = join(ROUND_DIR, '..', '2026-10-02', 'tenant20-full-sweep', 'harness', 'lib.mjs')

const base = await import(BASE)

export const {
  chromium, api, loginApi, me, employeeLoginApi, loginUi, psql, psqlWrite,
  shot, newContext, sleep, Recorder, log, saveCtx, loadCtx,
  REPO_ROOT, WEB, API, OUT, SMS_CODE,
} = base

/** 脱敏：任何 JWT / Bearer / 密码字段不进产物（issue #6303）。 */
export function scrub(value) {
  if (typeof value === 'string') {
    return value
      .replace(/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}/g, '<JWT-REDACTED>')
      .replace(/Bearer\s+[A-Za-z0-9._-]{20,}/gi, 'Bearer <REDACTED>')
  }
  if (Array.isArray(value)) return value.map(scrub)
  if (value && typeof value === 'object') {
    const out = {}
    for (const [k, v] of Object.entries(value)) {
      out[k] = /token|password|secret|authorization/i.test(k) ? '<REDACTED>' : scrub(v)
    }
    return out
  }
  return value
}

/** 本轮探针对象的统一前缀（写面只碰自己造的）。 */
export const PROBE = 'A06验收'

/** 被测 SHA（部署腿日志逐字：三服务在跑 tag = sha-7332716 ⇒ 73327161f = origin/main HEAD）。 */
export const SUBJECT_SHA = '73327161f'
