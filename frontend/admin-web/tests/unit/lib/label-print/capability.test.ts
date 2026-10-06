// case_ids: PP-011
// @vitest-environment jsdom
//
// PP-011（issue #6439）：**打印通道能力探测**（不是打印机定制功能）。
//
// 用户 2026-10-06 逐字：「其实我们不要做成打印机定制功能，因为可能企业内部用的是其他类型的打印机，
// 只要我们功能支持能连接上不同类型的打印机即可」「这个需要考虑用户有通过 window 电脑安装打印机驱动
// 或者蓝牙连接，或者 usb 连接各种情况」。
//
// ⇒ 两条通道、各自边界（**本文件测直连通道的探测与文案**）：
//   ① **系统打印**（`window.print()`，走 OS 驱动）：覆盖**任何**装了驱动的打印机（Windows 驱动 /
//      USB / 网络 / 已配对蓝牙）—— 已在 `lib/print-doc.ts` 落地，本单不改；
//   ② **浏览器直连**（Web Bluetooth / WebHID，免驱动）：**只有带 SDK 协议的机型**能连
//      —— Web Bluetooth 是点对点协议、**没有通用标准**，所以它永远**不是**「任意打印机」的答案。
//
// 逐条判据（都能判红）：
// ① **每一类失败各有可行动文案**：非空、两两不同、且**说清「现在能做什么」**（含动作词）
//    —— 合并成一句通用文案 ⇒ 必红（历史缺陷形态：工人只看到「打印失败」不知道去开蓝牙还是换浏览器）；
// ② **判定顺序 = 越早死越省事**：非安全上下文 → iOS → 无 Web Bluetooth；且 **iOS 排在「无 API」之前**
//    （iOS 上本来就没有 `navigator.bluetooth`，先判无 API 会把用户引向「换浏览器」这个**走不通**的动作）；
// ③ **系统打印那条路必须在文案里被点明**（否则用户以为直连不可用就等于「打不了」）；
// ④ `ok: true` 时 `hint` 为空串（不显示噪音）。
import { describe, expect, it } from 'vitest'
import {
  DIRECT_PRINT_HINTS,
  DIRECT_PRINT_READY_HINT,
  SYSTEM_PRINT_HINT,
  directPrintHint,
  probeDirectPrint,
  type DirectPrintFailureReason,
  type LabelPrintEnv,
} from '@/lib/label-print/capability'

const REASONS = Object.keys(DIRECT_PRINT_HINTS) as DirectPrintFailureReason[]

/** 动作词：一条「可行动的文案」至少要告诉用户**去做一件他能做的事** */
const ACTION_WORDS = ['换', '用', '打开', '刷新', '检查', '插', '装', '重', '选', '确认', '联系', '保持', '点']

const env = (over: Partial<LabelPrintEnv> = {}): LabelPrintEnv => ({
  secureContext: true,
  hasBluetoothApi: true,
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/153.0.0.0 Safari/537.36',
  isIos: false,
  isWechat: false,
  ...over,
})

describe('label-print/capability — 打印通道能力探测（issue #6439）', () => {
  it('判据 ①：每一类失败文案非空、不短、两两不同', () => {
    expect(REASONS.length).toBeGreaterThanOrEqual(8)
    const seen = new Map<string, string>()
    for (const reason of REASONS) {
      const hint = DIRECT_PRINT_HINTS[reason]
      expect(hint, `${reason} 文案不得为空`).toBeTruthy()
      expect(hint.trim().length, `${reason} 文案太短（说不清怎么回事）`).toBeGreaterThanOrEqual(12)
      const dup = seen.get(hint)
      expect(dup, `${reason} 与 ${dup} 文案完全相同 ⇒ 等于没有分类`).toBeUndefined()
      seen.set(hint, reason)
    }
  })

  it('判据 ①：每一类失败文案都给出**可行动**的去处（含动作词）', () => {
    for (const reason of REASONS) {
      const hint = DIRECT_PRINT_HINTS[reason]
      expect(
        ACTION_WORDS.some((word) => hint.includes(word)),
        `${reason} 的文案没有告诉用户能做什么：${hint}`,
      ).toBe(true)
    }
  })

  it('判据 ③：系统打印那条路必须被点明（直连不可用 ≠ 打不了）', () => {
    // 这条是「不做打印机定制功能」的核心：不装 SDK、不接蓝牙的打印机照样要能打
    expect(SYSTEM_PRINT_HINT).toContain('驱动')
    expect(SYSTEM_PRINT_HINT).toContain('打印任务卡')
    for (const reason of REASONS) {
      // 每一类直连失败都要把用户指回系统打印那条路
      expect(DIRECT_PRINT_HINTS[reason], `${reason} 未指出系统打印兜底路径`).toContain('打印任务卡')
    }
  })

  it('判据 ②：环境中一切正常 ⇒ ok，且不带噪音文案', () => {
    const cap = probeDirectPrint(env())
    expect(cap.ok).toBe(true)
    expect(cap.hint).toBe('')
    expect(DIRECT_PRINT_READY_HINT).not.toBe('')
  })

  it('判据 ②：非安全上下文 ⇒ insecure-context（Web Bluetooth 的硬要求）', () => {
    expect(probeDirectPrint(env({ secureContext: false }))).toMatchObject({
      ok: false,
      reason: 'insecure-context',
    })
    // 缺失（undefined）按不安全处理 = fail-closed
    expect(probeDirectPrint(env({ secureContext: undefined }))).toMatchObject({
      ok: false,
      reason: 'insecure-context',
    })
  })

  it('判据 ②：iOS 排在「无 API」之前（否则给的是走不通的动作）', () => {
    const cap = probeDirectPrint(env({ isIos: true, hasBluetoothApi: false }))
    expect(cap.reason).toBe('ios-unsupported')
    expect(cap.hint).not.toBe(DIRECT_PRINT_HINTS['no-web-bluetooth'])
  })

  it('判据 ②：无 Web Bluetooth ⇒ 桌面浏览器导向；微信内置浏览器 ⇒ 导向「在浏览器打开」', () => {
    expect(probeDirectPrint(env({ hasBluetoothApi: false })).reason).toBe('no-web-bluetooth')
    expect(probeDirectPrint(env({ hasBluetoothApi: false, isWechat: true })).reason).toBe('wechat-webview')
  })

  it('未知原因 ⇒ 回落到连接失败文案，**绝不返回空串**（空提示 = 静默失败）', () => {
    expect(directPrintHint('不存在的原因' as DirectPrintFailureReason)).toBe(DIRECT_PRINT_HINTS['connect-failed'])
    expect(directPrintHint('connect-failed')).toBe(DIRECT_PRINT_HINTS['connect-failed'])
  })
})
