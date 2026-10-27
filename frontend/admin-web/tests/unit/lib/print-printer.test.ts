// case_ids: OR-072
// @vitest-environment jsdom
/**
 * 纸型 → 打印机引导 + **本机打印机名**登记（issue #7957）。
 *
 * 事实约束（先写死在这里，防止后人"顺手"做一个假能力）：
 * 浏览器 `window.print()` 没有「指定打印机」参数，JS 也**读不到**用户在系统打印对话框里选了哪台
 * ⇒ 「记住上次**实际**用的打印机」在浏览器侧不可能实现。本模块只做两件事：
 * ① 纸型 ⇒ **打印机类型**（A4 激光 / 针式连续纸 / 标签打印机）的引导；
 * ② 让商家**登记**「这台电脑的该纸型打印机叫什么」，存 localStorage（每台机器的外设事实，不落服务端）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'

import {
  PRINTER_KIND_BY_MEDIA,
  printerKindOf,
  readPrinterName,
  savePrinterName,
} from '@/lib/print-printer'

describe('纸型 → 打印机类型（issue #7957）', () => {
  beforeEach(() => localStorage.clear())

  it('① 三种纸各有一句通用类型（不写具体型号，型号由本机登记）', () => {
    expect(PRINTER_KIND_BY_MEDIA.a4).toBe('A4 激光打印机')
    expect(PRINTER_KIND_BY_MEDIA['continuous-241x140']).toBe('针式打印机（连续纸）')
    expect(PRINTER_KIND_BY_MEDIA['label-50x119']).toBe('标签打印机')
  })

  it('①b 未知纸型（历史行 / 未来新增）⇒ 兜底文案，**不编类型**', () => {
    expect(printerKindOf('legacy-80mm')).toBe('打印机')
  })

  it('② 登记 → 读回（trim 后保存）', () => {
    savePrinterName('a4', '  HP LaserJet M404  ')
    expect(readPrinterName('a4')).toBe('HP LaserJet M404')
  })

  it('③ 按纸型隔离：A4 登记的名字不会串到连续纸 / 标签纸', () => {
    savePrinterName('a4', 'HP LaserJet')
    expect(readPrinterName('continuous-241x140')).toBeNull()
    savePrinterName('continuous-241x140', 'EPSON LQ-300K')
    expect(readPrinterName('a4')).toBe('HP LaserJet')
    expect(readPrinterName('continuous-241x140')).toBe('EPSON LQ-300K')
  })

  it('④ 空白名（trim 后为空）⇒ 清掉该纸型的登记，不留空串', () => {
    savePrinterName('a4', 'HP LaserJet')
    savePrinterName('a4', '   ')
    expect(readPrinterName('a4')).toBeNull()
  })

  it('⑤ localStorage 不可用（隐私模式 / 配额满）⇒ 读 null / 写不抛', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })
    expect(() => savePrinterName('a4', 'HP')).not.toThrow()
    spy.mockRestore()
    const getSpy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError')
    })
    expect(readPrinterName('a4')).toBeNull()
    getSpy.mockRestore()
  })
})
