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
