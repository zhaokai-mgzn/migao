/**
 * 纸型 → 打印机的**引导**与**本机登记**（issue #7957）。
 *
 * ## 为什么只有「引导 + 登记」，没有「自动选打印机」
 *
 * 浏览器 `window.print()` **没有**「指定打印机」参数；打印对话框是原生窗口，JS 既不能预选，
 * 也**读不到**用户最后选了哪台（`beforeprint` / `afterprint` 事件不带打印机信息）。
 * ⇒ 「记住上次**实际**用的打印机」在浏览器侧**不可能**实现，任何看起来能做到的实现都是假的。
 *
 * 所以这里只做两件真实可做的事：
 * ① **纸型 ⇒ 打印机类型**的引导（A4 激光 / 针式连续纸 / 标签打印机）—— 让商家在对话框里
 *    有个明确的选型预期，而不是面对一串打印机名猜；
 * ② 让商家**一次性登记**「这台电脑的该纸型打印机叫什么」，存在本机 `localStorage`
 *    （键里带纸型 ⇒ 一台电脑三台打印机各记各的）。
 *
 * 🔴 **不落服务端**：打印机是**这台机器**的外设事实，不是租户配置 —— 存服务端会让 A 店的
 * 「针式打印机」名字出现在 B 店的对话框提示里（比没有提示更糟）。
 * 🔴 **不编具体型号**：没登记就只显示通用类型；型号只能由本机使用者填。
 */
import type { PrintMediaId } from '@/lib/print-media'

/** 纸型 ⇒ 通用打印机类型（**不写型号**；型号来自本机登记） */
export const PRINTER_KIND_BY_MEDIA: Record<PrintMediaId, string> = {
  a4: 'A4 激光打印机',
  'continuous-241x140': '针式打印机（连续纸）',
  'label-50x140': '标签打印机',
  // 历史/旁支标签纸（介质矩阵里仍在册，见 `PRINT_MEDIA_IDS`）——同一类外设
  'label-50x70': '标签打印机',
  'label-50x80': '标签打印机',
}

/** 未知纸型的兜底文案（历史行 / 未来新增介质）——只说「打印机」，不编类型 */
export const FALLBACK_PRINTER_KIND = '打印机'

const STORAGE_PREFIX = 'migao.print.printer.'
const DEFAULT_KIND = FALLBACK_PRINTER_KIND

function storageKey(media: string): string {
  return `${STORAGE_PREFIX}${media}`
}

/** 纸型的通用打印机类型（未知纸型 ⇒ 「打印机」） */
export function printerKindOf(media: string | null | undefined): string {
  if (!media) return DEFAULT_KIND
  return PRINTER_KIND_BY_MEDIA[media as PrintMediaId] ?? DEFAULT_KIND
}

/** 读本机登记的打印机名（未登记 / 读不到 / localStorage 不可用 ⇒ `null`） */
export function readPrinterName(media: string | null | undefined): string | null {
  if (!media) return null
  try {
    const raw = window.localStorage.getItem(storageKey(media))
    const name = (raw ?? '').trim()
    return name.length > 0 ? name : null
  } catch {
    // 隐私模式 / 被策略禁用 ⇒ 当「没登记」处理（**不抛**：打印链路不能被外设登记拖垮）
    return null
  }
}

/** 登记本机该纸型的打印机名；`trim()` 后为空 ⇒ 清掉登记（不留空串） */
export function savePrinterName(media: string | null | undefined, name: string): void {
  if (!media) return
  try {
    const trimmed = name.trim()
    if (trimmed.length === 0) {
      window.localStorage.removeItem(storageKey(media))
      return
    }
    window.localStorage.setItem(storageKey(media), trimmed)
  } catch {
    // 写不进去（配额 / 隐私模式）⇒ 静默降级：页面照旧可打印，只是这次不记住
  }
}
