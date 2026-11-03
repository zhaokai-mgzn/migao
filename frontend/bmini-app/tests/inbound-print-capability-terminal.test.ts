// case_ids: MC-156
/**
 * **终端壳打印能力：桥在 ≠ 打印机在**（issue #8310；承接 #8089 的终端打印通道）
 *
 * 病（2026-11-01 真机取证，商米 V2s `Qbao_h2` / Android 11 / 终端壳 1.0.19）：拍照入库页第一行写
 * 「点「打印标签」，由本机打印机直接出纸。」，而同一台机器点打印 ⇒「打印机未连接（需商米内置打印服务）」；
 * `PrinterLink.mode()` = **-1**，设备上只有 `com.sunmi.printer.firmware`，没有 `com.sunmi.printer`
 * 服务、也没有 `/dev` 打印节点 ⇒ **这台机器打不出来，页面却说能打**（工人先拍照、先过账，过账不可逆）。
 *
 * 根因：`probePrintCapability()` 的终端分支**只看壳**（`if (env.terminalBridge) return { ok: true }`），
 * `PrintEnv` 里**没有**打印能力字段 —— 桥证明的是「壳在」，不是「打印机在」。
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | T1 | `printerMode = -1`（确知没有商米打印服务）⇒ **不**报能打、**不**出「直接出纸」那半句 | 退回只看桥 ⇒ 红（改前实测见 PR body） |
 * | T2 | `printerMode > 0`（原生报正向）⇒ **仍**报能打 + 机身内置打印机文案（**负控**：别把功能修没了） | 把判定写成恒 false ⇒ 红 |
 * | T3 | `printerMode` **读不到**（缺省 / 0 / NaN / Infinity）⇒ **判不了**：不说能打、也不冒充「确知没有」 | 写成 `printerMode ?? 1` 或 `\|\| true` ⇒ 红（最容易被写成这个） |
 * | T4 | 类级：终端分支**必须**读 `printerMode`；`PRINT_READY_HINT_TERMINAL` 只许由本模块在 `available` 分支给出 | 把终端分支改回 `if (env.terminalBridge) return { ok: true }` ⇒ 红 |
 * | T5 | 读路径真的接线：`readPrintEnv()` 从原生注入的 `window.__CFG__.printerMode` 取值，非数字按「读不到」 | 摘掉 `readPrintEnv` 的 `printerMode` ⇒ 红 |
 *
 * ⚠️ **边界（照实登记）**：仓外事实 = `window.__CFG__` 由终端仓 `zhaokai-mgzn/migao-terminal` 注入，
 * 截至本条落地**还没有** `printerMode` 字段 ⇒ 真机上现在一律落 `unknown`（fail-closed：不许说能打）。
 * 本判据只钉本仓这一侧（判定 + 文案 + 取值接线），不覆盖原生侧是否真的按 `PrinterLink.mode()` 赋值。
 */
import { readFileSync, readdirSync, statSync } from 'fs'
import { join } from 'path'
import {
  PRINT_FAILURE_HINTS,
  PRINT_READY_HINT_TERMINAL,
  probePrintCapability,
  readPrintEnv,
  terminalPrintState,
  type PrintEnv,
} from '../src/utils/inbound/printCapability'
import { INBOUND_PRINT_GAP_WIRING } from '../src/utils/inbound/gaps'

/** 真机取证的那台机器：壳在、桥在、`PrinterLink.mode()` = -1（没有商米打印服务）。 */
const SUNMI_NO_SERVICE: PrintEnv = {
  platform: 'h5',
  secureContext: true,
  hasBluetoothApi: false,
  terminalBridge: true,
  printerMode: -1,
}

/** 正向读数：原生报的是可用的打印服务模式。 */
const SUNMI_READY: PrintEnv = { ...SUNMI_NO_SERVICE, printerMode: 1 }

describe('T1 终端壳打印能力：printerMode = -1 ⇒ 不许说能打（issue #8310 真机）', () => {
  it('不报能打，且**不**出现「由本机打印机直接出纸」', () => {
    const cap = probePrintCapability(SUNMI_NO_SERVICE)
    expect(cap.ok).toBe(false)
    expect(cap.reason).toBe('terminal-printer-unavailable')
    expect(cap.readyHint).toBeUndefined()
    expect(cap.hint).toBe(PRINT_FAILURE_HINTS['terminal-printer-unavailable'])
    // 病症原句必须消失（只判 ok 不够：改前 ok 为 true，改后若有人把 readyHint 留着仍会误报）
    expect(cap.hint).not.toContain('直接出纸')
    expect(cap.hint).not.toContain(PRINT_READY_HINT_TERMINAL)
  })

  it('文案 = 事实陈述 + 该做什么（电脑端补打 / 找管理员），不责备不催促', () => {
    const hint = PRINT_FAILURE_HINTS['terminal-printer-unavailable']
    expect(hint).toContain('电脑端补打')
    expect(hint).toContain('管理员')
    expect(hint).not.toMatch(/！|!!/)
  })
})

describe('T2 负控：printerMode 正向 ⇒ 仍然报能打（别把功能修没了）', () => {
  it('ok + 机身内置打印机文案（与 #8089 的既有形态一致）', () => {
    const cap = probePrintCapability(SUNMI_READY)
    expect(cap.ok).toBe(true)
    expect(cap.hint).toBe('')
    expect(cap.readyHint).toBe(PRINT_READY_HINT_TERMINAL)
  })

  it('三态判定的方向是单向的：只有正向读数才 available', () => {
    expect(terminalPrintState(1)).toBe('available')
    expect(terminalPrintState(2)).toBe('available')
  })
})

describe('T3 判不了：读不到 printerMode ⇒ unknown（不许当能打，也不许冒充「确知没有」）', () => {
  it.each([
    ['缺省（原生没送）', undefined],
    ['0（语义仓外未定义）', 0],
    ['NaN', Number.NaN],
    ['Infinity', Number.POSITIVE_INFINITY],
  ])('%s ⇒ unknown ⇒ ok:false 且不说能打', (_label, printerMode) => {
    const cap = probePrintCapability({ ...SUNMI_NO_SERVICE, printerMode: printerMode as number })
    expect(cap.ok).toBe(false)
    expect(cap.reason).toBe('terminal-print-unknown')
    expect(cap.readyHint).toBeUndefined()
    expect(cap.hint).toBe(PRINT_FAILURE_HINTS['terminal-print-unknown'])
    expect(cap.hint).not.toContain('直接出纸')
    // 「判不了」与「确知没有」必须分开说（同一个出口，但"为什么"不同 —— 不能合并成一句通用文案）
    expect(cap.hint).not.toBe(PRINT_FAILURE_HINTS['terminal-printer-unavailable'])
  })

  it('三态：负向 unavailable / 缺省未知（`unknown` 不是 `unavailable`，也不是 `available`）', () => {
    expect(terminalPrintState(-1)).toBe('unavailable')
    expect(terminalPrintState(-7)).toBe('unavailable')
    expect(terminalPrintState(undefined)).toBe('unknown')
    expect(terminalPrintState(0)).toBe('unknown')
    expect(terminalPrintState(Number.NaN)).toBe('unknown')
  })
})

describe('T4 类级：终端分支必须读 printerMode；正向文案只许由 available 分支给出', () => {
  const SRC = 'src/utils/inbound/printCapability.ts'
  const code = readFileSync(join(__dirname, '..', SRC), 'utf8')
  const branch = code.slice(
    code.indexOf('if (env.terminalBridge)'),
    code.indexOf("if (env.platform !== 'h5')"),
  )

  it('终端分支消费 printerMode（摘掉 ⇒ 红）：旧形态 `只看壳 ⇒ ok:true` 必须不复存在', () => {
    expect(branch).not.toBe('')
    expect(branch).toContain('terminalPrintState(env.printerMode)')
    expect(branch).toContain('printerMode')
    // 旧形态（病根）逐字形态：桥在就直接返回能打
    expect(branch).not.toMatch(/if \(env\.terminalBridge\) \{\s*return \{ ok: true/)
  })

  it('`PRINT_READY_HINT_TERMINAL` 只许由本模块产出（页面不许自己写死「直接出纸」）', () => {
    // ⚠️ 归一化后再比：**注释里提到**这句话不算上屏（`terminalTransport.ts` 的注释就在讲这条历史缺陷）
    //    —— 本仓被点过名的形态正是「内容扫描分不清引用与使用」（§25）。故先剥注释。
    const sources = walk(join(__dirname, '..', 'src')).filter((rel) => rel !== SRC)
    const offenders = sources.filter((rel) => {
      const code = stripComments(readFileSync(join(__dirname, '..', rel), 'utf8'))
      return code.includes('PRINT_READY_HINT_TERMINAL') || code.includes('由本机打印机直接出纸')
    })
    expect(offenders).toEqual([])
  })

  it('两条新文案都登记在能力缺口台账里（未登记 ⇒ 既有 G5/D6 判据以外本判据也点名）', () => {
    const wired = INBOUND_PRINT_GAP_WIRING.map((item) => item.reason)
    expect(wired).toContain('terminal-printer-unavailable')
    expect(wired).toContain('terminal-print-unknown')
    const hints = Object.keys(PRINT_FAILURE_HINTS).filter((k) => k.startsWith('terminal-'))
    expect(hints.sort()).toEqual(['terminal-print-unknown', 'terminal-printer-unavailable'])
  })
})

describe('T5 读路径接线：readPrintEnv() 从原生注入的 __CFG__.printerMode 取值', () => {
  const w = window as any
  afterEach(() => {
    delete w.__CFG__
  })

  it('原生没送 ⇒ undefined（**不是** 0 / true —— 缺省必须落「判不了」）', () => {
    delete w.__CFG__
    expect(readPrintEnv().printerMode).toBeUndefined()
  })

  it('原生送了数字 ⇒ 原样读到（-1 与正向都读，判定在 terminalPrintState）', () => {
    w.__CFG__ = { printerMode: -1 }
    expect(readPrintEnv().printerMode).toBe(-1)
    w.__CFG__ = { printerMode: 1 }
    expect(readPrintEnv().printerMode).toBe(1)
  })

  it('非数字 / 非有限值 ⇒ 按「读不到」处理（fail-closed，不猜）', () => {
    w.__CFG__ = { printerMode: 'yes' }
    expect(readPrintEnv().printerMode).toBeUndefined()
    w.__CFG__ = { printerMode: Number.NaN }
    expect(readPrintEnv().printerMode).toBeUndefined()
    w.__CFG__ = {}
    expect(readPrintEnv().printerMode).toBeUndefined()
  })

  it('端到端：__CFG__ 注入 -1 ⇒ 探针（读真环境）也不说能打', () => {
    w.__CFG__ = { printerMode: -1 }
    w.chrome = { webview: {} }
    try {
      const cap = probePrintCapability()
      expect(cap.ok).toBe(false)
      expect(cap.readyHint).toBeUndefined()
    } finally {
      delete w.chrome
    }
  })
})

describe('T6 回归控制：其它平台分支一字未动（新判定没漏到 h5 / weapp）', () => {
  it('weapp 仍报能打（小程序 BLE，issue #7802）', () => {
    const cap = probePrintCapability({ platform: 'weapp', hasBluetoothApi: false })
    expect(cap.ok).toBe(true)
  })

  it('h5 + Web Bluetooth 就绪仍报能打', () => {
    const cap = probePrintCapability({
      platform: 'h5',
      secureContext: true,
      hasBluetoothApi: true,
      terminalBridge: false,
    })
    expect(cap.ok).toBe(true)
  })
})

/**
 * 剥掉注释再扫用户可见字面量（**引用 ≠ 使用**，§25）：`terminalTransport.ts` 的注释里就**提到**了
 * 「由本机打印机直接出纸」这句历史缺陷 —— 内容扫描分不清两者，故先剥注释再判。
 * 只处理本仓的两种注释形态（`/* … *​/` 与整行 `//`），够用于这条结构判据。
 */
function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((line) => !line.trim().startsWith('//'))
    .join('\n')
}

/** 递归列出 `src/**` 的仓库相对路径（只看 .ts/.tsx，跳过测试与样式）。 */
function walk(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const abs = join(dir, name)
    if (statSync(abs).isDirectory()) {
      walk(abs, acc)
      continue
    }
    if (!/\.tsx?$/.test(name)) continue
    acc.push(abs.replace(`${join(__dirname, '..')}/`, ''))
  }
  return acc
}
