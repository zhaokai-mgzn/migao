// case_ids: UI-063, UI-128
// @vitest-environment jsdom

import { describe, it, expect } from 'vitest'
import matrix from '@/lib/print-media.json'
import {
  BROWSER_CHROME_MARGIN_MM,
  PRINT_MEDIA_IDS,
  PRINT_MEDIA_SPECS,
  browserChromeMarginProblems,
  isContinuousFeed,
  printBodyFontPt,
  printContentInsetCss,
  printContentInsetMm,
  printMediaSpec,
  printPageBoxMm,
  printPageRule,
  printUsableBoxMm,
  printUsableHeightMm,
  type PrintMediaSpec,
} from '@/lib/print-media'

/**
 * 打印**介质矩阵**（issue #5651）—— 介质是**参数**，不是复制粘贴出来的页面。
 *
 * 断言的是**矩阵本身的机器可判形态**（真值源 = `src/lib/print-media.json`）：
 * ① id 字面量清单与 JSON 的 id 集**逐字一致**（只改一边 ⇒ 红：否则新增介质会
 *    「矩阵里有、类型上没有」，调用方只能 `as any` 绕过类型）；
 * ② 每种介质的 `@page` 规则由 `printPageRule()` **唯一生成**（单据不得自写 `@page size`）；
 * ③ **三联纸的待实测登记必须存在**（用户 2026-09-26 裁定 241mm × 140mm 两等分；
 *    真机参数本机拿不到 ⇒ 通用参数 + 显式登记，**不编造精确值**）；
 * ④ 连续走纸的单联可用高度算得出来（= 页长 − 上下边距）—— 它是「不许跨联」的版面预算。
 *
 * ⚠️ 判据只读矩阵与纯函数，不读组件：组件侧的「切介质不产生第二份映射」由
 * `tests/unit/components/SalesDoc.test.tsx` + `tests/unit_ci_workflows/test_print_media_matrix_guard.py` 判。
 */
describe('打印介质矩阵（issue #5651）', () => {
  it('① id 字面量清单与 JSON 的 id 集逐字一致（只改一边 ⇒ 红）', () => {
    const fromJson = matrix.media.map((m) => m.id).sort()
    expect([...PRINT_MEDIA_IDS].sort()).toEqual(fromJson)
    // 反空跑：矩阵被清空/缩到 <3 ⇒ 本判据会空跑通过
    expect(fromJson.length).toBeGreaterThanOrEqual(3)
  })

  it('② 四种介质都在册，且技术/复写/连续走纸口径与 issue #5651 的矩阵表一致', () => {
    expect(matrix.media.map((m) => m.id)).toEqual([
      'a4',
      'label-50x60',
      'label-30x40',
      'continuous-241x140',
    ])
    const a4 = printMediaSpec('a4')
    expect(a4.technology).toBe('laser-inkjet')
    expect(a4.continuousFeed).toBe(false)
    expect(a4.carbonCopies).toBe(1)
    const label = printMediaSpec('label-50x60')
    expect(label.technology).toBe('thermal-transfer')
    expect(label.pageSize).toBe('50mm 60mm')
    // 入库标签 30×40（issue #5052 CP-1，2026-09-29 用户裁定改竖版）：纸型 + 点阵口径同源在矩阵里，
    // **待实测**（真机参数未核实）
    const inbound = printMediaSpec('label-30x40')
    expect(inbound.pageSize).toBe('30mm 40mm')
    expect(inbound.measurement).toBe('pending-field-measurement')
    expect(inbound.pendingMeasurements.length).toBeGreaterThanOrEqual(3)
    expect(inbound.dotGeometry?.dpi).toBe(203)
    // 🔴 逐值一致性用**派生关系**断言（`8 dots/mm × 30mm = 纸宽像素`），不在这里再抄一份
    //    240/320/384 字面量 —— 那会变成「同一物理口径的第二份字面量」（bmini 侧的守卫会判红）
    const dots = inbound.dotGeometry?.dotsPerMm as number
    expect(dots).toBe(8)
    expect(inbound.dotGeometry?.widthPx).toBe(dots * 30)
    expect(inbound.dotGeometry?.heightPx).toBe(dots * 40)
    expect(inbound.dotGeometry?.headWidthPx).toBe(dots * 48)
    // 有效打宽 = min(纸宽, 打印头宽)：30mm 纸 < 48mm 头 ⇒ 整幅可打
    expect(inbound.dotGeometry?.effectiveWidthPx).toBe(dots * 30)
    const tri = printMediaSpec('continuous-241x140')
    expect(tri.technology).toBe('dot-matrix')
    expect(tri.continuousFeed).toBe(true)
    // 🔴 复写是**纸**的特性：一次打印即复写三份 ⇒ 软件只渲染一页（见 SalesDoc 的 DOM 判据）
    expect(tri.carbonCopies).toBe(3)
  })

  it('③ @page 规则由 printPageRule 唯一生成（三联纸 = 241mm 140mm，用户 2026-09-26 裁定）', () => {
    // issue #7309：A4 的 `@page` 边距**必须是 0** —— 浏览器（Chrome）把自己的页眉页脚
    // （版式日期 / 文档标题 / 页面 URL / 页码）画在 `@page` 的页边距里，够大就照画
    // （实测阈值见 `BROWSER_CHROME_MARGIN_MM`）；0 边距 = 没有可画的边距 = 必然不出。
    // 版面内缩（12mm）改由单据容器 padding 承担，见 ⑤ 那一组。
    expect(printPageRule('a4')).toBe('@page { size: A4; margin: 0; }')
    expect(printPageRule('label-50x60')).toBe('@page { size: 50mm 60mm; margin: 0; }')
    expect(printPageRule('continuous-241x140')).toBe('@page { size: 241mm 140mm; margin: 6mm 12mm; }')
  })

  it('未知介质直接抛错（静默回落 = 把三联纸打成 A4 而不出声）', () => {
    // @ts-expect-error 故意传非法 id：必须抛，不许静默回落
    expect(() => printPageRule('a3')).toThrow(/未知打印介质/)
  })

  it('🔴 ③ 三联纸的**待实测**登记必须存在（红证：删掉 pendingMeasurements ⇒ 必红）', () => {
    const tri = printMediaSpec('continuous-241x140')
    expect(tri.measurement).toBe('pending-field-measurement')
    // 真机参数（走纸长度 / 边距 / 每行行高 / 最小字号）本机拿不到 ⇒ 逐项登记，不许留白
    expect(tri.pendingMeasurements.length).toBeGreaterThanOrEqual(3)
    for (const item of tri.pendingMeasurements) {
      expect(item.trim().length).toBeGreaterThan(5)
    }
    const joined = tri.pendingMeasurements.join('\n')
    for (const keyword of ['走纸长度', '边距', '行高', '字号']) {
      expect(joined).toContain(keyword)
    }
    // 有实测读数的介质则**不许**留待实测项（否则「待实测」会退化成永久标签）
    for (const id of ['a4', 'label-50x60'] as const) {
      expect(printMediaSpec(id).measurement).toBe('measured')
      expect(printMediaSpec(id).pendingMeasurements).toEqual([])
    }
  })

  it('④ 判据可红：删掉待实测登记 / 写坏 pageSize ⇒ 同一个判定函数必须判红', () => {
    /** 与守卫同口径的最小判定（注入式红证用；真实判定在 test_print_media_matrix_guard.py） */
    const problems = (spec: PrintMediaSpec): string[] => {
      const out: string[] = []
      if (spec.measurement !== 'measured' && spec.pendingMeasurements.length === 0) {
        out.push(`${spec.id}: 待实测介质没有登记待实测清单`)
      }
      if (!/^(A4|[0-9.]+mm( [0-9.]+mm)?)$/.test(spec.pageSize)) {
        out.push(`${spec.id}: pageSize 不是合法 CSS 尺寸：${spec.pageSize}`)
      }
      return out
    }
    const real = structuredClone(PRINT_MEDIA_SPECS['continuous-241x140']) as PrintMediaSpec
    expect(problems(real)).toEqual([])
    const noRegistry: PrintMediaSpec = { ...real, pendingMeasurements: [] }
    expect(problems(noRegistry)).not.toEqual([]) // 删掉登记 ⇒ 红
    const badSize: PrintMediaSpec = { ...real, pageSize: '241 x 140' }
    expect(problems(badSize)).not.toEqual([]) // 写坏纸型 ⇒ 红
  })

  it('④ 单联可用高度 = 页长 − 上下边距（连续纸「不许跨联」的版面预算）', () => {
    expect(printUsableHeightMm('continuous-241x140')).toBe(128)
    // 纸的整幅 mm 尺寸 = 矩阵的 `pageBoxMm`（`pageSize` 是 CSS 值，`A4` 解析不出 mm）
    expect(printPageBoxMm('a4')).toEqual({ widthMm: 210, heightMm: 297 })
    expect(printPageBoxMm('continuous-241x140')).toEqual({ widthMm: 241, heightMm: 140 })
    expect(printPageBoxMm('label-50x60')).toEqual({ widthMm: 50, heightMm: 60 })
    expect(printUsableHeightMm('a4')).toBe(273) // 297 − 12×2（命名纸型不再返回 null）
    expect(printUsableHeightMm('label-50x60')).toBe(60) // 标签无边距
    expect(printContentInsetMm('continuous-241x140')).toEqual({ xMm: 12, yMm: 6 })
    expect(printUsableBoxMm('continuous-241x140')).toEqual({ widthMm: 217, heightMm: 128 })
    expect(isContinuousFeed('continuous-241x140')).toBe(true)
    expect(isContinuousFeed('a4')).toBe(false)
    // 针打**不复用** A4 的字号预算（A4 的 6pt 量级在针打上会糊）
    expect(printBodyFontPt('continuous-241x140')).toBeGreaterThanOrEqual(printBodyFontPt('label-50x60'))
  })

  it('⑤ 纸面不带**浏览器页眉页脚**：A4 的 @page 边距为 0，版面内缩改由单据容器承担（issue #7309）', () => {
    // 用户 2026-10-19 逐字「我建议拿掉打印的页头和页脚」（附打印成品截图：顶部 `2026/10/19 10:52` +
    // `观星台 - AI经营管理平台`，底部订单 URL + `1/1`）—— 那四样**都不是我们画的内容**，
    // 是 Chrome 的打印页眉页脚。
    expect(printPageRule('a4')).toBe('@page { size: A4; margin: 0; }')
    // 版面内缩是**真值**（12mm）：改由单据容器 padding 承担，纸面观感与改前逐毫米一致
    expect(printContentInsetCss('a4')).toBe('12mm')
    expect(printContentInsetMm('a4')).toEqual({ xMm: 12, yMm: 12 })
    // 🔴 可用版面与改前**逐值不变**（210−24 × 297−24）：抑制页眉页脚**不许**动版面，
    // 也不许动纸面自检的判据面（`PrintDocPreview` 读的就是这两个函数）
    expect(printUsableBoxMm('a4')).toEqual({ widthMm: 186, heightMm: 273 })
    // 页边距本就在阈值以下的介质**不许**被顺手改（销售单三联纸 6mm / 标签 0）
    expect(printContentInsetCss('continuous-241x140')).toBe('0')
    expect(printContentInsetCss('label-50x60')).toBe('0')
  })

  it('⑤ 类级元守卫：矩阵里任何介质都不许落进「浏览器会画页眉页脚」的页边距区间', () => {
    const offenders = matrix.media.flatMap((spec) =>
      browserChromeMarginProblems(spec as PrintMediaSpec)
    )
    expect(offenders).toEqual([])
    // 反空跑：扫描面必须真有介质
    expect(matrix.media.length).toBeGreaterThanOrEqual(3)

    // ── 判别力自证（内存注入，不碰真文件）：修前形态必须判红、修后形态必须判绿 ──
    const before: PrintMediaSpec = {
      ...(printMediaSpec('a4') as PrintMediaSpec),
      pageMargin: '12mm',
      contentInset: undefined,
    }
    expect(browserChromeMarginProblems(before).length).toBeGreaterThan(0)
    // ① 页边距 0 但**没登记内缩** ⇒ 内容贴纸边（打印机不可打区会裁掉）⇒ 红
    const noInset: PrintMediaSpec = { ...before, pageMargin: '0' }
    expect(browserChromeMarginProblems(noInset).length).toBeGreaterThan(0)
    // ② 内缩与 @page 边距叠加（双重内缩，版面悄悄变窄）⇒ 红
    const doubled: PrintMediaSpec = {
      ...(printMediaSpec('a4') as PrintMediaSpec),
      pageMargin: '12mm',
      contentInset: '12mm',
    }
    expect(browserChromeMarginProblems(doubled).length).toBeGreaterThan(0)
    // ③ 阈值本身必须**取在实测边界的安全侧**（实测：8.7mm 不画 / 8.8mm 画）
    expect(BROWSER_CHROME_MARGIN_MM).toBeLessThanOrEqual(8.7)
  })
})
