/**
 * B 端商家端 h5（手机浏览器 / 扫码使用）地址的**唯一读取点**（issue #5668）。
 *
 * 为什么单独成一个模块 —— 这条地址要同时满足两条判据：
 *   ① **单一真值**：`NEXT_PUBLIC_BMINI_H5_URL` 只在这里读，组件里**不许**硬编码域名
 *      （同族反面教材：craft-display 三份副本，issue #4393）；
 *   ② **缺配置不画假码**：取不到值 ⇒ 返回空串，由调用方渲染「移动端地址未配置」，
 *      而**不是**画一个指向空/错地址的二维码（同族判据：洗水码「缺码不画假码」）——
 *      画了假码，用户扫出白屏或别的站点，而页面上一切看起来正常。
 *
 * ⚠️ 读值写在**函数体内**（不是模块级常量）：Next 的构建期 `process.env.NEXT_PUBLIC_*`
 *    文本替换照旧生效；同时单测可以 `vi.stubEnv('NEXT_PUBLIC_BMINI_H5_URL', …)` 逐格给值
 *    （同 `frontend/admin-web/src/lib/utils.ts` 的 `resolveImageUrl` 口径）。
 *
 * 取值链（线上）：`deploy-frontend.yml` 的 `--build-arg` → `frontend/admin-web/Dockerfile`
 *   的 `ENV` → 构建期 baked 进 JS。缺省值即线上落位 `https://app.migaozn.com/b/`。
 */
export function getBminiH5Url(): string {
  return (process.env.NEXT_PUBLIC_BMINI_H5_URL || '').trim()
}

/**
 * 「手机端」二维码的**内容**（issue #7825）—— 有票据就带 `?qr=`，没有票据就是裸地址。
 *
 * 为什么拼串也必须留在这个模块：整条链路（顶栏 → 二维码 → 手机 H5 兑换）只认**一个**地址真值；
 * 组件里再抄一遍 query 拼法，就成了「改一处漏一处」的第二份副本
 * （判据 = `tests/unit_ci_workflows/test_frontend_bmini_entry_single_source.py`）。
 *
 * 票据是**短期持有凭证**（120 秒、单次有效），只在二维码里出现 —— 界面上可见的地址仍是裸地址。
 *
 * @param baseUrl 入口地址（`getBminiH5Url()` 的返回值）
 * @param ticket  一次性票据；空值 ⇒ 原样返回裸地址（降级为「扫码后登录」）
 */
export function buildMobileEntryUrl(baseUrl: string, ticket?: string | null): string {
  const base = (baseUrl || '').trim()
  if (!base) return ''
  const value = (ticket || '').trim()
  if (!value) return base
  const separator = base.includes('?') ? '&' : '?'
  return `${base}${separator}qr=${encodeURIComponent(value)}`
}
