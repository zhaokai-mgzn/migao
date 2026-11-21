// case_ids: BM-014, BM-015
/**
 * **小程序（weapp）不再直连蓝牙标签机**（issue #8939；用户 2026-11-21 逐字「可以理解为都有手持标签机」）
 *
 * ## 这一层从哪来、又为什么反过来
 *
 * #7802（2026-10-26）曾把小程序设成「唯一能在微信内不跳出去打标签的载体」，走 `lpapi-ble-wx`。
 * 但该通道**真机从未验证**（#7802 关闭时自述「小程序侧真机未验，判据全部跑替身」），
 * 而生产早已把出纸迁到**手持标签机**（机身内置打印机，`./terminalTransport` 的终端桥）。
 * ⇒ 用户裁定后通道退役：小程序里不再有「能打」这条路，页面必须**在动手前**给出
 * 「请用手持标签机」的可行动文案（不是打完了才失败，也不是一句「暂不支持」）。
 *
 * ## 判据（每条都能单独变红）
 *
 * | # | 判据 | 红证（怎么让它单独红） |
 * |---|---|---|
 * | W1 | `weapp` ⇒ **不可用**，原因 `weapp-no-printer`，文案点名「手持标签机」 | 把 weapp 分支改回 `ok: true` ⇒ 红 |
 * | W2 | 非 h5 的其它目标（alipay / tt / swan / unknown）仍判 `not-h5`，且**不**共用小程序那条文案 | 让 weapp 落进 `not-h5` ⇒ 红 |
 * | W3 | 判定**先于**安全上下文 / iOS / 终端桥（在小程序里判这些没有意义） | 把 weapp 判定后移 ⇒ 红 |
 * | W4 | 源码面：`lpapiTransport` 不再 `import` `lpapi-ble-wx`；`app.config.ts` 不再声明 `scope.userLocation`；`package.json` 不再依赖该包 | 任一处加回 ⇒ 红 |
 */
import fs from 'fs'
import path from 'path'
import { probePrintCapability, PRINT_FAILURE_HINTS } from '../src/utils/inbound/printCapability'

// 🔴 只读**本模块内**的文件（不跨目录去读仓根）：`tests/unit_ci_workflows/test_local_gate_matrix.py`
// 的「触发面闭合」判据会把跨目录输入当成漏面风险 —— bmini 的判据读 bmini 的文件。
const BMINI = path.resolve(__dirname, '..')
const TRANSPORT_FILE = path.join(BMINI, 'src/utils/inbound/lpapiTransport.ts')
const APP_CONFIG_FILE = path.join(BMINI, 'src/app.config.ts')
const PKG_FILE = path.join(BMINI, 'package.json')

describe('W1 小程序判不可用：出口是「去用手持标签机」', () => {
  it('W1 weapp ⇒ ok:false + weapp-no-printer + 文案点名手持标签机', () => {
    const cap = probePrintCapability({
      platform: 'weapp',
      secureContext: false,
      hasBluetoothApi: false,
    })
    expect(cap.ok).toBe(false)
    expect(cap.reason).toBe('weapp-no-printer')
    // 不可用 ⇒ 不许给「可用时的正向说法」
    expect(cap.readyHint).toBeUndefined()
    expect(cap.hint).toContain('手持标签机')
    // 出口**不是**「换浏览器」：人在小程序里换了浏览器也没有打印机
    expect(cap.hint).not.toMatch(/Chrome/)
  })

  it('W1 与 not-h5 是两条文案（合并即红，与 D3 同口径）', () => {
    expect(PRINT_FAILURE_HINTS['weapp-no-printer']).not.toBe(PRINT_FAILURE_HINTS['not-h5'])
    expect(PRINT_FAILURE_HINTS['weapp-no-printer'].length).toBeGreaterThan(10)
  })
})

describe('W2 别的编译目标不许跟着变', () => {
  it('W2 alipay / tt / swan / unknown 仍判 not-h5', () => {
    for (const platform of ['alipay', 'tt', 'swan', 'unknown']) {
      const cap = probePrintCapability({ platform, secureContext: true, hasBluetoothApi: true })
      expect({ platform, ok: cap.ok }).toEqual({ platform, ok: false })
      expect(cap.reason).toBe('not-h5')
    }
  })

  it('W2 not-h5 文案不再提「小程序」（它会打到支付宝等目标的用户脸上）', () => {
    expect(PRINT_FAILURE_HINTS['not-h5']).not.toContain('小程序')
  })
})

describe('W3 判定顺序：weapp 先于安全上下文 / iOS / 终端桥', () => {
  it('W3 小程序 + iOS + 微信 UA + 非 https ⇒ 仍是 weapp-no-printer', () => {
    const cap = probePrintCapability({
      platform: 'weapp',
      secureContext: false,
      hasBluetoothApi: false,
      isIos: true,
      isWechat: true,
    })
    expect(cap.reason).toBe('weapp-no-printer')
  })

  it('W3 小程序 + 终端桥注入 ⇒ 仍按小程序判（不落到手持终端分支）', () => {
    const cap = probePrintCapability({ platform: 'weapp', hasBluetoothApi: false, terminalBridge: true })
    expect(cap.reason).toBe('weapp-no-printer')
  })
})

describe('W4 源码面：退役通道不许留在依赖与配置里', () => {
  const transport = fs.readFileSync(TRANSPORT_FILE, 'utf8')
  const appConfig = fs.readFileSync(APP_CONFIG_FILE, 'utf8')
  const pkg = JSON.parse(fs.readFileSync(PKG_FILE, 'utf8'))

  it('W4 lpapiTransport 只加载浏览器 SDK，不再 import 小程序 SDK', () => {
    expect(transport).not.toMatch(/import\(\s*\/\*[^*]*\*\/\s*'lpapi-ble-wx/)
    expect(transport).not.toContain("'lpapi-ble-wx/lib/index.js'")
    expect(transport).toMatch(/import\(\s*\/\*[^*]*\*\/\s*'lpapi-ble'\s*\)/)
  })

  it('W4 app.config 不再为蓝牙搜索声明位置权限', () => {
    // 注释里**提到**它不算声明（引用 ≠ 使用，§25）⇒ 只认带冒号的真实声明形态
    expect(appConfig).not.toMatch(/'scope\.userLocation'\s*:/)
    expect(appConfig).not.toMatch(/permission:\s*\{/)
  })

  it('W4 package.json 不再依赖 lpapi-ble-wx（浏览器 SDK 仍在）', () => {
    const deps = { ...pkg.dependencies, ...pkg.devDependencies }
    expect(deps['lpapi-ble-wx']).toBeUndefined()
    expect(deps['lpapi-ble']).toBeDefined()
  })
})
