'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { QRCodeSVG } from 'qrcode.react'
import { printNamedPageRule, printPageBoxMm, printPageRule } from '@/lib/print-media'
import { cn } from '@/lib/utils'
import type { PrintTarget } from '@/lib/print-doc'
// 纸面**内容**的单一真值（issue #6656）：本组件与免驱动直连通道（`lib/label-print/*`）读
// **同一份**有序行清单 —— 两条通道各派生一份字段 = 改一处另一处不红，
// 而那正是「直连打印机打出来的和这里预览的不一样」的根因。
// 取值口径（工艺规格 → `lib/craft-display.ts`、套序 → `groupBySet`）全在这个模块里，本文件不再自己派生。
import {
  WASH_LABEL_COMPANY_SUBTITLE,
  WASH_LABEL_REGULAR_MEDIA,
  washLabelCompanyName,
  washLabelRows,
  washLabelSheets,
  type WashLabelRowKey,
  type WashLabelSheet,
} from '@/lib/wash-label-content'
// 纸面抬头用的企业名（与发货单 / 报价单 / 加工单 / 销售单**同一份**读取口，issue #7219）
import { useCompanyName } from '@/lib/use-company-name'
// 需要「加黑加粗」的行（加工项 = 加工方式行）：与位图通道**同一份**常量（issue #7986 同批）
import { WASH_LABEL_EMPHASIS_ROW_KEYS } from '@/lib/label-print/wash-label-metrics'
import type { ProcessingOrderItem, ProductionPosition } from '@/types'

/**
 * 加工单**水洗唛**（可打印纸面，issue #4964 → 版式历次改判 #5646 / #7776 / **#7816** / **#7948** / **#7960**）
 *
 * ## 历次裁定的沿革（改版别把历史读成"仍然有效"）
 *
 * - 2026-09-26（issue #5646，**逐字原话，勿删**）：「洗水码宽是50，长度根据我们实际需要来定」
 *   ⇒ 纸宽 50mm 固定、长度随字段增加而加长（60mm → 70mm）。
 * - 2026-10-25（issue #7776）：字号 6pt → 9pt、纸长按内容撑开（夹 70~150mm）、件名与算料公式退场。
 * - 2026-10-26（issue #7816）：纸型固定 50×150、正文 12pt、加「褶法」、份数 = 开数、
 *   订单号提到第一行、加工单号/交期/扫码报工/短码退场、二维码底部居中并放大。
 * - **2026-10-26（issue #7833，现行）**：纸面**折行印全文**（去 `truncate` / `line-clamp`）、
 *   虚线标界线（2026-10-26 后续裁定**只留底部**一条）、单号行改印**加工单号（去 `JG-` 前缀）**（17 位订单号退出纸面）、
 *   加工方式**去「加工方式」前缀**并**并入加工费组合项**、不再印「加工类型」（定高买宽/定宽买高）。
 * - **2026-10-27（issue #7948，已被 #7960 取代）**：纸型 50×150 → 50×110（用户逐字「把水洗唛的尺寸改成
 *   50*110，现在偏长了」）；「二维码不能直接沉底，务必和底部留点距离」⇒ 容器 `padding-bottom: 6mm`，
 *   码下沿与底部虚线**恒 ≥ 6mm**（内容再长也压不到虚线上）。
 * - 2026-10-27 晚（issue #7960）：客户要求纸长 **< 120mm**（取 **119mm**）+ 用户「要不字体小一号？」
 *   ⇒ 纸型 **50×110 → 50×119**、正文 **12pt → 11pt**；二维码与底部虚线曾恒 ≥ 6mm。
 * - **2026-10-28（issue #7979，现行）**：「水洗唛还是要调整到50*150，当前是50*120，多的30要添加到顶部和
 *   底部虚线下处各15，顶部需要让最顶端的字体上面留白15」+「二维码紧挨文字排版，当前留白太多，这样尺寸
 *   就能缩小到50*140」⇒ 纸型 **50×119 → 50×140**；**顶部留白 15mm**（最顶端的字 = 抬头首行，距纸边）；
 *   **二维码紧挨正文**（正文末行之下只留 0.5mm 块间距，不再空两行）；**码下沿距底部虚线 15mm**。
 *
 * ## 本版（2026-10-26，issue #7833）用户逐字裁定 —— 一次收齐
 *
 * ⑥ 「JG-20261026-8172 这个加工单有超高倒幅，但是在加工单的各个环节都没有体现出来，打印的
 *    洗水唛中也需要体现加工费组合中的信息」⇒ 加工方式行**并入** `processingItems[].name`
 *    （加工费组合键：韩褶 / 超高 / 超宽 / 倒幅 / 定型 …，取值见 `lib/processing-combo.ts`）；
 * ⑦ 「加工方式这几个字可以移除」⇒ 该行**只印值**（`韩褶 · 超高 · 倒幅 · 双开 · 定型`）；
 * ⑧ 「把定高买宽和定宽买高的工艺规格信息不要展示在洗水唛上」⇒ 不再印「加工类型」；
 * ⑨ 「订单号是否可以短一些…只留加工单号，删掉订单行」⇒ 第一行改印 `单号 JG-…`（订单号不上纸）；
 * ⑩ 「打印后的结果出现了文字缩写…自动去换行打印」+「头尾加下虚线」⇒ 行内**折行印全文**
 *    （无省略号 / 无行数截断）+ 标签上下各一条虚线；**后续裁定（issue #7839）**「水洗唛的顶部虚线移除掉」
 *    ⇒ 只保留**底部**一条（顶部那条去掉）。
 *
 * ## 上一版（2026-10-26，issue #7816）口令（仍然有效的那部分）
 *
 * ① 「水洗唛长度不足，设置为打印50*150」⇒ 纸型曾固定 50mm × 150mm（作废 #7776 的"按内容撑开"）；
 *    🔴 **2026-10-28 起由 140mm 取代**（见上「历次裁定的沿革」最后一条），本条其余口令（份数 / 字号 /
 *    褶法 / 字段面）**仍然有效**；
 * ② 「如果订单是双开的要打印两份，单开的要打印1份，三开打印3份，4开打印4份，这个都要在
 *    打印预览中默认设置好」⇒ **份数 = 打开方式开数**（`washLabelCopies`，两条通道共用）；
 * ③ 「字体还是太小，可以再大一点」⇒ 正文 9pt → **12pt**（抬头 14pt / 副标题 10pt；2026-10-27 晚再收到 11pt，见上「历次裁定的沿革」）；
 * ④ 「要体现出是否采用的韩褶公式以及韩褶的折数，用一个字段表示即可」⇒ 新增 **褶法** 行
 *    （`褶法 韩褶公式 52折` / `褶法 倍数法`，见 `lib/wash-label-content.ts` 的 `washLabelPleats`）；
 * ⑤ 「把订单号放到第一行，客户那一行上面」「移除加工单号」「移除交期字段」
 *    「二维码放到底部居中」「移除扫码报工和短码文字」「二维码可以放大一点」。
 *
 * - **2026-10-28（issue #7986 / #7987）**：「把安装小区和安装位置放置到客户那一行下面」⇒ 这两行
 *   紧跟「客户」；「把加工项信息加黑加粗」⇒ 加工方式行 `font-bold`（位图通道同口径加粗）。
 * - **2026-10-28（issue #8002，专属唛）**：勾了「余料带回 / 绑带」的套**额外**打印水洗唛
 *   （每套每类别 1 张、**不乘开数**）—— 抬头副标题 = `成品定制 · 余料带回`（12pt 加粗）标清
 *   「这张纸是给哪个特殊选项的」；行清单与常规唛**同一份**（`washLabelRows`），追加在常规唛之后。
 *   张数 / 张序 / 副标题统一由 `washLabelSheets` 派生（与免驱动直连通道**同源**）—— 本文件不自己展开。
 *
 * 字段面（从上到下）= **纸面抬头（企业名 / 成品定制；专属唛的第二行为 `成品定制 · 余料带回`）** →
 * **单号（加工单号）** / 客户 /
 * 第 N 套共 M 套 / **帘种** / **货号**（值 = 颜色内容，issue #7872 起文案由「颜色」改「货号」）/
 * 安装小区 / 安装位置 / 门幅 / 用料 / 宽高 / 加工方式（含加工费组合项，无前缀）/
 * 褶法 / 特殊选项 / 备注 / **布料批次（末行，值 = 快照 `batchNo`，issue #7872）**
 * → 底部**居中二维码**（80 CSS px = 21.17mm）。
 * 一行粒度 = 一部位（商品行）**一张 × 开数份**；专属唛 = **每套每类别 1 张**（不乘开数，排在常规唛之后）。
 *
 * - **2026-10-29（issue #8107，专属唛瘦身）**：用户逐字「余料带回和绑带的水洗唛打印功能中，用户反馈
 *   打印的信息太多了，可以适当删减，保留货号，门幅，宽高，工艺和特殊选项 + 二维码即可」
 *   「把长度再缩减一些，能放下以上信息即可」⇒ ① **专属唛只印 5 行 + 二维码**（货号 / 门幅 / 宽高 /
 *   工艺 / 特殊选项；行集合 = `wash-label-content.ts::WASH_LABEL_OPTION_ROW_KEYS`，抬头照旧是
 *   「这张纸属于哪个特殊选项」的标记）；② **专属唛用自己的短纸 50mm × 100mm**
 *   （介质 `label-50x100`；同一次出纸里两种纸高靠 **CSS 命名页** `@page wash-label-option` 并存，
 *   见 `printNamedPageRule`）。🔴 **常规唛一字不改**：50mm × 140mm / 15 行。
 *   ⛔ 退场行（专属唛上不得出现）：单号 / 客户 / 套序 / 帘种 / 安装小区 / 安装位置 / 用料 / 褶法 /
 *   备注 / 布料批次 —— 它们由内容模块的行集合决定，本文件**不自己挑行**（单源守卫 SS9）。
 *
 * 🔴 **退场项（历次字段裁定未选，勿"顺手加回"）**：
 *   ① **工序摘要** —— 工人扫部位码后在 H5 看该部位工序清单（`#4967`），纸面不印；
 *   ② **完整套号**（`JG-…-001`）—— 与加工单号重复，纯占纸面；
 *   ③ **件名（商品名称）与算料公式（褶倍公式）** —— 2026-10-25 用户逐字「移除商品名称展示…
 *      移除褶倍公式字段展示」；
 *   ④ **交期 / 扫码报工 / 人可读短码** —— 2026-10-26 用户逐字（见上 ⑤）。
 *      ⚠️ 短码退场**改变了** `docs/design/worker-h5-scan-and-report.md` §1.4 的"手输降级入口"：
 *      纸面不再提供手输码 ⇒ 扫不出码时只能看屏幕/重新出码（用户裁定，登记在本文件与 CHANGELOG）。
 *   ⑤ **加工类型（定高买宽 / 定宽买高）** —— issue #7833 用户逐字「不要展示在洗水唛上」。
 *      ⚠️ **加工单号**在 #7816 曾退场，issue #7833 起以「单号」行**回到纸面**（它取代了 17 位订单号）——
 *      这是用户 2026-10-26 的**后一次**裁定，不是把 #7816 读错了。
 *
 * ## 纸面几何与垂直预算（实测口径沿用 #4949 / #5646；**2026-10-28 按 140mm 纸型 / 上下各留白 15mm 重算**）
 *
 * 纸型 = **50mm × 140mm**（固定；真值源 = `lib/print-media.json` 的 `label-50x140`，本文件不写第二份）。
 * 容器实测沿 #5646：正文右边界 48.799mm 减 1.2mm 内边距 ⇒ **版心宽 47.6mm**；
 * 140mm 高减**上留白 15mm**（用户 2026-10-28「顶部需要让最顶端的字体上面留白15」）、减**下净空 15mm**
 * （码下沿与底部虚线的空白：「多的30要添加到顶部和底部虚线下处各15」）⇒ **可用 110mm**。
 * 正文 11pt / `line-height 1.2` ⇒ **每行 4.66mm**（4.6567mm；≈ 12.3 个汉字/行；12pt 时代是 11.2 个字）。
 * 逐项预算（满字段 = 15 行：单号 / 客户 / 套序 / 帘种 / 货号 / 安装小区 / 安装位置 / 门幅 / 用料 /
 * 宽高 / 加工方式 / 褶法 / 特殊选项 / 备注 / 布料批次）：
 * 抬头块 **10.16**（14pt 5.93 + 10pt 4.23）+ 行前块距 **0.5** + 正文 15 × 4.6567 ≈ **69.85**
 * + 二维码前块距 **0.5**（紧挨正文，2026-10-28 由「空两行 9.31mm」收到一个块间距）+ 二维码 **21.17**（80 CSS px）
 * ⇒ **102.18mm ≤ 110mm**（余 **7.82mm** ≈ 1.6 行）—— 满字段 15 行装得下且有余量。
 * 🔴 **17 行 ⇒ 111.49mm > 110mm**（溢出 1.49mm）：再多的折行就被裁；
 * 装不下时**只裁文字块**（`min-h-0 overflow-hidden`，先裁尾部补充行），**二维码永不被裁、且离底虚线恒 ≥ 15mm**
 * （`.task-card-label` 的 `padding-bottom: 15mm` 是硬约束）。溢出由「打印预览」的**纸面自检逐张**如实报出
 * 「内容 Xmm > 可用 Ymm（第 N 张）」，**不靠静默裁切掩盖**（同 `SalesDoc` 的 #7715 口径）。
 * 2026-10-28 的用户裁定共同定下这一版：纸型 50×140 + **上下各 15mm 留白** + **二维码紧挨正文**
 * （后者省下的 ≈9mm 正是纸长能从 150mm 收到 140mm 的来源）；再要装折行只能
 * **继续降字号 / 再抬纸长 / 减字段** —— 都是用户裁定项，**不要在本文件里偷偷调**。
 * 🔴 **折行印全文（issue #7833）**：行里**没有** `truncate` / `line-clamp-*`（省略号 = 静默吃掉半截字），
 * 长值（客户 / 部位 / 货号 / 加工方式 / 特殊选项 / 备注 / 布料批次）一律折行。
 *
 * ##### 【专属唛预算】（issue #8107，可复算；守卫 G8~G11 按本节读数复算）
 *
 * 专属唛（`.task-card-label--option`）纸型 = **50mm × 100mm**（真值源 = `label-50x100`；
 * 命名页 = `@page wash-label-option`，由 `printNamedPageRule` 从矩阵取，本文件不写第二份纸型）。
 * 版心宽 47.6mm（= 50 − 2 × 1.2 内边距，与常规唛同宽）；可用 70mm（= 100 − 15 上留白 − 15 下净空）；
 * 每行 4.6567mm（正文 11pt × 行高 1.2）；抬头块 11.01mm（14pt + 12pt，行高 1.2）；
 * 二维码 21.17mm（80 CSS px）、块距 0.5mm × 2。
 * 满字段 5 行 = 11.01 + 0.5 + 5 × 4.6567 + 0.5 + 21.17 = **56.46mm ≤ 70mm**
 * ⇒ 整张 ≈ 15 + 56.46 + 15 = **86.46mm ≤ 100mm**（余 13.54mm ≈ 2.9 行 ⇒ **可容 7 行**：
 * 工艺 / 特殊选项各折一次仍装得下；再多即裁尾部文字，二维码永不被裁且离底虚线恒 15mm）。
 *
 * 打印隔离沿用项目既有范式（见 `frontend/admin-web/src/components/orders/ShipmentDoc.tsx` 文件头的 6 条约束）：
 * 1. **屏幕隐藏、打印可见**：页面已有屏幕布局，本组件 `display:none` + `@media print` 显形；
 * 2. **portal 到 body + display:none 隔离**：`body > *:not(.print-doc) { display:none !important }`
 *    —— display:none 不占版面高度，避免按隐藏内容高度分页打出空白页；
 *    `.task-card-print-area` 必须是 portal 容器本身的 class（不能再包一层），且**必须同时带共享标记类
 *    `print-doc`**（issue #4983，来自 #4965 的实测）：按「自己那一份」写选择器
 *    （`body > *:not(.task-card-print-area)`）会把**兄弟单据也选进来**整份 `display:none` 掉 ——
 *    同一页挂两份打印单据时各自把对方藏掉；共享 `print-doc` 是让「排除所有打印单据」成立的唯一写法。
 *    守卫 = `tests/unit_ci_workflows/test_print_doc_convention_guard.py`；
 * 3. 不得放进 Modal（面板 `max-h` 会裁掉多页明细）；每页只挂一份（全局选择器）；
 * 4. 二维码内容只放**该部位自己的** `scan_url ?? part_token`（token 化、可撤销），
 *    不放单号拼接串、不放加工单级 `qr_token`；**缺码不画假码**（出占位框）；
 * 5. ⚠️ **别把这个水洗唛挪到德佟 DP30S 上打**：DP30S 是 **203dpi 的 2 英寸头**，**有效打印宽度通常只有
 *    48mm（384 dots）** ⇒ **50mm 宽打不满**，右侧约 2mm 打不到（约束登记在 issue #5052「裁定记录 5」）。
 *    本版按用户 2026-09-26 裁定做 50mm —— 水洗唛今天由 admin-web 走 A4/标签打印机出，**不是 DP30S**；
 *    若将来要上 DP30S，必须先改回 ≤48mm 并重算本条的预算账。
 */
interface TaskCardPrintProps {
  /** 加工单号 —— **纸面第一行**（客户之上；issue #7833 起取代 17 位订单号） */
  processingOrderNo?: string
  /** 加工单公共属性：客户名 —— **每张标签都要呈现** */
  customerName?: string
  /** 部位（= 商品行）列表；一个部位按开数出 N 张，码取自该部位自己的 scan_url/part_token */
  positions?: ProductionPosition[]
  /** 缺码时的占位文案（撤销后传「已撤销」，避免纸面指向不存在的按钮）；缺省＝待生成 */
  qrPlaceholderHint?: string
  /** 该部位对应的加工单快照明细（货号/门幅/用料/加工方式/褶法/特殊选项/备注/开数的取值来源） */
  items?: ProcessingOrderItem[]
  /**
   * 本次打印的目标（`'labels'` = 打印本单据）。**必须由调用方置位**：标签的显形规则按
   * `[data-print-target='labels']` 限定 ⇒ 不置位就**不上纸**（issue #5914 的「一次只放一份」）。
   */
  printTarget?: PrintTarget | null
  /**
   * **原地渲染**（`true`）而不是 portal 到 `document.body`（issue #5914）—— 只有**打印预览层**
   * 用它：预览要把**同一份单据**摆进真尺寸纸框里，portal 会让它跑到框外（且屏幕态仍是 `display:none`）。
   * 缺省 `false` = 既有行为（portal 到 body，屏幕上隐藏、仅打印呈现）。
   */
  inline?: boolean
  className?: string
}

/** 行 ⇒ `data-testid` 的中段（与 issue #5646 起的既有 testid 逐字一致，别改名） */
const WASH_LABEL_TESTID_SEGMENT: Record<WashLabelRowKey, string> = {
  docNo: 'doc-no',
  customer: 'customer',
  setNo: 'set-no',
  color: 'color',
  positionKind: 'kind',
  installCommunity: 'install-community',
  installRoom: 'install-room',
  doorWidth: 'door-width',
  meters: 'meters',
  size: 'size',
  craft: 'craft',
  pleats: 'pleats',
  specialOptions: 'special-options',
  remark: 'remark',
  batchNo: 'batch-no',
}

/**
 * 行 ⇒ `data-testid`。
 *
 * 🔴 2026-10-26 起**每张纸都带张序**（份数 = 开数 ⇒ 同一部位会重复出纸）：订单号那行也按张编，
 * 否则两份纸里 `getAllByTestId('task-card-order-no')` 拿不到第二张（判据会静默只覆盖第一张）。
 */
function washLabelRowTestId(key: WashLabelRowKey, index: number): string {
  return `task-card-label-${WASH_LABEL_TESTID_SEGMENT[key]}-${index}`
}

/**
 * 行 ⇒ 本渲染器（CSS）的样式。
 *
 * 🔴 **只在本文件里**决策：折行是**排版**，不进单一真值模块。
 *
 * 🔴 **纸面不许藏字（issue #7833）**：这里**没有** `truncate` / `line-clamp-*` / `text-overflow`
 * —— 用户 2026-10-26 逐字「打印后的结果出现了文字缩写…自动去换行打印」。
 * 长值一律折行（`break-words`）；纯数字行用 `whitespace-nowrap` 只是**不折行**（不藏字）。
 * 守卫 = `tests/unit_ci_workflows/test_print_paper_full_text_guard.py` 的 C4。
 */
const WASH_LABEL_ROW_CLASS: Record<WashLabelRowKey, string> = {
  // 单号（加工单号）是纸上唯一的单据身份 ⇒ 允许折断、绝不省略/裁切
  docNo: 'break-all',
  customer: 'break-words',
  setNo: 'whitespace-nowrap',
  color: 'break-words',
  positionKind: 'break-words',
  installCommunity: 'break-words',
  installRoom: 'break-words',
  doorWidth: 'break-words',
  meters: 'break-words',
  size: 'break-words',
  craft: 'break-words',
  pleats: 'whitespace-nowrap',
  specialOptions: 'break-words',
  remark: 'break-words whitespace-pre-line',
  // 布料批次 = 单据型短码（`PC-20261026-0001`）：折断**不藏字**（长批次号也不许出省略号）
  batchNo: 'break-all',
}

export default function TaskCardPrint({
  processingOrderNo,
  customerName,
  positions,
  qrPlaceholderHint,
  items,
  printTarget,
  inline,
  className,
}: TaskCardPrintProps) {
  // 打印只发生在客户端；SSR/首帧无 document，portal 前先等 mounted
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  // 纸面抬头：与四张 A4/三联纸单据**同一份**读取口（模块级缓存 ⇒ 同页多份只读一次）
  const companyName = washLabelCompanyName(useCompanyName())

  if (!mounted) return null

  const list = positions ?? []

  /**
   * 逐张出纸清单（**单一真值** = `lib/wash-label-content.ts::washLabelSheets`，与免驱动直连通道同一份）：
   * 常规唛 = 部位 × **开数**（2026-10-26 用户裁定「双开打两份…单开打一份」）；
   * 专属唛（余料带回 / 绑带，issue #8002）= **每套每类别 1 张**、不乘开数、追加在常规唛之后。
   *
   * 🔴 本文件**不再自己**按开数展开 —— 展开口径各写一份 ⇒ 两条通道出纸张数会不一样。
   */
  const sheets: WashLabelSheet[] =
    list.length > 0
      ? washLabelSheets({ positions: list, items })
      : // 0 个部位 ⇒ 仍出**一张**显式占位（明确「无商品/无码可打印」），而不是什么都不打
        [
          {
            position: null,
            setNo: 1,
            setCount: 1,
            optionLabel: null,
            variant: 'regular',
            media: WASH_LABEL_REGULAR_MEDIA,
            subtitle: WASH_LABEL_COMPANY_SUBTITLE,
            qrValue: null,
          },
        ]

  // 🔴 纸面**内容与行序**的唯一来源（issue #6656；与免驱动直连通道同一份）：
  // 单号 / 客户 / 套序 / 部位 / 货号 / 门幅 / 用料 / 宽高 / 加工方式 / 褶法 / 特殊选项 / 备注
  // 的取值口径全在 `washLabelRows` 里面 —— 本文件**不再自己派生**（派生两份 = 两条通道会画得不一样）。
  const rowsBySheet = sheets.map((sheet) =>
    sheet.position
      ? washLabelRows({
          position: sheet.position,
          item: sheet.item,
          setNo: sheet.setNo,
          setCount: sheet.setCount,
          customerName,
          processingOrderNo,
          // 🔴 行集合（常规 15 行 / 专属唛 5 行）由内容模块的 `sheet.variant` 决定（issue #8107）——
          // 渲染器自己按 optionLabel 挑行 = 第二份行集合口径（单源守卫 SS9 判红）
          variant: sheet.variant,
        })
      : [],
  )

  const doc = (
    <div
      className={cn('task-card-print-area print-doc text-neutral-900', className)}
      {...(printTarget === 'labels' ? { 'data-print-target': 'labels' } : {})}
    >
      {/* 🔴 纸型规则**只在本次打印目标为本单据时**进文档（issue #5914 的 P1-2）：
          `@page` 是**文档级**规则 —— 同页多份单据并存时**最后声明的那条赢**。 */}
      {printTarget === 'labels' && (
        <>
          <style>{printPageRule('label-50x140')}</style>
          {/* 🔴 专属唛的**命名页**（issue #8107）：同一次出纸里两种纸高并存 ——
              常规唛吃上面那条文档级 `@page`（50mm × 140mm），专属唛吃这条
              `@page wash-label-option`（50mm × 100mm）。尺寸由 `printNamedPageRule` 从介质矩阵取，
              本文件不写第二份纸型（守卫 G9 把命名页与矩阵逐字比对）。 */}
          <style>{printNamedPageRule('wash-label-option', 'label-50x100')}</style>
        </>
      )}
      <style>{`
        .task-card-print-area { display: none; }
        /* 水洗唛本体：固定 50mm × 140mm（issue #7979，2026-10-28 用户裁定），超出一律裁掉（纸面只有这么大）。
           上内边距 15mm = 顶部留白（最顶端的字距纸边 15mm，用户「顶部需要让最顶端的字体上面留白15」）；
           下内边距 15mm = 二维码与底部虚线之间的净空（「多的30要添加到顶部和底部虚线下处各15」）；
           两个 15mm 与画布通道 wash-label-metrics.ts 的 WASH_LABEL_TOP_BLANK_MM /
           WASH_LABEL_BOTTOM_CLEARANCE_MM 同值。
           ⚠️ 这段注释在模板字面量里 ⇒ 不许写 markdown 星号（copy-no-markdown-emphasis 判据会红） */
        .task-card-label { width: 50mm; height: 140mm; overflow: hidden; box-sizing: border-box;
          padding: 15mm 1.2mm 15mm; font-size: 11pt; line-height: 1.2; display: flex; flex-direction: column;
          /* 底部虚线（issue #7833 → #7839）：只标这张纸的下沿（顶部那条按用户裁定移除） */
          border-bottom: 1px dashed #000;
          break-after: page; page-break-after: always; }
        /* 最后一张不再分页（否则末尾多吐一张空白） */
        .task-card-label:last-child { break-after: auto; page-break-after: auto; }
        /* 专属唛（余料带回 / 绑带，issue #8107）：只印 5 行 + 二维码 ⇒ 短纸 50mm × 100mm。
           宽度 / padding / 字号 / 二维码与基类同值（上面那条），只有纸高与命名页不同 ——
           命名页让同一份打印任务里两种纸高并存（尺寸见 printNamedPageRule，本文件不写第二份）。
           ⚠️ 这段注释在模板字面量里 ⇒ 不许写 markdown 星号（copy-no-markdown-emphasis 判据会红） */
        .task-card-label--option { height: 100mm; page: wash-label-option; }
        @media print {
          body > *:not(.print-doc) { display: none !important; }
          /* 🔴 只有「本次目标」上纸（issue #5914）：否则打印会同时吐出别的单据的版面 */
          .task-card-print-area[data-print-target='labels'] {
            display: block;
            position: static;
            width: auto;
          }
          /* 防御：页面其他组件残留的 "body * { visibility: hidden }" 打印隔离
             （如 ProcessingOrderBlock）会连同本组件一起藏掉 —— 显式恢复自身可见 */
          .task-card-print-area, .task-card-print-area * { visibility: visible; }
        }
      `}</style>

      {sheets.map((sheet, sheetIndex) => {
        const { position } = sheet
        const rows = rowsBySheet[sheetIndex] ?? []
        // 该张自己的纸型（issue #8107：常规 50×140 / 专属唛 50×100）——
        // 打印预览的纸面自检按**每张自己的纸高**判溢出，读的就是这里，不用文档级单一 limit
        const paper = printPageBoxMm(sheet.media)

        return (
          <div
            key={`${position?.order_item_id ?? 'label'}-${sheetIndex}`}
            className={cn('task-card-label', sheet.variant === 'option' && 'task-card-label--option')}
            data-print-sheet
            data-sheet-paper-mm={`${paper.widthMm}x${paper.heightMm}`}
            {...(sheet.variant === 'option' ? { 'data-sheet-note': '专属唛' } : {})}
            data-testid={`task-card-label-${sheetIndex}`}
          >
            {/* ① 纸面抬头（用户 2026-10-25 裁定照参考工单「亿家纺织 / 成品定制」的形态）：
                企业名 + 副标题，居中两行。**常规唛**企业名缺值 ⇒ 整块不渲染（纸面是给客户看的，
                不印空行、不印「未设置」）；**专属唛**（issue #8002）的副标题就是「这张纸给哪个特殊
                选项」的标记 ⇒ 企业名缺值也照印。与免驱动直连通道（`lib/label-print/wash-label.ts`
                的 `company` 块）同字号同位置。 */}
            {(companyName !== '' || sheet.optionLabel !== null) && (
              <div className="shrink-0 text-center" data-testid="task-card-company">
                {companyName !== '' && <div className="text-[14pt] font-bold">{companyName}</div>}
                {sheet.optionLabel !== null ? (
                  <div className="text-[12pt] font-bold" data-testid="task-card-option-label">
                    {sheet.subtitle}
                  </div>
                ) : (
                  <div className="text-[10pt] text-neutral-600">{sheet.subtitle}</div>
                )}
              </div>
            )}

            {/* ② 中部文字块（第一行 = **单号**，2026-10-26 用户裁定「放到第一行，客户上面」）。
                🔴 **不再 `flex-1`**（用户 2026-10-26 逐字「二维码不要沉底，跟文字隔两行即可，
                要离底部虚线留空」）：文字块按内容高度收缩，二维码跟在文字后**两行**处；
                改前 `flex-1` 会把二维码顶到纸底、贴着底部虚线。
                🔴 2026-10-27 起「离底留空」是**硬约束**：容器 `padding-bottom: 6mm`（见上方 CSS），
                所以内容再长也只会压缩本块（`overflow-hidden` 裁尾部行），码永远压不到虚线上。
                `data-testid` 是给「纸面内容 = 唯一真值模块」那条判据读**整块逐行文本**用的：
                在本块里内联多写一行（绕过 `washLabelRows`）⇒ 那条判据必红。 */}
            <div
              className="mt-[0.5mm] min-h-0 overflow-hidden"
              data-testid={`task-card-label-rows-${sheetIndex}`}
            >
              {position ? (
                <>
                  {/* 有序行清单（`washLabelRows`）：内容与行序的单一真值，两条打印通道共用。
                      折行 / clamp 由本文件的 `WASH_LABEL_ROW_CLASS` 决定（排版不进真值模块）。 */}
                  {rows.map((row) => (
                    <div
                      key={row.key}
                      className={cn(
                        WASH_LABEL_ROW_CLASS[row.key],
                        // 加工项**加黑加粗**（用户 2026-10-28「把加工项信息加黑加粗」）——
                        // 哪些行加粗由 metrics 的 `WASH_LABEL_EMPHASIS_ROW_KEYS` 决定（两条通道同源）
                        WASH_LABEL_EMPHASIS_ROW_KEYS.includes(row.key) && 'font-bold',
                      )}
                      data-testid={washLabelRowTestId(row.key, sheetIndex)}
                    >
                      {row.text}
                    </div>
                  ))}
                </>
              ) : (
                <div className="text-neutral-600">
                  该加工单暂无商品/无码可打印{qrPlaceholderHint ? `（${qrPlaceholderHint}）` : ''}
                </div>
              )}
            </div>

            {/* ③ 二维码（`shrink-0`，永不被裁）：**紧挨正文**，且不贴纸底。
                🔴 2026-10-28 用户逐字「二维码紧挨文字排版，当前留白太多，这样尺寸就能缩小到50*140」
                ⇒ `mt` 由「2 行正文（9.31mm）」收到**一个块间距** 0.5mm（与位图通道同一个
                `WASH_LABEL_BLOCK_GAP_MM`）；码 80 CSS px（21.17mm），不画短码/说明字。
                🔴 下沿仍由容器 `padding-bottom: 15mm` 兜住（与位图通道
                `WASH_LABEL_BOTTOM_CLEARANCE_MM` 同值）—— 减掉那 9mm 只让纸变短，不让码贴虚线。 */}
            <div className="mt-[0.5mm] flex shrink-0 items-center justify-center">
              {sheet.qrValue ? (
                <QRCodeSVG value={sheet.qrValue} size={80} level="M" title={sheet.qrValue} data-testid="task-card-qr" />
              ) : (
                <div
                  data-testid="task-card-qr-placeholder"
                  className="flex h-[20mm] w-[20mm] shrink-0 items-center justify-center border border-dashed border-neutral-400 text-center text-[9pt] text-neutral-500"
                >
                  {qrPlaceholderHint ?? '待生成'}
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )

  // 🔴 预览层里**不 portal**（issue #5914）：同一份单据要摆进真尺寸纸框，portal 会跑到框外
  return inline ? doc : createPortal(doc, document.body)
}
