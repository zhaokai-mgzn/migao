/**
 * 给「可能永远不回调」的等待加一道上限（issue #8307）。
 *
 * 真机现场（商米 V2s 手持机 / WebView 83，终端壳 1.0.17 与 1.0.19 均复现 2/2）：
 * 拍照入库 → 选图 → 点「识别」⇒ 按钮**永久置灰**，5s / 10s / 20s / 45s / 60s 截图逐字节相同，
 * 应用与 WebView 渲染进程 CPU 0.0% —— 页面不是「慢」，是**在等一个不会 settle 的 promise**。
 * `onRecognize` 的 `finally { setBusy(false) }` 只要走到就一定会恢复按钮 ⇒ 按钮不恢复 = 还在 await。
 *
 * 因此三步（读图 / 上传 / 识别）各自封顶：超时即 reject 一个**人话**错误，页面照常 `busy=false`
 * 并给出可行动出口（重试 / 扫码 / 手工录入），而不是把工人锁死在灰按钮上。
 * 这同时是**定位手段**：卡在哪一步，错误文案就点名哪一步。
 *
 * 🔴 不在这里做重试：重试策略属于页面决策（换图 / 换网络 / 改手工），工具只负责「不许无限等」。
 */

/** 读图 = 纯本机操作（`<img>` + canvas + jsQR），慢到 15s 已是异常（内存紧的老 WebView） */
export const INBOUND_DECODE_TIMEOUT_MS = 15_000
/** 上传 = 一张压缩图走内网 / 4G，20s 足够；不回调多半是通道卡死 */
export const INBOUND_UPLOAD_TIMEOUT_MS = 20_000
/** 识别 = 服务端 vision 兜底（唯一可能烧 LLM 的一步），给足 60s */
export const INBOUND_RECOGNIZE_TIMEOUT_MS = 60_000

export const INBOUND_PROGRESS_DECODE = '正在读取照片…'
export const INBOUND_PROGRESS_UPLOAD = '正在上传照片…'
export const INBOUND_PROGRESS_RECOGNIZE = '正在识别标签…'

export const INBOUND_DECODE_TIMEOUT_HINT = '照片读取超时，请重拍或换一张再试。'
export const INBOUND_UPLOAD_TIMEOUT_HINT = '照片上传超时，请检查网络后重试。'
export const INBOUND_RECOGNIZE_TIMEOUT_HINT = '识别超时，请重试；也可以直接扫码或手工录入。'

/**
 * 在 `ms` 内没结果 ⇒ reject（带 `message`）；有结果 / 有异常 ⇒ 原样透传。
 *
 * ⚠️ 超时**不会**取消底层请求（fetch / XHR 没有传入的 abort 口）—— 只保证**页面**不再无限等；
 * 底层请求由浏览器自己收尾，泄漏的上限是一次请求。
 */
export async function withTimeout<T>(task: Promise<T>, ms: number, message: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | null = null
  try {
    return await Promise.race([
      task,
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error(message)), ms)
      }),
    ])
  } finally {
    if (timer !== null) clearTimeout(timer)
  }
}
