/**
 * **短链 JSON 解析面**（issue #8196）—— 小程序 A 档（微信「扫普通链接二维码打开小程序」）的
 * 「短码 ⇒ 报工 token」那一跳。
 *
 * ## 为什么需要它
 *
 * 纸上的码 = `https://app.migaozn.com/s/<短码>`（已印出去、不可重印）。H5 靠服务端 **302** 进
 * `/b/?t=<token>`，而**小程序不跟随 302** ⇒ 微信把整条链接放进 `getEnterOptionsSync().query.q` 后，
 * 页面手里只有一个短码，`fetch` 那一跳拿到的是空响应。服务端因此提供**显式**的 JSON 面
 * （`GET /s/{短码}/json` ⇒ `{reportPath, token}`，判据见 admin-api 的 `WorkerShortLinkControllerTest`）——
 * 本模块是它在前端**唯一**的调用点。
 *
 * ## 三条纪律
 *
 * ① **单一真源**：短码 ⇒ token 的换发只在服务端（本模块不拼 `/b/report/`、不猜码形态）；
 *    返回的 `reportPath` 只用于自检字段形态，**页面不用它做路由**。
 * ② **public 面不携带商家凭据**（`skipAuth`）：短码在纸上，对任何持码人等价；这一跳不是身份入口
 *    （工人身份仍只由工人 session 承担）。
 * ③ **有界失败**：未知 / 已撤销用状态码区分（404 / 410），读不到（离线 / 旧后端无此路径）
 *    由调用方**退回既有行为**（短码原样交给工人扫码端点）—— 已印出去的码不能因新版前端而作废。
 */
import { API_BASE_URL } from '../utils/constants'
import { get } from '../utils/request'

/** JSON 面的成功体（与 302 的 `Location` 同源：报工页路径 + token） */
export interface WorkerShortLinkReport {
  reportPath: string
  token: string
}

export interface WorkerShortLinkResult {
  success: boolean
  data?: WorkerShortLinkReport
  /** 404 = 未知短码 / 410 = 已撤销（这张纸作废）；缺省 = 读不到（网络 / 旧后端无此路径） */
  statusCode?: number
  message?: string
}

/** 未知 / 已撤销码的**可行动**文案（页面直接上屏；服务端错误体只给机器可读的 `error`） */
export const WORKER_SHORT_LINK_INVALID_HINT = '这张码不存在或已失效：请让商家核对，或手动输入单号'

/** 响应形状不对（200 但没有 token）：当成读不到，由调用方退回既有行为 */
const BAD_RESPONSE = '短链解析返回了无法识别的内容'

/**
 * 短码 ⇒ 报工 token（`GET /s/{短码}/json`）。
 *
 * @param code 短码（8 位 Crockford Base32；服务端自己归一化手输抄错形态）
 * @returns `success:false` 时**不抛** —— 调用方按 `statusCode` 决定「明确报错」还是「退回既有行为」
 */
export async function resolveWorkerShortLink(code: string): Promise<WorkerShortLinkResult> {
  const shortCode = String(code ?? '').trim()
  if (shortCode === '') {
    return { success: false, message: BAD_RESPONSE }
  }
  try {
    const res = await get<WorkerShortLinkReport>(`/s/${encodeURIComponent(shortCode)}/json`, {
      baseURL: API_BASE_URL,
      // 显式声明想要 JSON：服务端把它做成**独立子路径**（不是内容协商）—— 这里只是客户端的礼貌声明，
      // 印刷品红线（旧路径任何 Accept 都仍是 302）由服务端与本文件的行为共同保证。
      headers: { Accept: 'application/json' },
      skipAuth: true,
    })
    if (res && typeof res.token === 'string' && res.token !== '') {
      return {
        success: true,
        data: { reportPath: String(res.reportPath ?? ''), token: res.token },
      }
    }
    return { success: false, message: BAD_RESPONSE }
  } catch (error: any) {
    return {
      success: false,
      statusCode: error?.statusCode,
      message: String(error?.data?.error || error?.message || BAD_RESPONSE),
    }
  }
}

export default { resolveWorkerShortLink }
