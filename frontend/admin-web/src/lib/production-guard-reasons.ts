/**
 * 生产页面的「护栏理由 → 可读文案」解析（纯函数，无 React 依赖）。
 *
 * ⚠️ **为什么放在 `lib/` 而不是页面文件里**（issue #4412）：
 * Next 的 route 文件（`page.tsx` / `layout.tsx` / `route.ts` …）**只允许导出框架认识的字段**
 * （`default` / `metadata` / `generateMetadata` / `dynamic` / `revalidate` …）。
 * 在 `page.tsx` 里 `export function feeGuardReasons(...)` ⇒ `next build` 直接
 * `Failed to compile: "feeGuardReasons" is not a valid Page export field`。
 * 而 Next 14 **没有 `next typegen`** ⇒ 这个契约**只有 `next build` 会校验**，
 * `tsc --noEmit` 看不见 ⇒ 曾造成「CI 全绿、`deploy-frontend` 连续 4 次红」（云测试环境前端停在旧镜像）。
 * ⇒ 判据：**route 文件里不放任何非框架字段的导出**；页面要用的纯函数一律落到 `lib/`。
 *
 * 口径 = 后端**真实**信封（issue #4308「冻结补遗 ②」/ #4386 判据 3）：
 * `{success:false, error:{code, message, details:[{field, message}]}, suggestion}` ——
 * 主口径 = `error.details[].message`（逐条），退化 = `error.message`（一句话摘要），最后才用 `Error.message`。
 *
 * ⚠️ **不读 `error_messages`**：该顶层字段后端不存在（全仓零命中），且 `error` 是**对象**不是字符串。
 * 曾按那个形状读 ⇒ 真实失败路径静默落到 `Error.message`，商家只看到
 * 「Request failed with status code 422」而看不到任何护栏理由（集成方探针实证 2/2 红）。
 */

/** 后端失败信封里我们关心的那几层（结构性最小类型，不引第三方） */
type ErrorEnvelope = {
  response?: { data?: { error?: { message?: unknown; details?: unknown } } }
  message?: string
}

/** 从信封里取 `error.details[].message`（逐条）；取不到返回空数组 */
function detailsMessages(error: unknown): string[] {
  const err = (error as ErrorEnvelope | null | undefined)?.response?.data?.error
  const details = err?.details
  if (!Array.isArray(details) || details.length === 0) return []
  return details
    .map((d) => (typeof d === 'string' ? d : (d as { message?: unknown } | null)?.message))
    .filter((m): m is string => typeof m === 'string' && m.trim().length > 0)
}

/** 退化口径：`error.message` → `Error.message`（都没有则由调用方给兜底文案） */
function fallbackMessage(error: unknown): string | null {
  const err = (error as ErrorEnvelope | null | undefined)?.response?.data?.error
  if (typeof err?.message === 'string' && err.message.trim()) return err.message
  const m = (error as ErrorEnvelope | null | undefined)?.message
  return typeof m === 'string' && m ? m : null
}

/**
 * 工艺路线护栏理由 → 逐条可读文案（issue #4308 的护栏清单：空序列 / 工序不存在 / 重复 /
 * 缺必完工序 / 权限）。识别不了的原样透出 —— **绝不吞掉后端理由**（吞掉就等于回到「只弹保存失败」）。
 */
export function describeRoutingGuard(raw: string): string {
  const s = (raw || '').trim()
  if (!s) return '保存失败'
  const dup = s.match(/重复|duplicate/i)
  if (dup) return `工序重复：${s}`
  if (/不存在/.test(s) || /不在/.test(s) || /not[_ ]?found/i.test(s)) return `工序不存在：${s}`
  if (/必完/.test(s)) return `缺少必完工序：${s}`
  if (/空|empty/i.test(s)) return `序列不能为空：${s}`
  if (/权限|forbidden|denied/i.test(s)) return `没有工艺路线管理权限：${s}`
  return s
}

/** 工艺路线页：从失败的请求里取**逐条**护栏理由（带路线专属文案前缀） */
export function routingGuardReasons(error: unknown): string[] {
  const reasons = detailsMessages(error)
  if (reasons.length > 0) return reasons.map((r) => describeRoutingGuard(r))
  const fb = fallbackMessage(error)
  if (fb) return [describeRoutingGuard(fb)]
  return ['保存失败，请稍后重试']
}

/**
 * 加工费页：从失败的请求里取**逐条**护栏理由。
 *
 * 与路线页 `routingGuardReasons` 同口径，但**不套**那里的路线专属文案前缀
 * （工序重复/缺必完工序…）—— 本页的字段是加工项与单价，套错标签会误导商家。
 */
export function feeGuardReasons(error: unknown): string[] {
  const reasons = detailsMessages(error)
  if (reasons.length > 0) return reasons
  const fb = fallbackMessage(error)
  if (fb) return [fb]
  return ['保存失败，请稍后重试']
}
