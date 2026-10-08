// case_ids: BM-014, BM-015
/**
 * **打印必留痕 + 前端不自行计数 + 失败逐种文案**（issue #5052 P3/P4；设计 §7.3 / §8.3；
 * 验收判据 4 / 5 / 9）
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | D1 | 送打印的**唯一**入口先调服务端留痕（顺序：render → **recordPrint** → transport） | 交换成 print→record ⇒ 红 |
 * | D2 | 留痕失败 ⇒ **不打印**（不产生无痕打印） | 留痕抛错仍打印 ⇒ 红 |
 * | D3 | 能力不可用 ⇒ **既不调服务端也不连蓝牙**（动手前就说清） | 先连再判 ⇒ 红 |
 * | D4 | 计数**原样转发**服务端回执（两次不同读数 ⇒ 两次都原样，不做本地 +1） | 本地 +1 ⇒ 红 |
 * | D5 | 失败文案**逐种不同且可行动**（合并成一句通用文案 ⇒ 红） | 两条相同 ⇒ 红 |
 * | D6 | 台账条目活着：`INBOUND_PRINT_GAP_WIRING` 的键集 == 文案表的键集 | 删一条 ⇒ 红 |
 * | D7 | 🔴 送打印**唯一通道**（调用点级）：全 `src/**` 里 `.print(…)` 只许出现在 `printInboundLabel` 内 | 页面里加一条直连 `createLpapiTransport().print()` ⇒ 红 |
 * | D8 | 🔴 文案不得对**运行期**事实下结论：静态 hint 里不许出现"记没记打印次数"，该事实只由 `printRecorded` 说 | 把文案改回「重打不会重复计数」⇒ 红 |
 * | D9 | 🔴 页面必须**消费** `printRecorded`（`printFailureText(result.hint, result.printRecorded)`） | 页面只上屏静态 hint ⇒ 红 |
 */
import fs from 'fs'
import path from 'path'
import {
  printInboundLabel,
  classifyPrintError,
  LabelTransportError,
  type LabelTransport,
} from '../src/utils/inbound/labelPrint'
import {
  PRINT_COUNT_REPRINT_NOTICE,
  PRINT_FAILURE_HINTS,
  printFailureText,
  probePrintCapability,
  printFailureHint,
  type PrintFailureReason,
} from '../src/utils/inbound/printCapability'
import { LABEL_PRINT_PARAMS, createLpapiTransport } from '../src/utils/inbound/lpapiTransport'
import {
  createPrinterLinkStore,
  isAbnormalPrintable,
  linkStateAfterFailure,
  printerLinkText,
  type PrinterLinkState,
} from '../src/utils/inbound/printerLink'
import { INBOUND_PRINT_GAP_WIRING } from '../src/utils/inbound/gaps'
import { layoutInboundLabel } from '../src/utils/inbound/labelLayout'
import { renderInboundLabel, type RenderedLabel } from '../src/utils/inbound/labelCanvas'
import { stripComments, walk, SRC_DIR } from './helpers/h5PlatformLists'
import { callSites } from './helpers/inboundCallSites'

const REPO_ROOT = path.join(__dirname, '..', '..', '..')

/** `src/**` 全部 `.ts`/`.tsx`（bmini 相对路径 + 源码）—— 调用点级射程用 */
function srcSources(): { file: string; code: string }[] {
  return walk(SRC_DIR, (name) => /\.tsx?$/.test(name)).map((abs) => ({
    file: path.relative(path.join(__dirname, '..'), abs),
    code: fs.readFileSync(abs, 'utf8'),
  }))
}

/**
 * 送打印**唯一通道**的调用点级判定（真判据与注入式红证共用同一份）。
 *
 * 判三件事（射程 = 全 `src/**`，不是只扫 `src/utils/inbound`）：
 * ① `.print(…)` 只许出现在 `src/utils/inbound/labelPrint.ts` 的 `printInboundLabel` **内**；
 * ② `printImageData(` 只许出现在传输层实现 `src/utils/inbound/lpapiTransport.ts`；
 * ③ `createLpapiTransport(` 的每一处调用都必须**喂给 `printInboundLabel`**（不许另起一条通道）。
 */
function printChannelProblems(files: { file: string; code: string }[]): string[] {
  const problems: string[] = []
  const ENTRY = 'src/utils/inbound/labelPrint.ts'
  const TRANSPORT = 'src/utils/inbound/lpapiTransport.ts'
  for (const source of files) {
    const code = stripComments(source.code)
    for (const site of callSites(code, /\.print\s*\(/g)) {
      if (source.file !== ENTRY || site.fn !== 'printInboundLabel') {
        problems.push(
          `${source.file} 的 ${site.fn || '<模块顶层>'}() 里有一处**直连送数据**（.print(…)）—— ` +
            `送打印只许走 printInboundLabel（它先调服务端留痕）`,
        )
      }
    }
    for (const site of callSites(code, /printImageData\s*\(/g)) {
      if (source.file !== TRANSPORT) {
        problems.push(`${source.file} 的 ${site.fn || '<模块顶层>'}() 直接调传输层 API printImageData(…) —— 绕过了送打印入口`)
      }
    }
    for (const site of callSites(code, /createLpapiTransport\s*\(/g, { skipDefinitions: true })) {
      if (!site.span.includes('printInboundLabel(')) {
        problems.push(`${source.file} 的 ${site.fn || '<模块顶层>'}() 造了一条传输通道却**没有**喂给 printInboundLabel —— 第二条第 送打印通道`)
      }
    }
  }
  return problems
}

/**
 * 文案方向判定（D8）：静态文案**不许**对"记没记打印次数"下结论。
 *
 * 理由：`printRecorded` 是**运行期**事实（取消发生在 `recordPrint()` 之后 ⇒ 已留痕），
 * 静态文案表说不了它 —— 说了就必然有一半是错的。历史缺陷（验收 D6）正是：
 * `user-cancelled` 写「重打不会重复计数」、`print-failed` 写「重打会再记一次」，两句相反。
 */
const COUNT_CLAIM = /计数|次数|再记|记一次|不重复/
function printCopyProblems(hints: Record<string, string>): string[] {
  const problems: string[] = []
  for (const [reason, hint] of Object.entries(hints)) {
    if (COUNT_CLAIM.test(hint)) {
      problems.push(`${reason}: 静态文案对「记没记打印次数」下了结论 —— 那是运行期事实（result.printRecorded），静态文案没有资格说`)
    }
    if (/不(会|再|用|需)?\s*重复计数|不再计|不会重复计/.test(hint)) {
      problems.push(`${reason}: 文案与实现相反（「重打不会重复计数」；实现是留痕**无条件原子自增** ⇒ 重打必再记一次）`)
    }
  }
  if (!COUNT_CLAIM.test(PRINT_COUNT_REPRINT_NOTICE)) {
    problems.push('PRINT_COUNT_REPRINT_NOTICE: 没把「已记一次 / 重打会再记一次」说清（运行期事实必须有一句准话）')
  }
  return problems
}

/** D9：页面必须消费 `result.printRecorded`（否则「本次记没记」这个事实没有读者） */
function recordedConsumptionProblems(pages: { file: string; code: string }[]): string[] {
  const problems: string[] = []
  for (const page of pages) {
    const code = stripComments(page.code)
    if (!/printFailureText\(\s*result\.hint\s*,\s*result\.printRecorded\s*\)/.test(code)) {
      problems.push(
        `${page.file}: 打印失败文案没有消费 result.printRecorded（只上屏静态 hint ⇒ 工人看不到"本次已记一次/重打会再记一次"）`,
      )
    }
  }
  return problems
}

function fakeLabel(): RenderedLabel {
  const plan = layoutInboundLabel({ shortCode: 'ABCD2345', productName: '遮光布', quantity: '60.5' })
  return {
    plan,
    canvas: { width: plan.widthPx, height: plan.heightPx, getContext: () => null as any },
    image: { data: new Uint8ClampedArray(plan.widthPx * plan.heightPx * 4), width: plan.widthPx, height: plan.heightPx },
    widthPx: plan.widthPx,
    heightPx: plan.heightPx,
  }
}

const OK_CAPABILITY = probePrintCapability({
  platform: 'h5',
  secureContext: true,
  hasBluetoothApi: true,
  isIos: false,
})

describe('打印通道：必留痕 / 不自行计数 / 逐种文案', () => {
  /**
   * 顺序判定（真判据与注入式红证**共用同一份**，见 `migao-dev-flow` §23.5）：
   * 空 `log`（= 一次都没走到）也算红 —— 这样"被测函数被整体禁用"时本判定必然判红。
   */
  function printOrderProblems(log: string[]): string[] {
    const expected = ['render', 'recordPrint', 'transport']
    if (log.join('>') !== expected.join('>')) {
      return [
        `送打印顺序 = ${log.join(' → ') || '（一次都没走到）'}；` +
          `要求 render → recordPrint → transport（**留痕先于送数据**）`,
      ]
    }
    return []
  }

  /** 跑一次真通道并记录调用序（D1 与它的红证共用） */
  async function runLogged() {
    const log: string[] = []
    const transport: LabelTransport = {
      id: 'fake',
      label: '测试打印机',
      print: async () => {
        log.push('transport')
      },
    }
    const result = await printInboundLabel({
      shortCode: 'ABCD2345',
      capability: OK_CAPABILITY,
      transport,
      render: () => {
        log.push('render')
        return fakeLabel()
      },
      recordPrint: async (code) => {
        log.push('recordPrint')
        return { shortCode: code, printCount: 7 }
      },
    })
    return { log, result }
  }

  it('D1 顺序 = render → recordPrint → transport（留痕**先于**送数据）', async () => {
    const { log, result } = await runLogged()
    expect(log).toEqual(['render', 'recordPrint', 'transport'])
    expect(printOrderProblems(log)).toEqual([])
    expect(result).toEqual({ ok: true, printCount: 7, transportId: 'fake', transportLabel: '测试打印机' })
  })

  it('D1 🔴 红证：把送数据排到留痕之前（"先打出来再说"）⇒ 同一判定必红', async () => {
    // ① 真实现产出的顺序 ⇒ 判定判绿。**这一半让本 case 真的走被测函数**：
    //    把 printInboundLabel 整体禁用（抛错）⇒ 这里拿不到 log ⇒ 本 case 必红（不再是空断言）。
    const { log } = await runLogged()
    expect(printOrderProblems(log)).toEqual([])
    // ② 坏形态作为**同一判定**的入参 ⇒ 必须点名判红
    expect(printOrderProblems(['transport', 'recordPrint', 'render']).join('\n')).toContain('留痕先于送数据')
    // ③ 一次都没走到（= 通道被整体禁用）同样算红 —— 防"没跑也算过"
    expect(printOrderProblems([]).join('\n')).toContain('一次都没走到')
  })

  it('D2 留痕失败 ⇒ 一次都不送数据（不产生无痕打印）', async () => {
    let printed = 0
    const transport: LabelTransport = {
      id: 'fake',
      label: '测试打印机',
      print: async () => {
        printed += 1
      },
    }
    const result = await printInboundLabel({
      shortCode: 'ABCD2345',
      capability: OK_CAPABILITY,
      transport,
      render: fakeLabel,
      recordPrint: async () => {
        throw new Error('网络断了')
      },
    })
    expect(printed).toBe(0)
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.printRecorded).toBe(false)
      expect(result.hint).toContain('留痕')
    }
  })

  it('D3 能力不可用 ⇒ 既不调服务端也不连蓝牙，且给出**原因专属**文案', async () => {
    let recorded = 0
    let printed = 0
    const ios = probePrintCapability({ platform: 'h5', secureContext: true, hasBluetoothApi: false, isIos: true })
    const result = await printInboundLabel({
      shortCode: 'ABCD2345',
      capability: ios,
      transport: {
        id: 'fake',
        label: 'x',
        print: async () => {
          printed += 1
        },
      },
      render: fakeLabel,
      recordPrint: async (code) => {
        recorded += 1
        return { shortCode: code, printCount: 1 }
      },
    })
    expect(recorded).toBe(0)
    expect(printed).toBe(0)
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.reason).toBe('ios-unsupported')
      expect(result.hint).toContain('iPhone')
    }
  })

  it('D3 探测顺序：iOS 优先于「没有蓝牙接口」（否则把人引向"换浏览器"这条走不通的路）', () => {
    const iosNoApi = probePrintCapability({ platform: 'h5', secureContext: true, hasBluetoothApi: false, isIos: true })
    expect(iosNoApi.reason).toBe('ios-unsupported')
    const nonH5 = probePrintCapability({ platform: 'weapp', secureContext: true, hasBluetoothApi: true, isIos: false })
    expect(nonH5.reason).toBe('not-h5')
    const insecure = probePrintCapability({ platform: 'h5', secureContext: false, hasBluetoothApi: true, isIos: false })
    expect(insecure.reason).toBe('insecure-context')
    // `isSecureContext` 缺失（老浏览器）⇒ 按**不安全**处理（fail-closed）
    const unknown = probePrintCapability({ platform: 'h5', hasBluetoothApi: true, isIos: false })
    expect(unknown.reason).toBe('insecure-context')
    const noApi = probePrintCapability({ platform: 'h5', secureContext: true, hasBluetoothApi: false, isIos: false })
    expect(noApi.reason).toBe('no-bluetooth-api')
    // 安卓微信内置浏览器（X5）没有 `navigator.bluetooth` ⇒ **不能**只说"换浏览器"，
    // 要说清**当下这一步**怎么做（右上角 → 在浏览器打开）；iOS 仍优先（iPhone 上换浏览器也不行）
    const wechat = probePrintCapability({
      platform: 'h5',
      secureContext: true,
      hasBluetoothApi: false,
      isIos: false,
      isWechat: true,
    })
    expect(wechat.reason).toBe('wechat-webview')
    expect(wechat.hint).toContain('浏览器打开')
    const wechatIos = probePrintCapability({
      platform: 'h5',
      secureContext: true,
      hasBluetoothApi: false,
      isIos: true,
      isWechat: true,
    })
    expect(wechatIos.reason).toBe('ios-unsupported')
    const ok = probePrintCapability({ platform: 'h5', secureContext: true, hasBluetoothApi: true, isIos: false })
    expect(ok.ok).toBe(true)
    expect(ok.hint).toBe('')
  })

  it('D4 计数取自服务端回执：两次不同读数**原样**转发（本地 +1 立刻露馅）', async () => {
    const transport: LabelTransport = { id: 'fake', label: 'x', print: async () => undefined }
    const first = await printInboundLabel({
      shortCode: 'ABCD2345',
      capability: OK_CAPABILITY,
      transport,
      render: fakeLabel,
      recordPrint: async (code) => ({ shortCode: code, printCount: 7 }),
    })
    const second = await printInboundLabel({
      shortCode: 'ABCD2345',
      capability: OK_CAPABILITY,
      transport,
      render: fakeLabel,
      recordPrint: async (code) => ({ shortCode: code, printCount: 12 }),
    })
    expect(first.ok && first.printCount).toBe(7)
    expect(second.ok && second.printCount).toBe(12)
  })

  it('D4 前端不自行计数（源码面：入库模块里没有对 printCount 的算术）', () => {
    const dir = path.join(REPO_ROOT, 'frontend/bmini-app/src/utils/inbound')
    const offenders: string[] = []
    for (const name of fs.readdirSync(dir)) {
      if (!/\.tsx?$/.test(name)) continue
      const code = fs
        .readFileSync(path.join(dir, name), 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
      if (/printCount\s*(\+\+|[+\-*/]=?)/.test(code) || /(\+\+|--)\s*\w*printCount/.test(code)) {
        offenders.push(name)
      }
    }
    expect(offenders).toEqual([])
  })

  it('D5 失败文案逐种不同、非空、可行动（合并成一句通用文案 ⇒ 红）', () => {
    const entries = Object.entries(PRINT_FAILURE_HINTS) as [PrintFailureReason, string][]
    expect(entries.length).toBeGreaterThanOrEqual(8)
    for (const [reason, hint] of entries) {
      expect(`${reason}:${hint}`.length).toBeGreaterThan(12)
      expect(hint.trim().length).toBeGreaterThanOrEqual(10)
    }
    const values = entries.map(([, hint]) => hint)
    expect(new Set(values).size).toBe(values.length)
    // 逐种文案必须点名各自的**可行动出口**，不能都是一句"打印失败"
    expect(PRINT_FAILURE_HINTS['ios-unsupported']).toMatch(/iPhone|iPad/)
    expect(PRINT_FAILURE_HINTS['insecure-context']).toMatch(/HTTPS/)
    expect(PRINT_FAILURE_HINTS['no-bluetooth-api']).toMatch(/Chrome/)
    // 微信里没有蓝牙接口 ⇒ 出口是「在浏览器打开」（**不是**"换个浏览器" —— 人要的是怎么离开微信）
    expect(PRINT_FAILURE_HINTS['wechat-webview']).toMatch(/浏览器打开/)
    expect(PRINT_FAILURE_HINTS['not-h5']).toMatch(/Chrome|电脑/)
    expect(PRINT_FAILURE_HINTS['user-cancelled']).toMatch(/取消/)
    expect(PRINT_FAILURE_HINTS['connect-failed']).toMatch(/开机|3 米/)
    expect(printFailureHint('render-failed')).toContain('空白标签')
    // 未知原因 ⇒ 回落但**不为空**（空提示 = 静默失败）
    expect(printFailureHint('不存在的原因' as PrintFailureReason).length).toBeGreaterThan(10)
  })

  it('D6 台账条目活着：接线台账的键集 == 文案表的键集（删一条 ⇒ 红）', () => {
    const wired = INBOUND_PRINT_GAP_WIRING.map((item) => item.reason).sort()
    const declared = (Object.keys(PRINT_FAILURE_HINTS) as PrintFailureReason[]).sort()
    expect(wired).toEqual(declared)
    // 每一条都点名了**在哪个文件被引用**，且那个文件真的提到该原因字面量
    for (const item of INBOUND_PRINT_GAP_WIRING) {
      const file = path.join(REPO_ROOT, 'frontend/bmini-app', item.wiredBy)
      expect(fs.existsSync(file)).toBe(true)
      expect(fs.readFileSync(file, 'utf8')).toContain(item.reason)
    }
  })

  it('D5 传输层异常 → 分类（未知一律 print-failed，不吞、不假装）', () => {
    expect(classifyPrintError(new LabelTransportError('user-cancelled'))).toBe('user-cancelled')
    expect(classifyPrintError(new LabelTransportError('connect-failed'))).toBe('connect-failed')
    expect(classifyPrintError(new Error('User cancelled the requestDevice'))).toBe('user-cancelled')
    expect(classifyPrintError(new Error('GATT connect timeout'))).toBe('connect-failed')
    expect(classifyPrintError(new Error('打印头过热')))
      .toBe('print-failed')
  })

  it('送数据失败 ⇒ 回执里要说清「留痕已发生」（重打会再记一次，不能骗工人）', async () => {
    const result = await printInboundLabel({
      shortCode: 'ABCD2345',
      capability: OK_CAPABILITY,
      transport: {
        id: 'fake',
        label: 'x',
        print: async () => {
          throw new LabelTransportError('connect-failed', 'GATT timeout')
        },
      },
      render: fakeLabel,
      recordPrint: async (code) => ({ shortCode: code, printCount: 3 }),
    })
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.reason).toBe('connect-failed')
      expect(result.printRecorded).toBe(true)
      expect(result.hint).toBe(PRINT_FAILURE_HINTS['connect-failed'])
    }
  })

  it('渲染失败 ⇒ 中止且**未**留痕（画不出来就不该占一次计数）', async () => {
    let recorded = 0
    const result = await printInboundLabel({
      shortCode: 'ABCD2345',
      capability: OK_CAPABILITY,
      transport: { id: 'fake', label: 'x', print: async () => undefined },
      render: () => {
        throw new Error('no canvas')
      },
      recordPrint: async (code) => {
        recorded += 1
        return { shortCode: code, printCount: 1 }
      },
    })
    expect(recorded).toBe(0)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.reason).toBe('render-failed')
  })

  it('渲染器与打印通道共用同一份版面（打印用的位图就是预览那份计划）', () => {
    const rendered = renderInboundLabel({ shortCode: 'ABCD2345' }, (w, h) => {
      const ctx = {
        fillStyle: '',
        font: '',
        textBaseline: '',
        fillRect: () => undefined,
        fillText: () => undefined,
        getImageData: (x: number, y: number, w2: number, h2: number) => ({
          data: new Uint8ClampedArray(w2 * h2 * 4),
          width: w2,
          height: h2,
        }),
      }
      return { width: w, height: h, getContext: () => ctx }
    })
    expect(rendered.image.width).toBe(rendered.plan.widthPx)
    expect(rendered.image.height).toBe(rendered.plan.heightPx)
  })

  it('D7 🔴 送打印唯一通道（**调用点级**，射程 = 全 `src/**` 而不是只扫 `src/utils/inbound`）', () => {
    const files = srcSources()
    // 反空跑：射程真的扫到了源码（否则两边都是空集，判据会空转通过）
    expect(files.length).toBeGreaterThanOrEqual(50)
    expect(printChannelProblems(files)).toEqual([])
    // 变异体在**内存里**构造（不改磁盘）：在一个**页面**里加第二条直连送数据的通道（不留痕）
    const directPrint = files.map((source) =>
      source.file === 'src/pages/worker/reprint/index.tsx'
        ? {
            ...source,
            code:
              `${source.code}\nconst __bypass = createLpapiTransport({ lpapi })\n` +
              `await __bypass.print(label, { printCount: 1 })\n`,
          }
        : source,
    )
    const problems = printChannelProblems(directPrint).join('\n')
    expect(problems).toContain('直连送数据')
    expect(problems).toContain('src/pages/worker/reprint/index.tsx')
  })

  it('D7 🔴 造了传输通道却没喂给送打印入口 ⇒ 判红（第二条第 送打印通道）', () => {
    const files = srcSources()
    const orphan = files.map((source) =>
      source.file === 'src/pages/worker/inbound/index.tsx'
        ? { ...source, code: `${source.code}\nconst __orphan = createLpapiTransport({ lpapi })\n` }
        : source,
    )
    expect(printChannelProblems(orphan).join('\n')).toContain('第二条第 送打印通道')
  })

  it('D8 🔴 文案不得对**运行期**事实下结论（"记没记打印次数"只由 printRecorded 说）', () => {
    expect(printCopyProblems(PRINT_FAILURE_HINTS)).toEqual([])
    // 注入：把 D6 修复前的那**一对互相矛盾**的文案喂给**同一判定** ⇒ 必须逐条点名
    const beforeD6 = {
      ...PRINT_FAILURE_HINTS,
      'user-cancelled':
        '已取消选择打印机。请点「选打印机」重新选择 DP30S 后重试（标签未打印，但打印次数已记一次，重打不会重复计数）。',
      'print-failed':
        '打印机已连上但这次没打出来：请检查纸仓是否装好、是否缺纸 / 卡纸，处理好后点「重打」（重打会再记一次打印次数）。',
    }
    const problems = printCopyProblems(beforeD6).join('\n')
    expect(problems).toContain('user-cancelled')
    expect(problems).toContain('print-failed')
    expect(problems).toContain('与实现相反')
  })

  it('D8 🔴 送数据阶段的任何失败 ⇒ **已留痕**，且上屏文案必须说清「重打会再记一次」', async () => {
    const reasons = Object.keys(PRINT_FAILURE_HINTS) as PrintFailureReason[]
    const readings: { reason: string; printRecorded: boolean; says: boolean }[] = []
    for (const reason of reasons) {
      const result = await printInboundLabel({
        shortCode: 'ABCD2345',
        capability: OK_CAPABILITY,
        transport: {
          id: 'fake',
          label: 'x',
          print: async () => {
            throw new LabelTransportError(reason)
          },
        },
        render: fakeLabel,
        recordPrint: async (code) => ({ shortCode: code, printCount: 3 }),
      })
      expect(result.ok).toBe(false)
      if (result.ok) continue
      const text = printFailureText(result.hint, result.printRecorded)
      readings.push({ reason, printRecorded: result.printRecorded, says: text.includes(PRINT_COUNT_REPRINT_NOTICE) })
    }
    expect(readings).toHaveLength(reasons.length)
    // 逐条：送数据阶段抛的错 ⇒ 留痕一定已经发生，且文案一定把这件事说出口
    expect(readings.filter((r) => !(r.printRecorded && r.says))).toEqual([])
    // 反向：能力不可用（**还没留痕**）⇒ 报告里 printRecorded=false，文案也不许说"已记一次"
    const ios = probePrintCapability({ platform: 'h5', secureContext: true, hasBluetoothApi: false, isIos: true })
    const blocked = await printInboundLabel({
      shortCode: 'ABCD2345',
      capability: ios,
      transport: { id: 'fake', label: 'x', print: async () => undefined },
      render: fakeLabel,
      recordPrint: async (code) => ({ shortCode: code, printCount: 1 }),
    })
    expect(blocked.ok).toBe(false)
    if (!blocked.ok) {
      expect(blocked.printRecorded).toBe(false)
      expect(printFailureText(blocked.hint, blocked.printRecorded)).not.toContain('已记一次')
    }
  })

  it('D9 🔴 两个出标签的页面必须消费 `printRecorded`（否则"本次记没记"没有读者）', () => {
    const pages = srcSources().filter((source) => /pages\/worker\/(inbound|reprint)\/index\.tsx$/.test(source.file))
    expect(pages.map((page) => page.file).sort()).toEqual([
      'src/pages/worker/inbound/index.tsx',
      'src/pages/worker/reprint/index.tsx',
    ])
    expect(recordedConsumptionProblems(pages)).toEqual([])
    // 注入：页面退回"只上屏静态 hint" ⇒ 同一判定必须点名
    const reverted = pages.map((page) => ({
      ...page,
      code: page.code.replace(/printFailureText\(\s*result\.hint\s*,\s*result\.printRecorded\s*\)/g, 'result.hint'),
    }))
    const problems = recordedConsumptionProblems(reverted).join('\n')
    expect(problems).toContain('没有消费 result.printRecorded')
    expect(problems).toContain('src/pages/worker/inbound/index.tsx')
  })
})

/** D10：页面必须**订阅并渲染**连接状态（真判据与注入式红证共用同一份） */
function linkConsumptionProblems(pages: { file: string; code: string }[]): string[] {
  const problems: string[] = []
  for (const page of pages) {
    const code = stripComments(page.code)
    if (!/printerLink\.subscribe\(/.test(code)) {
      problems.push(`${page.file}: 没有订阅 printerLink —— 连接状态会永远停在打开页面那一刻`)
    }
    if (!/printerLinkText\(/.test(code)) {
      problems.push(`${page.file}: 没有渲染 printerLinkText(...) —— 工人看不到打印机连没连上`)
    }
  }
  return problems
}

/**
 * 打印机**连接状态**（issue #5052 CP-1；2026-09-29 用户要求「提示用户是否已连接打印机」）
 *
 * 它是**运行期事实**（与 `./printCapability` 的能力探测**是两件事**）：能打 ≠ 已连上
 * （机器可能没开机）。判据三件：① 四态文案各自可行动；② `unselected`（还没选过）**不许**说成故障；
 * ③ 两个出标签的页面**订阅并渲染**它。浏览器侧的持续真值**做不到**（Web Bluetooth 权限模型
 * 不允许静默重连）⇒ 口径 = 「最后一次真实交互的读数」，文案里明写，不谎报"持续在线"。
 */
describe('打印机连接状态（DP235S）', () => {
  it('D10 四态文案两两不同、各有可行动出口', () => {
    const texts = (['unselected', 'connecting', 'connected', 'disconnected'] as const).map((status) =>
      printerLinkText({ status }),
    )
    expect(new Set(texts).size).toBe(4)
    for (const text of texts) expect(text.trim().length).toBeGreaterThanOrEqual(10)
    // 🔴「还没选过」不许说成"断开/失败"（那是故障感：会把人引去排障一个不存在的问题）
    expect(printerLinkText({ status: 'unselected' })).not.toMatch(/断开|失败|未连上/)
    expect(printerLinkText({ status: 'disconnected' })).toMatch(/3 米|开机/)
    expect(printerLinkText({ status: 'connected', deviceName: 'DP235S-1234' })).toContain('DP235S-1234')
    // 机器自检提示必须被带出来，否则「已连接」会掩盖「打不出来」
    expect(printerLinkText({ status: 'connected', warning: '未检测到纸张' })).toContain('未检测到纸张')
  })

  it('D10 状态仓：`set` 通知订阅者，退订后不再收到（页面订阅的就是它）', () => {
    const store = createPrinterLinkStore()
    const seen: string[] = []
    const off = store.subscribe((state) => seen.push(state.status))
    store.set({ status: 'connecting' })
    store.set({ status: 'connected', deviceName: 'DP235S' })
    off()
    store.set({ status: 'disconnected' })
    expect(seen).toEqual(['connecting', 'connected'])
    expect(store.get().status).toBe('disconnected')
    store.reset()
    expect(store.get().status).toBe('unselected')
  })

  it('D10 🔴 「打不出来」≠「没连上」：打印失败仍算已连接，取消不冒充断开', () => {
    const connected: PrinterLinkState = { status: 'connected', deviceName: 'DP235S' }
    // 送数据失败（缺纸 / 开盖 / 过热）⇒ 仍是已连接（异常交给自检提示说）
    expect(linkStateAfterFailure('print-failed', connected, 'DP235S').status).toBe('connected')
    // 用户点取消 / SDK 没起来 ⇒ **没有产生关于打印机的信息** ⇒ 保持原读数，不冒充"断开"
    expect(linkStateAfterFailure('user-cancelled', connected).status).toBe('connected')
    expect(linkStateAfterFailure('sdk-unavailable', connected).status).toBe('connected')
    expect(linkStateAfterFailure('user-cancelled', { status: 'unselected' }).status).toBe('unselected')
    // 连不上 ⇒ 未连上（这才是该让人去排障的那一种）
    expect(linkStateAfterFailure('connect-failed', connected, 'DP235S').status).toBe('disconnected')
  })

  it('D10 机器自检态的口径：`LPA_Printable` ≥ 20 才算异常（不抄整张表）', () => {
    // 0/1/2/10/11/12 = 可打印 / 正在打印 / 马达转动 / 无任务 / 页面未收完 / 任务被取消 ⇒ 正常或瞬时
    for (const code of [0, 1, 2, 10, 11, 12]) expect(isAbnormalPrintable(code)).toBe(false)
    for (const code of [20, 30, 33, 34, 35, 50]) expect(isAbnormalPrintable(code)).toBe(true)
    // 取不到 ⇒ 不冒充异常（宁可不提示，也不编一句"打印机异常"）
    expect(isAbnormalPrintable(undefined)).toBe(false)
    expect(isAbnormalPrintable(null)).toBe(false)
  })

  it('D10 🔴 两个出标签的页面必须**订阅并渲染**连接状态（只渲染不订阅 ⇒ 状态停在打开页面那一刻）', () => {
    const pages = srcSources().filter((source) => /pages\/worker\/(inbound|reprint)\/index\.tsx$/.test(source.file))
    expect(pages.map((page) => page.file).sort()).toEqual([
      'src/pages/worker/inbound/index.tsx',
      'src/pages/worker/reprint/index.tsx',
    ])
    expect(linkConsumptionProblems(pages)).toEqual([])
    // 注入式红证：把订阅删掉 ⇒ 同一判定必须点名
    const reverted = pages.map((page) => ({
      ...page,
      code: page.code.replace(/printerLink\.subscribe\(/g, '__gone('),
    }))
    const problems = linkConsumptionProblems(reverted).join('\n')
    expect(problems).toContain('没有订阅')
    expect(problems).toContain('src/pages/worker/inbound/index.tsx')
  })
})

/**
 * 🔴 **真实 SDK 回执包络的判据**（issue #5052 CP-1，2026-09-29）
 *
 * 为什么单独成块：本文件上面所有替身喂的都是**自造包络**（`{success}` / `{code}`），而
 * `lpapi-ble@1.7.260618` 的**真实**包络是 `{statusCode, resultInfo}` / `{statusCode, errMsg}`
 * （实测 `libs/index.umd.js` 的 `success()` / `complete()` / `onResult({statusCode, errMsg})`）。
 * 替身对替身 ⇒ 传输层的错误判定**可以是空的**而判据全绿 —— 这正是本块要钉住的形态。
 */
describe('打印通道：真实 SDK 回执包络（statusCode）', () => {
  const LPA = { OK: 0, CANCEL: 25, UN_SUPPORTED: 19 } as const

  function fakeLpapi(env: {
    requestDevice?: unknown
    openPrinter?: unknown
    printImageData?: unknown
    printerInfo?: unknown
  }) {
    const calls = {
      requestDevice: 0,
      openPrinter: 0,
      printImageData: 0,
      options: {} as Record<string, unknown>,
      initOptions: {} as Record<string, unknown>,
      /** `openPrinter` 的入参 —— 空参是**真机实测**过的失败形态（issue #6439），必须能断言到 */
      openPrinterOptions: undefined as unknown,
    }
    const printer = {
      async requestDevice() {
        calls.requestDevice += 1
        return env.requestDevice ?? { statusCode: LPA.OK, resultInfo: [] }
      },
      async openPrinter(options?: unknown) {
        calls.openPrinter += 1
        calls.openPrinterOptions = options
        return env.openPrinter ?? { statusCode: LPA.OK }
      },
      async printImageData(options: Record<string, unknown>) {
        calls.printImageData += 1
        calls.options = options
        return env.printImageData ?? { statusCode: LPA.OK }
      },
      getPrinterInfo: () => env.printerInfo,
    }
    return {
      calls,
      module: {
        getInstance: (options?: Record<string, unknown>) => {
          calls.initOptions = options || {}
          return printer
        },
        // 厂商静态表（实测挂在导出的 LPAPI 类上）
        getPrintableMessage: (code: number) => `厂商文案-${code}`,
      },
    }
  }

  it('🔴 用户点取消（`{statusCode: 25}`，**resolve 回来**）⇒ user-cancelled，且不再试连接', async () => {
    const fake = fakeLpapi({ requestDevice: { statusCode: LPA.CANCEL, resultInfo: [] } })
    const transport = createLpapiTransport({ lpapi: fake.module, link: createPrinterLinkStore() })
    await expect(transport.print(fakeLabel(), { printCount: 1 })).rejects.toMatchObject({
      reason: 'user-cancelled',
    })
    expect(fake.calls.openPrinter).toBe(0)
    expect(fake.calls.printImageData).toBe(0)
  })

  it('🔴 `openPrinter` 必须显式喂设备 + 关掉 autoScan（issue #6439 真机实测）', async () => {
    // 真机读数（2026-10-06，本机 DP235S / Chrome 153）：空参 ⇒ SDK 走自己的 `searchPrinter()`
    // 重扫，而 Web Bluetooth 没有用户手势扫不了 ⇒ 恒回 `ERROR_NO_PRINTER`「未搜索到到打印机设备！」。
    // 红证：把入参改回空（`api.openPrinter()`）⇒ 本条的 toEqual 必红。
    const fake = fakeLpapi({
      requestDevice: { statusCode: LPA.OK, resultInfo: [{ name: 'DP235S-Y608220585', deviceId: 'dev-9' }] },
    })
    const transport = createLpapiTransport({ lpapi: fake.module, link: createPrinterLinkStore() })
    await transport.print(fakeLabel(), { printCount: 1 })
    expect(fake.calls.openPrinterOptions).toEqual({
      name: 'DP235S-Y608220585',
      deviceId: 'dev-9',
      checkDeviceName: false,
      autoScan: false,
    })
  })

  it('🔴 旧判定（查 `success`/`result`/`code`）对真实包络**恒判通过** —— 这正是当年漏掉取消的原因', () => {
    // 与历史实现同源的口径，**在内存里**复现：它拿到取消回执却认为一切正常
    const legacyLooksOk = (res: any) =>
      !(res?.success === false || res?.result === false || (typeof res?.code === 'number' && res.code !== 0))
    expect(legacyLooksOk({ statusCode: LPA.CANCEL, resultInfo: [] })).toBe(true)
    expect(legacyLooksOk({ statusCode: LPA.UN_SUPPORTED, resultInfo: '当前环境不支持 WebBluetooth 功能！' })).toBe(
      true,
    )
    // 现口径：同一份回执必须被认出来（否则上面那条"红证"只是空断言）
    expect({ statusCode: LPA.CANCEL }.statusCode).not.toBe(LPA.OK)
  })

  it('环境不支持（`{statusCode: 19}`）⇒ sdk-unavailable（不是"打印机没开机"）', async () => {
    const fake = fakeLpapi({
      requestDevice: { statusCode: LPA.UN_SUPPORTED, resultInfo: '当前环境不支持 WebBluetooth 功能！' },
    })
    const transport = createLpapiTransport({ lpapi: fake.module, link: createPrinterLinkStore() })
    const error: any = await transport.print(fakeLabel(), { printCount: 1 }).then(
      () => null,
      (e) => e,
    )
    expect(error?.reason).toBe('sdk-unavailable')
  })

  it('成功路径（`{statusCode: 0}`）⇒ 1:1 送点阵 + 带齐打印参数 + 状态置已连接', async () => {
    const fake = fakeLpapi({ printerInfo: { printable: 0 } })
    const store = createPrinterLinkStore()
    const transport = createLpapiTransport({ lpapi: fake.module, link: store })
    const plan = fakeLabel()
    await transport.print(plan, { printCount: 7 })
    expect(fake.calls.printImageData).toBe(1)
    const sent = fake.calls.options
    expect(sent.width).toBe(plan.widthPx)
    expect(sent.height).toBe(plan.heightPx)
    expect(sent.copies).toBe(1)
    expect(sent.gapType).toBe(LABEL_PRINT_PARAMS.gapType)
    expect(sent.gapLength).toBe(LABEL_PRINT_PARAMS.gapLength)
    expect(sent.orientation).toBe(LABEL_PRINT_PARAMS.orientation)
    expect(store.get().status).toBe('connected')
    expect(store.get().warning).toBe('')
  })

  it('🔴 缺纸（`printable = 35`）⇒ 状态仍是**已连接**，但把厂商自检文案带出来', async () => {
    const fake = fakeLpapi({ printerInfo: { printable: 35 } })
    const store = createPrinterLinkStore()
    const transport = createLpapiTransport({ lpapi: fake.module, link: store })
    await transport.print(fakeLabel(), { printCount: 1 })
    expect(store.get().status).toBe('connected')
    expect(store.get().warning).toBe('厂商文案-35')
    expect(printerLinkText(store.get())).toContain('厂商文案-35')
  })

  it('🔴 不锁型号：`getInstance` 不传 `models`（实机 DP235S ≠ 当时写死的 DP30S）', async () => {
    const fake = fakeLpapi({})
    const transport = createLpapiTransport({ lpapi: fake.module, link: createPrinterLinkStore() })
    await transport.print(fakeLabel(), { printCount: 1 })
    expect(fake.calls.initOptions).not.toHaveProperty('models')
    expect(fake.calls.initOptions.webBLE).toBe(true)
  })

  it('🔴 打印参数值本身钉住（改一个数 ⇒ 红）：不干胶=间隙纸 2 / 间隔 3mm / 不旋转', () => {
    expect(LABEL_PRINT_PARAMS.gapType).toBe(2)
    expect(LABEL_PRINT_PARAMS.gapLength).toBe(3)
    expect(LABEL_PRINT_PARAMS.orientation).toBe(0)
  })
})
