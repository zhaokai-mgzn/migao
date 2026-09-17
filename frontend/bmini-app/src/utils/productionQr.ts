/**
 * 加工单二维码解析（issue #3997，M4-G-3）
 *
 * 二维码内容由后端生成（M4-G-2），格式约定三种合法形态（容错解析）：
 *   1. 裸 order_id：`CSO260915-02615`
 *   2. 自定义 scheme：`migao://production/<order_id>?token=xxx`
 *   3. 带 query 的 URL：`<order_id>?token=xxx` / `https://.../<order_id>?token=xxx`
 * 其余一律返回 null —— 防呆：扫到别的二维码（会员码/商品码）不得瞎猜单号去请求。
 */

/** 加工单号字符集（字母/数字/中划线/下划线，长度 4~64；`CSO260915-02615` 实测形态） */
const ORDER_ID_PATTERN = /^[A-Za-z0-9_-]{4,64}$/

/** 从候选串归一化为 order_id；不合字符集返回 null */
function normalizeOrderId(candidate: string): string | null {
  let decoded = candidate
  try {
    decoded = decodeURIComponent(candidate)
  } catch {
    // 非法百分号编码：按原样处理
  }
  const value = decoded.trim()
  return ORDER_ID_PATTERN.test(value) ? value : null
}

/**
 * 解析扫码结果 → order_id；无法识别返回 null
 */
export function parseOrderIdFromQr(raw: string): string | null {
  const text = String(raw ?? '').trim()
  if (!text) return null

  // 形态 2：migao://production/<id>；其它 migao scheme（如 migao://order/xxx）不是加工单码
  if (/^migao:\/\//i.test(text)) {
    const matched = /^migao:\/\/production\/([^/?#]+)/i.exec(text)
    return matched ? normalizeOrderId(matched[1]) : null
  }

  // 形态 3 / 形态 1：去掉 query、fragment，取最后一个路径段（http(s) URL 同样适用）
  const path = text.split('?')[0].split('#')[0]
  const segments = path.split('/').filter(Boolean)
  const candidate = segments.length > 0 ? segments[segments.length - 1] : ''
  return normalizeOrderId(candidate)
}

export default { parseOrderIdFromQr }
