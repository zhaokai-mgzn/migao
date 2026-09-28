/**
 * 入库标签**短码口径**（issue #5052 P2/P3）
 *
 * 真值在服务端：`backend/admin-api/src/main/java/com/migao/admin/service/WorkerShortLinkService.java`
 * 的 `ALPHABET` / `CODE_LENGTH`（`InboundLabelService` 的注释写明「**复用** `WorkerShortLinkService`
 * 的静态口径」）⇒ 本文件是它的**镜像**，逐值由
 * `frontend/bmini-app/tests/inbound-print-geometry-single-source.test.ts` 的 C3 直接解析 Java 源**逐值比对**
 * （改一处不改另一处 ⇒ 红）。
 *
 * 🔴 客户端**不生成**短码（生成面 = 服务端 `allocateUniqueCode()` 唯一写方）；
 * 这里只做两件事：① 拼 `https://app.migaozn.com/i/<短码>`；② **校验**拿到的是不是合法短码 ——
 * 因为「缺码不画假码」（设计 §7.1）要求脏值（长度不对 / 含 `I` `L` `O` `U` 这类**生成面不产出**的字母）
 * 也走「缺码」分支，而不是把脏值画成一个**扫出来是错的**二维码。
 */
import { inboundLabelCodeUrl } from './truth'

/**
 * 人可读字母表（去 `I` `L` `O` `U`）—— 与 `WorkerShortLinkService.ALPHABET` 逐字一致（守卫 C3 钉住）。
 * ⚠️ 它的**唯一用途**是校验服务端发下来的码；写码路径不存在（客户端不分配短码）。
 */
export const SHORT_CODE_ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'

/** 短码长度（= `WorkerShortLinkService.CODE_LENGTH`） */
export const SHORT_CODE_LENGTH = 8

/** 拿到的是不是一个**合法**短码（长度 + 字母表；大小写不敏感，服务端可能回小写） */
export function isValidShortCode(raw: string | null | undefined): boolean {
  const code = String(raw ?? '').trim().toUpperCase()
  if (code.length !== SHORT_CODE_LENGTH) return false
  for (const ch of code) {
    if (!SHORT_CODE_ALPHABET.includes(ch)) return false
  }
  return true
}

/** 归一化（大写、去空白）；非法 ⇒ `null`（**不**试图修补、**不**截断补零） */
export function normalizeShortCode(raw: string | null | undefined): string | null {
  const code = String(raw ?? '').trim().toUpperCase()
  return isValidShortCode(code) ? code : null
}

/**
 * 标签二维码要编码的内容。
 *
 * 🔴 **缺码 / 脏码 ⇒ `null`**：调用方据此走「缺码不画假码」分支（留空位 + 可见标注），
 * **绝不**拿占位串（如 `https://app.migaozn.com/i/00000000`）去画一张能扫但指向不存在标签的图。
 */
export function labelCodePayload(raw: string | null | undefined): string | null {
  const code = normalizeShortCode(raw)
  return code ? inboundLabelCodeUrl(code) : null
}

/** 人可读短码（印在纸面上，工人可抄）；非法 ⇒ `null`（纸面显式标注缺失，不印占位串） */
export function humanReadableShortCode(raw: string | null | undefined): string | null {
  return normalizeShortCode(raw)
}
