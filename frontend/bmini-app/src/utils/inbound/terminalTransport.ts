/**
 * 观星台手持标签机（SUNMI V2s）的**终端打印运输**（issue #8089）。
 *
 * bmini 的标签页跑在两种壳里：
 * - 浏览器 / 小程序：Web Bluetooth + 德佟 DP235S（`./lpapiTransport`）；
 * - 观星台 Android 终端：WebView **没有 Web Bluetooth**，但注入了 `window.chrome.webview`
 *   与 `window.migaoTerminal` ⇒ 标签位图交机身商米内置打印机（终端 `print` 桥，>384 宽由原生缩到打印头）。
 *
 * 本模块只做「把已渲染的标签送出去 + 等回执」；留痕、计数、文案仍在 `./labelPrint`。
 */
import { LabelTransportError, type LabelTransport } from './labelPrint'
import type { RenderedLabel } from './labelCanvas'

/** 是否在观星台手持终端里（桥两端都在才算：`chrome.webview` 是壳、`migaoTerminal.post` 是注入的 bridge）。 */
export function hasTerminalPrintBridge(): boolean {
  return (
    typeof window !== 'undefined' &&
    !!(window as any).chrome?.webview &&
    typeof (window as any).migaoTerminal?.post === 'function'
  )
}

/**
 * 造一个终端打印通道。
 *
 * @param options.timeoutMs 等终端回执的上限（默认 20s；打印头忙 / 缺纸时原生会回失败而不是不回）
 */
export function createTerminalTransport(options: { timeoutMs?: number } = {}): LabelTransport {
  const timeoutMs = options.timeoutMs ?? 20000
  return {
    id: 'terminal-print-bridge',
    label: '商米内置打印机',
    print(label: RenderedLabel): Promise<void> {
      return new Promise((resolve, reject) => {
        const canvas = label.canvas as any
        if (!canvas || typeof canvas.toDataURL !== 'function') {
          reject(new LabelTransportError('render-failed', '标签画布不支持 toDataURL'))
          return
        }
        let image: string
        try {
          image = canvas.toDataURL('image/png')
        } catch (e) {
          reject(new LabelTransportError('render-failed', String(e)))
          return
        }
        const bridge = (window as any).migaoTerminal
        if (!bridge?.post) {
          reject(new LabelTransportError('print-failed', '终端打印桥不可用'))
          return
        }
        const onMessage = (ev: Event) => {
          const d = (ev as CustomEvent).detail
          if (!d || d.cmd !== 'print') return
          clearTimeout(timer)
          window.removeEventListener('migao-terminal', onMessage)
          if (d.ok) resolve()
          else reject(new LabelTransportError('print-failed', String(d.err || '终端打印失败')))
        }
        const timer = setTimeout(() => {
          window.removeEventListener('migao-terminal', onMessage)
          reject(new LabelTransportError('print-failed', '终端打印超时'))
        }, timeoutMs)
        window.addEventListener('migao-terminal', onMessage)
        try {
          bridge.post({ cmd: 'print', image, label: true, copies: 1 })
        } catch (e) {
          clearTimeout(timer)
          window.removeEventListener('migao-terminal', onMessage)
          reject(new LabelTransportError('print-failed', String(e)))
        }
      })
    },
  }
}

/**
 * 页面唯一入口：终端桥优先，否则回落到浏览器 Web Bluetooth（原路径一字不动）。
 * 返回 `null` = 两条通道都起不来（页面照旧给 `SDK_UNAVAILABLE_HINT`）。
 */
export async function createPrintTransport(): Promise<LabelTransport | null> {
  if (hasTerminalPrintBridge()) return createTerminalTransport()
  const { loadLpapi, createLpapiTransport } = await import('./lpapiTransport')
  const lpapi = await loadLpapi()
  return lpapi ? createLpapiTransport({ lpapi }) : null
}
