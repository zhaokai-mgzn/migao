/**
 * **报工页的入口参数 + 登录回跳**（issue #7879）——「一套代码两个编译目标」的那一层。
 *
 * ## 为什么单独一个模块（而不是写在页面里）
 *
 * 入口参数的**来源按平台不同**（h5 = URL search；小程序 = `getEnterOptionsSync().query`
 * / 页面参数），但「取出来之后是什么」必须**只有一份**（`utils/scanInput.ts` 的 `resolveScanLanding`）。
 * ⇒ 平台分支只住在这里；页面（`pages/worker/report/index.tsx`）只消费 {@link currentEntryLanding}
 * 的**返回值**，**不出现 `process.env.TARO_ENV` / `isH5()` 判断**（判据
 * `tests/report-landing.test.ts` 的结构断言：页面源码里不得出现平台判断）。
 *
 * ## A 档 = 主路径（issue #7881）
 *
 * 微信扫纸上的 `https://app.migaozn.com/s/<短码>` ⇒ 直接打开小程序 `pages/worker/report/index`，
 * 参数在 `Taro.getEnterOptionsSync().query.q`（URL-encoded 的完整链接）。本模块把 `q`（以及
 * B 档的 `scene`、小程序内扫一扫的原文、页面参数）收口到同一个解析器。
 *
 * ## 登录回跳（新手机首次扫码 = 没有工人 session）
 *
 * 报工页在无工人 session 时给「工号 + PIN 登录」入口；点它之前用 {@link rememberReportReturn}
 * 把「登录完要回报工页 + 继续报这个码」记在本机 ⇒ 登录成功后
 * `pages/auth/login/index.tsx` 用 {@link takeReportReturn} 读到它就 `redirectTo` 回报工页
 * （**不是**停在登录页、**不是**落到商家 tabBar / 工人首页就把活丢了）。
 * 存的是**码**不是身份（PIN 绝不落盘，见 `rememberAccount` 的既有口径）。
 */
import Taro from '@tarojs/taro'
import { isH5, isWeapp } from './platform'
import { REPORT_PAGE_ROUTE } from './inbound/gaps'
import { NONE_LANDING, resolveScanLanding, type ScanLanding } from './scanInput'

/** 本机临时键：登录完要回报工页继续报的那个码（一次性，读到即清） */
export const PENDING_REPORT_RETURN_KEY = 'workerPendingReportReturn'

function routerParams(): Record<string, any> | null {
  try {
    return (Taro.getCurrentInstance?.()?.router?.params as Record<string, any>) ?? null
  } catch {
    return null
  }
}

function enterQuery(): Record<string, any> | null {
  try {
    return (Taro.getEnterOptionsSync?.()?.query as Record<string, any>) ?? null
  } catch {
    return null
  }
}

/**
 * **当前入口** ⇒ 去哪一页 + 什么码（页面与启动器只消费它）。
 *
 * - h5：页面参数优先（`redirectTo` 之后 Taro 把 query 放进 `router.params`），其次 URL search；
 * - 小程序：冷启动 `query`（A 档 `q` / B 档 `scene`）+ 页面参数（`redirectTo` 带过去的 `t`）；
 * - 其它平台（编译到别的端）⇒ 不去（`kind: 'none'`）。
 */
export function currentEntryLanding(): ScanLanding {
  if (isH5()) {
    const params = routerParams()
    const search = typeof window === 'undefined' ? '' : window.location?.search
    return resolveScanLanding({ params, search })
  }
  if (isWeapp()) {
    return resolveScanLanding({ query: enterQuery(), params: routerParams() })
  }
  return NONE_LANDING
}

/**
 * 记住「登录完要回报工页」；`code` = 这次要接着报的码（可为空：只回报工页重新扫）。
 *
 * 存不下（隐私模式 / 配额满）⇒ **静默降级**：登录后仍回工人首页（既有动线），
 * 但绝不因此把登录挡掉。
 */
export function rememberReportReturn(code: string): void {
  try {
    Taro.setStorageSync(PENDING_REPORT_RETURN_KEY, JSON.stringify({ code: String(code ?? '') }))
  } catch {
    /* 记不住就退回既有动线：登录本身不受影响 */
  }
}

/** 读并**清**那条临时记录（一次性：读到即清，避免下次登录被上一次的码带跑） */
export function takeReportReturn(): { present: boolean; code: string } {
  let raw: any = ''
  try {
    raw = Taro.getStorageSync(PENDING_REPORT_RETURN_KEY)
  } catch {
    return { present: false, code: '' }
  }
  if (!raw) return { present: false, code: '' }
  try {
    Taro.removeStorageSync(PENDING_REPORT_RETURN_KEY)
  } catch {
    /* 清不掉也继续：读到即用，最坏情况是下次登录多回一次报工页 */
  }
  try {
    const parsed = JSON.parse(String(raw))
    return { present: true, code: typeof parsed?.code === 'string' ? parsed.code : '' }
  } catch {
    return { present: true, code: '' }
  }
}

/** 登录完回跳的目标 URL（路由字面量仍只有 `gaps.ts` 一份） */
export function reportReturnUrl(code: string): string {
  return `${REPORT_PAGE_ROUTE}?t=${encodeURIComponent(String(code ?? ''))}`
}
