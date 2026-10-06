// 2026-10-06 智能派单省料验证 · 共享库
//
// 复用 2026-10-02 / 2026-10-06 两份 harness 的底座（chromium / api / psql / loginApi / shot / Recorder），
// **不复制**它们的实现（避免第二份判定）。本文件只覆盖「环境 + 产物目录 + 探针前缀」。
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
export const ROUND_DIR = join(HERE, '..')

process.env.OUT_DIR ??= join(ROUND_DIR, 'out')
process.env.API_BASE ??= 'https://api.migaozn.com'
process.env.BASE_URL ??= 'https://merchant.migaozn.com'
process.env.REPO_ROOT ??= join(ROUND_DIR, '..', '..')

const BASE = join(ROUND_DIR, '..', '2026-10-02', 'tenant20-full-sweep', 'harness', 'lib.mjs')
const base = await import(BASE)

export const { chromium, api, loginApi, me, loginUi, psql, psqlWrite, shot, Recorder, log, REPO_ROOT, WEB, API, OUT, SMS_CODE } = base

/** 脱敏：任何 JWT / Bearer / 密码字段不进产物。 */
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

/** 本轮探针对象统一前缀（写面只碰自己造的，收尾清理）。 */
export const PROBE = process.env.PROBE_PREFIX || 'SD06省料'
export const TENANT_ID = 25
