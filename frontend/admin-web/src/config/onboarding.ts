/**
 * 自助入驻（官网「商家入驻 / 免费开通」入口）是否对外开放。
 *
 * 内测期（2026-11-23 起，issue #9066）**关闭**：官网导航 / 页脚 / 各页 CTA 不再露出自助入驻入口，
 * 引导文案同步收口为「预约演示 / 联系我们」。
 *
 * ⚠️ 只隐藏**公开入口**，不做其他收缩：`/register` 页面与 `POST /api/auth/register`
 * **保持原样可用** —— 内部同事直接访问 `<站点>/register` 自助开通测试租户，这就是内测期的内部入口
 * （公开面没有任何链接指向它；`robots.txt` 一直 Disallow `/register`）。
 *
 * 恢复条件（内测结束）= 把这里改回 `true`：
 * 判据 `tests/unit/onboarding-entry-hidden.test.tsx` 会当场变红，按它的提示同步各页 CTA 断言即可。
 */
export const SELF_SERVICE_ONBOARDING_OPEN = false
