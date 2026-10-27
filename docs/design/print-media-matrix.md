# 打印介质矩阵（单据 = 内容，介质 = 参数）

> **状态**：已落地（issue #5651，2026-09-26）。本文是**设计真值源**：新单据先回答
> 「介质是哪一种」，再谈版式。
> **真值源（机器可读）**：`frontend/admin-web/src/lib/print-media.json` +
> `frontend/admin-web/src/lib/print-media.ts`；判据 = `tests/unit_ci_workflows/test_print_media_matrix_guard.py`。

## 1. 为什么要有这一层

2026-09-26 用户展示客户**现行四张单据**，MIGAO 只有两种半：

| # | 单据 | 介质 | MIGAO 落地 |
|---|---|---|---|
| 1 | 水洗唛 | 特殊标签 | ✅ `components/production/TaskCardPrint.tsx`（#4964 → #5646 改判 50×60 → 2026-10-25 加长到 50×70 → #7816 固定 50×150 → **2026-10-27（#7948）固定 50×110 → 2026-10-27 晚（#7960）固定 50×119、正文 11pt、二维码离底 ≥ 6mm**） |
| 2 | 报价单 | A4 | ✅ `components/orders/QuotationDoc.tsx`（#4965） |
| 3 | **加工单** | A4 | ✅ **本单新增** `components/orders/ProcessingDoc.tsx` |
| 4 | **销售单** | **三联纸** | ✅ **本单新增** `components/orders/SalesDoc.tsx`（针式/连续纸/压感复写 = 全仓此前**零支持**） |
| — | 发货单（MIGAO 自有） | A4 | ⛔ **已退场**（issue #7902，2026-10-27 用户裁定「移除发货单打印」「统一到销售单上打印」）：纸、组件、发货页/发货记录页的打印入口一并撤下；仓库改用销售单 |

不显式分层时的实际后果：新单据**再抄一份 A4 模板**，抄出来的 `@page` 与字段映射
**没有任何东西**会拦住它漂移 —— 纸面尺寸错 = 打废纸；字段错 = 账实不符。两者都不出声。

## 2. 介质矩阵

| 介质 id | 打印技术 | `@page` | 连续走纸 | 复写份数 | 版面预算（正文基准） | 实测状态 |
|---|---|---|---|---|---|---|
| `a4` | 激光 / 喷墨（浏览器 `window.print()`） | `size: A4; margin: 0`（版面内缩 12mm 走容器 padding，issue #7309） | 否 | 1 | 9pt（= 既有 12px 口径） | 已实测（既有单据在用） |
| `label-50x119` | 热敏 / 热转印（BLE 直打，通道归 #5052） | `size: 50mm 119mm; margin: 0`（整幅出图，纸边即版心）；🔴 **纸型固定**（issue #7960，2026-10-27 用户逐字「客户要求小于120mm」）—— 作废 #7816 的 150mm 与 #7776 的「纸长按内容撑开」；**二维码与底部虚线恒留 6mm 净空**（系统打印 `padding-bottom: 6mm` / 位图 `WASH_LABEL_BOTTOM_CLEARANCE_MM`） | 否 | 1 | **11pt**（2026-10-27 客户要求 <120mm + 用户「字体小一号」；抬头 14pt） | **已实测（纸宽侧）**（#5646：容器 49.998mm 宽、正文右边界 48.799mm；点阵 119mm × 8 dots/mm = 952px。119mm 的可用高度 = 111.8mm，满字段 15 行刚好装下（余 0.81mm），有折行即裁 ⇒ 文字块被裁、码永不被裁，见 §2 下方） |
| `label-50x70` | 热敏 / 热转印（**工人端发货标签**，通道归 #7761/#7786） | `size: 50mm 70mm; margin: 0`（整幅出图）；🔴 **纸长按内容撑开**：宽度固定 50mm、长度由 `frontend/worker-h5/src/shipment.mjs` 的 `shipLabelLengthMm()` 按纸面内容算（70mm = **最短**，上限 150mm，issue #7776 仍对发货标签有效） | 否 | 1 | 9pt | **已实测**（#5646 纸宽侧；2026-10-25 纸长 60→70mm；点阵 560px = 最短 70mm） |
| `continuous-241x140` | **针式点阵 + 连续纸 + 压感复写** | `size: 241mm 140mm; margin: 0`（版面内缩 6mm 12mm 走容器 padding，2026-10-25） | **是** | **3**（纸承担） | 9pt（**通用下限**，待实测） | 🚧 **待现场实测**（见 §5；含「边距 0 + 容器内缩」的真机对齐） |


🔴 **整张矩阵的 `@page` 上下边距都必须是 0**（issue #7309 立口径 → **2026-10-25 收口到全矩阵**；
用户 2026-10-19 逐字「我建议拿掉打印的页头和页脚」；2026-10-25 逐字「刚才发现打印预览的所有单子，
水洗唛都带了打印页头和页脚，你把所有打印的功能都检查一遍，移除掉」+「我希望做到**即使勾着也不要
打印出页眉和页脚**」）：
Chrome 把自己的页眉页脚（版式日期 / 文档标题 / 页面 URL / 页码）**画在 `@page` 的页边距里** ——
实测（Chromium 1243 = Chrome 14x，A4）：`8.7mm` 不画、`8.8mm` 画、`12mm` 画（= 改前值）。
⇒ 边距 0 时**没有可画之处**，页眉页脚必然不出（不依赖那条未文档化的阈值）；
反过来，**只要边距不是 0，就有一条被画出来的路** —— 所以三联纸原来的 `6mm 12mm`（靠「6mm 小于
8.7mm」侥幸）也在 2026-10-25 改成 **0 + `contentInset: 6mm 12mm`**。
版面内缩是**真值**，登记在 `contentInset`，由单据容器的 `padding` 承担；
`box-decoration-break: clone` 让**第 2 页起**也重复这段内缩（实测：不 clone 时 `padding-top`
不重复 ⇒ 内容贴到纸边）。可用版面逐值不变（A4 = 186 × 273mm、三联纸 = 217 × 128mm）。
判据 = `print-media.ts::browserChromeMarginProblems`（**非 0 即红**，`BROWSER_CHROME_MARGIN_MM`
只作历史说明）+ `tests/unit_ci_workflows/test_print_media_matrix_guard.py` 的 C10。

🔴 **工人端发货标签（issue #7761，2026-10-25）是第 6 份可打印单据**，介质 = DP235S 的 50mm 卷纸
`label-50x70`：内容 = 订单号 / 收货人 / 电话 / 地址 / 物流方式 / 物流公司 / 套数 / 备注。
⚠️ **两张纸自 issue #7816 起已分开，不要合并**：
- **水洗唛** = `label-50x119`（**固定** 50mm × 119mm，正文 11pt）—— 2026-10-27 用户逐字
  「客户要求小于120mm」「要不字体小一号？」（#7816 的 150mm 作废）；「二维码不能直接沉底，
  务必和底部留点距离」⇒ **二维码下沿与底部虚线恒 ≥ 6mm**（系统打印 = `.task-card-label` 的
  `padding-bottom: 6mm`；位图 = `wash-label.ts` 的 `footerBottomMax = heightPx - 6mm`，同一常量）。
  可用高度 = 119 − 1.2（上）− 6（下）= **111.8mm**；满字段 15 行 = 110.99mm（余 0.81mm）刚好装下、有折行即裁 ⇒ **文字块被裁、
  二维码永不被裁**（溢出由打印预览的纸面自检逐张报出，不静默）。
  纸面内容 = `frontend/admin-web/src/lib/wash-label-content.ts`（单一真值；两条通道同读）：
  `单号(加工单号) / 客户 / 第N套共M套 / 帘种 / 货号(值=颜色内容) / 安装小区 / 安装位置 / 门幅 / 用料 / 宽高 /
  加工方式(含加工费组合项，无前缀) / 褶法 / 特殊选项 / 备注 / 布料批次`
  —— issue #7833（2026-10-26）：行格式 `A: B`、褶法 `韩褶公式 52折`、**折行印全文**（无省略号）、
  底部一条虚线；issue #7839（同批后续）：单号去 `JG-` 前缀（只改纸面显示，系统编号不变）、顶部虚线移除；
  issue #7856：`安装小区` / `安装位置` 进纸面；**issue #7872（2026-10-26）**：「颜色」行的**文案改「货号」**
  （值仍是 `colorName`，一字不动）、**末行新增「布料批次」**（值 = 快照 `batchNo`，未指派印 `—`）。
- **发货标签** = `label-50x70`（50mm 宽**连续卷**，纸长按内容撑开 70~150mm，正文 9pt）——
  由 `frontend/worker-h5/src/shipment.mjs` 的 `shipLabelLengthMm()` / `shipLabelPageRule()` 现算，
  守卫 `frontend/worker-h5/tests/worker-h5-shipment-ready.test.mjs` 逐值比对 `pageSize` 与 `lengthMm`。
⇒ 改任一边都要看另一边；把水洗唛改回 `label-50x70` / `label-50x150` = 把「长度不足」带回来（守卫
`tests/unit_ci_workflows/test_wash_label_geometry_guard.py` 会红）。

## 2.1 打印入口唯一化与打印流水（issue #7902）

**一处入口**：所有纸都从**销售订单详情页**的打印层出（报价单 / 销售单 / 加工单=面料单 / 水洗唛）。
其余页面（发货页、发货记录页、加工单生产明细页）**不再持有** 打印入口 —— 同一份纸两处可打，
必然出现「两套状态各打一份」与「谁是最新那张」的争论。

- **派单闸门**：加工单 / 面料单 / 水洗唛 只在该订单**已有作业单**时出现（`processing_orders` 是派单产物）；
  面料单（`order_kind='outbound'`）没有水洗唛（issue #7891）。
- **联合打印** = 勾选 + 逐张引导：四份纸的介质不同（241×140 三联 / A4 / 50×119 标签），
  物理上必须一张一张换纸；浏览器也不保证 `window.print()` 连打不丢对话框 ⇒ **不自动连打**。
- **打印流水**（`print_logs`，V201）：`doc_type` / `doc_title`（打印当时的纸面名快照）/ `media_id` /
  `sheets` / `channel`（browser / ble）/ `batch_id+batch_index+batch_size`（联合打印批次）/
  `order_status`（当时的订单状态）/ `status`（fired / failed）+ `fail_reason` / 操作人快照 / 客户端 IP。
  它是**外部事实表**（纸出没出来服务端不知道）⇒ 只登记「已发起 + 结果」，不存业务对象副本。
  订单列表的「已打印」= 该表 `status='fired'` 行的**一次批量聚合**（`printedAt` / `printCount` /
  `printedDocTypes`），不是前端本地状态。

**四条技术要点（三联纸，实现前必读）**

1. 🔴 **复写是纸的特性，不是软件的事** —— 一次打印即复写三份 ⇒ 软件**只渲染一页**。
   `carbonCopies: 3` 描述的是**纸**，**不是**渲染次数（渲三遍 = 打三张、复写九份）。
   判据：`SalesDoc.test.tsx` 断言 DOM 里**只有一份** `.sales-sheet`。
2. **`@page` 按连续纸尺寸**：用户裁定 `241mm × 140mm`（两等分）⇒ `@page { size: 241mm 140mm; … }`。
   两等分纸的**单联实际高度**需现场核对，**不许**照 A4 比例硬套。
3. **针打字号独立预算**：针打 180dpi 量级，A4 的 6pt 量级上去会糊 ⇒ 三联纸**不复用** A4 的字号；
   矩阵按介质给 `minFontPt`，单据只读它、不自己定字号。
4. **走纸与页边距**：连续纸靠**走纸孔**定位 ⇒ 容器按纸固定高度 + `overflow: hidden`
   （高度 = `printUsableHeightMm()` = 页长 − 上下边距；`241×140` + `6mm 12mm` ⇒ **128mm**）——
   内容超高会打到**下一联**，属「纸面与账目对不上」的一种形态，**不许**靠浏览器自然分页兜。

## 3. 分层（三层，别混）

| 层 | 是什么 | 落在哪 | 判据 |
|---|---|---|---|
| ① 内容 / 字段映射 | 这张单据**印什么**（列清单 + 取值口径） | 各 `*Doc.tsx`，每张**只有一份** | `test_print_media_matrix_guard.py` C5（列清单全仓**恰好一个文件**命中）+ **C7**（商品身份走 `lib/order-item-sku.ts` 的 `orderItemSku()`、物流方式走 `lib/logistics.ts` 的 `freightText()`） |
| ② 介质 | 印在**什么纸**上（尺寸 / 边距 / 技术 / 复写 / 字号） | `lib/print-media.json` + `.ts` | 同上 C2（单据 `@page` 与矩阵同源）、C4（待实测登记）、**C10**（纸面不带浏览器页眉页脚：**每一份**浏览器打印介质的 `@page` 上下边距必须为 0 + 内缩走 `contentInset` 与容器 padding） |
| ③ 打印隔离 | 一次只放**一份**单据上纸 | `body > *:not(.print-doc)`（#4983） | `test_print_doc_convention_guard.py` |
| ④ 打印入口 / 纸型唯一 | `window.print()` 只在 `lib/print-doc.ts`（且**目标提交后**才调用）；`@page` 只在「本次目标是本单据」时发表 | `lib/print-doc.ts` + 各 `*Doc.tsx` 的条件 `<style>` | `test_print_single_doc_on_paper.py`（C1 / C2 / C3） |
| ⑤ 打印前自检 + 截图 | 真尺寸纸框 + 溢出/页数 + 本次纸型；「打印」「复制截图」两个出口 | `components/orders/PrintDocPreview.tsx` + `lib/print-capture.ts` | `PrintDocPreview.test.tsx` + `tests/e2e/specs/orders/print-preview.spec.ts` |
| ⑥ 打印入口（商家可见面） | **一份单据只有一个入口**，且与订单状态**解耦**。<br>**订单详情页**只有一个「打印」（页面级，不在任何状态分支里），进来后在自检层顶部以**单据标签**选（销售单 / 报价单 / 发货单）—— 加工单（A4）**不在**这里（issue #7870）。<br>**加工单生产明细页**（`/processing-orders/{id}/production`）同样只有一个「打印」，单据标签 = **水洗唛 / 加工单**（加工单读订单详情 DTO，需 `order:detail`；无该码的岗位只有水洗唛）。先预览再出纸 | `OrderDetail.tsx` 的 `ORDER_PRINT_DOCS` + `processing-orders/[id]/production/page.tsx` 的 `printDocs`（各自**一处**声明）+ `PrintDocPreview.tsx` 的 `docs` / `onSelect` | `tests/unit_ci_workflows/test_order_print_entry_matrix.py`（G1~G8）+ `frontend/admin-web/tests/unit/pages/order-detail.test.tsx` + `frontend/admin-web/tests/unit/pages/processing-orders-production.test.tsx` |

🔴 **介质是参数，不是复制粘贴出来的页面**：同一份字段映射可以落不同介质 ⇒
`SalesDoc` 把介质做成 **prop**（缺省三联纸，可切 A4）。判据两条：
① 「切介质后逐格取值逐字相同」（`SalesDoc.test.tsx`）；
② 「列清单全仓唯一」（C5，复制一份映射 ⇒ 红）。

### 3.1 单据的字段映射（列清单 = 唯一真值，改动必须同批改本表 + C5 的钉住元组）

各单据组件里的 `*_DOC_COLUMNS` 常量（打印介质守卫 C5 逐字钉住同一串，**两处必须一致**）：

| 单据 | 列清单（有序） | 说明 |
|---|---|---|
| 加工单 / 面料单 | `货号 / 颜色 / 门幅 / 数量 / 批号 / 备注` | 每套一张 **6 列表**（`frontend/admin-web/src/components/orders/ProcessingDoc.tsx`；两型同版式，纸面标题按作业单两型给名）；🔴 纸面**不印**工序清单（issue #7274）；「品名 / 帘种 / 尺寸」三列与「工艺」行自 issue #7901 / #7909（用户 2026-10-27「面料单移除红框的行列」+「加工单也要移除」）退场 |
| 销售单 | `序号 / 货号 / 颜色 / 门幅 / 帘种 / 数量 / 单位 / 单价 / 金额` | 三联纸单联 9 列表（`frontend/admin-web/src/components/orders/SalesDoc.tsx`）；「品名」列自 issue #7530 退场、「帘种」自 issue #7625 加入 |

🔴 **2026-10-24（issue #7625）「组件」退场 + 四张单据统一加「帘种」**：用户逐字
「不要组件这一列，另外给所有打印预览表格都加一列用来区分是布帘还是纱帘」⇒ 报价单 / 加工单删掉
`组件` 列，四张纸面（报价单 / 加工单 / 发货单 / 销售单）的明细表都加 `帘种` 列（值 `布帘` / `纱帘`，
布料单印占位）。取值口 = `frontend/admin-web/src/lib/order-item-sku.ts` 的 `orderItemCurtainType()`
（`curtainType` 显式声明 → `componentRole` 受控枚举 → 布料单空串 → 缺省布帘，与后端
`ProcessingOrderService.COMPONENT_ROLE_POSITIONS` 同一张映射）；判据 = 四份单据测试的列清单断言 +
`tests/unit_ci_workflows/test_print_media_matrix_guard.py` 的 C5。

🔴 **2026-10-27（issue #7891）加工项绑商品 + 扫码报工码迁到加工单 + 作业单纸面按两型命名**：

1. **加工项绑商品**（用户逐字「发货单的加工项需要和商品绑定，比如如果是成品帘，一览展示商品，
   商品下面是加工项，展示内容参考水洗唛的那种格式，还有特殊选项也要放上去，都放在加工项那一栏里面」；
   同一条还点了「销售单和报价单都缺了加工项」）：
   - 销售单 / 报价单 / 发货单三份纸都在**商品行下方**印一行子行，形态 = 水洗唛式 `标签 值`：
     `加工项：定型、韩褶 各 6.3 · 特殊选项：拼2次-布`（特殊选项与加工项**同栏**）；
   - 发货单原来表外那条独立「加工项（数量：米）」区**退场**（不绑商品 = 与商品行对不上）；
     加工费合计仍印（口径不变 = 行级落库 `processingFee` 求和）；
   - 文案**单一构建器** = `frontend/admin-web/src/lib/processing-item-text.ts`（`processingItemsText` 从
     `frontend/admin-web/src/lib/processing-item-text.ts`（原在已退场的 ShipmentDoc）里）；特殊选项取
     `frontend/admin-web/src/lib/craft-display.ts::craftSpecRows()` 的同一份格式化。
     布料行没有 `processingInfo` ⇒ 不出子行。
2. **扫码报工码从销售单迁到加工单**（用户逐字「把销售单左上角的扫码报工二维码迁移到加工单打印上，
   这样设计才是合理的」）：加工单表头左上角印 `processingOrder.scan_url` 的二维码（= `{base}/o/{短码}`，
   服务端 302 到工人报工页 `/w/`），码旁只留**竖排**「扫码报工」（短码不上纸，issue #7608 口径不变）；
   **缺码不画假码**（无 `scan_url` ⇒ 整块不出现，不回落作业单号）。销售单纸面**不再有**该块。
3. **作业单纸面标题按两型**（用户 2026-10-27 裁定「入口统一叫作业单；面料单就叫面料单，不要叫裁剪单」）：
   成品帘（`processing`）⇒「加工单」；面料单（`outbound`）⇒「面料单」；
   真值 = `frontend/admin-web/src/lib/processing-order.ts` 的 `WORK_ORDER_DOC_TITLES` /
   `workOrderDocTitleOf()`。面料单**不再提供水洗唛打印入口**（用户逐字「面料单不能打印水洗唛，
   应该打印加工单」）。
4. **加工单「工艺」按水洗唛形态分行**（同日追加，用户逐字「加工单打印的工艺也参考水洗唛上的
   加工和特殊选项的展示方式」+ 真机截图红框指向那一整串长句）：每套块的那一格改为水洗唛式多行
   `标签 值` —— `加工方式`（复用 `frontend/admin-web/src/lib/wash-label-content.ts::washLabelCraftMode()`）
   + `特殊选项` 独立一行（`washLabelSpecialOptions()`，无值不渲染）+ 其余工艺规格逐行
   （顺序沿用 `craftSpecRows()`）。**不新增列**：`PROCESSING_DOC_COLUMNS` 仍是 C5 的唯一真值。

判据 = `frontend/admin-web/tests/unit/components/` 下 SalesDoc / QuotationDoc / ProcessingDoc
四份测试 ＋ 类级守卫 `tests/unit_ci_workflows/test_print_media_matrix_guard.py` 的 C9 / C11 / C12；
用例登记 = UI-134（码）· UI-138（加工项绑商品）· UI-139（两型命名 / 面料单不印水洗唛）·
UI-140（加工单工艺按水洗唛形态）。

🔴 **2026-10-14（issue #6901）「数量(米)」→「数量」**：列名不能写死单位 —— `quantity` 的单位随行
（快照行 `unit` 可能是米 / 件 / 套）。同一行的**列名与值**都出自
`frontend/admin-web/src/lib/order-item-sku.ts::orderItemQuantity()`：有单位 ⇒ 印 `数量(米)`，
**没采集到单位 ⇒ 只印 `数量`**（不编「米」）。

🔴 **2026-10-18（issue #7274）工序块从纸面移除**：用户逐字「工序细节不用在打印单上，移除掉工序相关的
表格信息」⇒ `ProcessingDoc` 的 `operations` prop 与 `工序 / 名称 / 应做 / 状态` 子表**整块退场**
（issue #6901 曾是它的来由）。工序清单仍在**屏幕**上的加工单块
（`frontend/admin-web/src/components/orders/ProcessingOrderBlock.tsx`）与「复制全部」文本、以及工人扫码面呈现；
读面 `GET /api/admin/production/orders/{id}/operations` 与显示名口径
`frontend/admin-web/src/lib/operation-display.ts::operationDisplayName()` **不变**。
判据 = `test_print_media_matrix_guard.py` 的 C8（把工序接回纸面 ⇒ 红）。


## 4. 字段缺口（**如实登记，不编数**）

> 🔴 **2026-10-14（issue #6869）列清单重做**：用户逐字「缺了商品 sku 的信息」「货运 express · 顺丰速运，
> 不要用英文」「报价单展示部位是啥意思」⇒ 三张单据（报价单 / 销售单 / 加工单）与发货单的商品明细
> 统一改成「**品名 / 货号 / 颜色 / 门幅**」四件套（取值口 = `lib/order-item-sku.ts` 的 `orderItemSku()`），
> 「部位」列退场（issue #4521 移除录入面后它对普通订单恒空，只有纱帘行有值 —— 该信息并入「工艺：…」行）。
> ⚠️ 根因**不是**漏列：原先读的 `item.productCode` / `item.color` / `item.specification` **都不在
> `OrderItemResponse` 里**（真字段 = `skuCode` + `processingInfo.colorName/doorWidth/remark`），
> 所以那些列在真单上恒空 —— 该形态的类级守卫 = 本文件的判据 **C7**。

客户实证制式里有、而 MIGAO **今天没有口径**的栏位 —— 纸面以**显式标注**呈现
（`—` / 「未采集」），**绝不**印 `0.00` 或空串（印 0 = 把「没有这个数」画成「余额为零」）：

| 单据 | 栏位 | 为什么是缺口（实测依据） | 纸面处置 |
|---|---|---|---|
| 加工单 | **制单人** | `Order` DTO 无该列（`OrderRemark.operator` 是备注操作人，不是制单人） | 「未采集」+ 脚注 |
| 加工单 | **批号** | ✅ **已落地，不再是缺口**（issue #5914）：`ProcessingOrderItem.batchNo` 存在且由 `stampAssignedBatches` 派工指派时写入；A4 加工单「批号」列与洗水唛「布料批次」末行（issue #7872）读**同一份**快照键 | 有值印真值；未指派 ⇒ `—`（`undefined` = 未指派 ≠「本系统没有这个字段」） |
| 销售单 | **上期余额 / 预存抵扣 / 账户余额** | `Order` 只有 `totalAmount` / `discountAmount` / `actualAmount`；`SystemSettings` 只有 `companyName` / `logo` / `notificationEnabled` / `code` —— **无余额面** | 「未采集」+ 脚注（含数字即判红） |
| 加工单 | **数量单位** | `OrderItem`（订单详情 DTO）**无** `unit` 键 ⇒ 纸面的单位只可能来自加工单**快照行** `unit`（issue #6901 起按行印） | 快照有 `unit` ⇒ 列名印 `数量(米)`；**没有 ⇒ 只印 `数量`**（不编「米」） |
| 销售单 | 单位 | `OrderItem` 无 `unit`；但 `quantity` 在本系统**恒为米**（发货单表头「数量(米)」、报价单「元/米」）⇒ 取**同一口径**，不算缺口 | 印「米」 |

## 5. 未核实项 / 待现场实测（**升级条件写死在这里**）

### 5.1 三联纸真机参数（`continuous-241x140`，`measurement = pending-field-measurement`）

| # | 待实测项 | 现在的通用值 | 实测后要改的地方 |
|---|---|---|---|
| 1 | 走纸长度 / 单联可用高度（撕线位置决定） | 页长 140mm（用户裁定「241mm × 140mm 两等分」） | `print-media.json` 的 `pageSize` + `pendingMeasurements` |
| 2 | 左 / 右边距（走纸孔带吃掉的可打印宽度） | 12mm | 同上 `pageMargin`。⚠️ **先核可打印宽度**：常见 24 针窄行机（80 列）最大打印宽度约 **203.2mm**，而 `241 − 12×2 = 217mm` 版心**大于**它 ⇒ 右侧可能被裁或被驱动缩放。现场量出实际可打印宽度后回填（若确为 203.2mm，左右边距应取 ≈19mm，并重算销售单的行高预算） |
| 3 | 上 / 下边距（撕线到首行、末行的留白） | 6mm | 同上 `pageMargin` |
| 4 | 每行行高（针打行距，与字号绑定） | 未定（随字号） | `print-media.json` + `SalesDoc` 的行高预算 |
| 5 | 最小可用字号 | **9pt（通用下限，不是实测值）** | 同上 `minFontPt` |

> ⛔ 表格里带数字的项**都是通用值**，不是量出来的读数。**不许**把推定值改写成实测值 ——
> 那会让下一个读它的人以为已经量过了。

### 5.2 现场核对清单（打印当天照着走）

1. 针打型号 + 驱动里的**自定义纸型**是否就是 `241mm × 140mm`（否则 `@page` 与驱动不一致 ⇒ 整体偏移）；
2. 装纸后**试打一张空白定位**，量左/上边距（连续纸的孔距与撕线会吃掉几 mm）；
3. 确认撕线正好落在**两联之间**（错位 = 复写联次串位）；
4. 走纸长度与「一联 140mm」是否一致（不一致 ⇒ 改 `pageSize` 并重跑判据）。

### 5.3 未核实（**取值口径存疑，已登记、未定论**）

- **销售单「订货电话」**：客户实证 #4 的栏位位置取的是**下单电话**（= `order.customerPhone`）。
  若现场口径实际是「商户订货热线」，则该栏应改读企业设置（而 `SystemSettings` 今天**无电话字段**
  ⇒ 会变成一个**新缺口**）。**不猜**：现场确认后再改取值，并同步本表。

## 6. 与发货链的关系（**已接线**，2026-09-27 收口）

用户 2026-09-26 裁定销售单要「挂在发货链上」= 随货给客户的那张，数量与**实发**同源。

- **真值载体**：`order_shipment_items`（issue #5648 / PR #5664 拥有）——「这一单实际发了多少」的
  **唯一**真值载体；消费入口 = `OrderShipmentService.readShipment`，**不得另建第二份投影**
  （类级守卫：`tests/unit_ci_workflows/test_shipment_read_surface_guard.py` 的 C4 ——
  视图键 `"shipped_quantity"` 在 Java 主源里恰好命中一个文件）。
- **两个读面（本单补齐第二个）**：
  | 面 | 端点 | 准入 |
  |---|---|---|
  | 工人 | `GET /api/worker/shipment/orders/{orderId}` | 工人 session（`X-Worker-Session-Id`），零商家权限码 |
  | 管理 | `GET /api/admin/orders/{id}/shipments` | 商家 session，权限码 `order:list`（与同页详情读面同码） |
  两面**共用同一份** `readShipment` ⇒ 车间记的实发与桌面纸面的实发**逐字同源**；跨租户统一 404
  （与「订单不存在」逐字同形，不是 403）。
- **前端消费**：`SalesDoc` 的数量列由 `frontend/admin-web/src/lib/sales-shipment.ts` 的
  `resolveSalesQuantity` 单点判定，**四态各自可判**（已发货 = 实发 / 部分发货 = 已发行实发 + 未发行
  标「未发」/ 未发货 = 订单数量**并标明基准** / 读面没取到 = 显式标注，**不冒充「未发货」**）；
  ⛔ **永不印 0**（`0` = 「实发为零」，与「没有这个数」是两件事）；挂不到订单行的实发行**显式提示行数**。
- **仍未做的**（照实登记，不属本单）：`order_shipments` 的「谁生成 / 谁打印 / 发货前还是发货后」的
  **产品口径**由 #5648 侧承载（本单只补读面 + 纸面消费）；「补发第二张发货单时纸面怎么呈现」当前口径 =
  **实发合计**（`resolveSalesQuantity` 跨全部发货单累加），如现场要求逐单分列，需另立裁定。

## 7. 新增一份可打印单据的 SOP

1. **先回答「介质是哪一种」** —— 在 `print-media.json` 里选（不够用才加新介质，加则同时补
   `PRINT_MEDIA_IDS` 与待实测登记）；
2. 单据里用 `printPageRule('<介质id>')` 生成 `@page`（**不许**自写 `@page size`），并且**必须条件化**：
   `{printTarget === '<目标位>' && <style>{printPageRule('<介质id>')}</style>}` —— `@page` 是**文档级**规则，
   同页多份单据并存时**最后声明的那条赢**（实测点「打印发货单」曾按销售单的三联纸出纸 = 打废纸，issue #5914）；
   打印态的 `display: block` 规则同样要按 `[data-print-target='<目标位>']` 限定（否则非目标单据仍占版面 ⇒ 空白页）；
   纸面容器还要标 `data-print-sheet`（预览层的溢出/页数自检靠它量内容高度）；
3. 容器带 `-print-area` + 共享标记类 `print-doc`，隔离选择器**恰好** `body > *:not(.print-doc)`，
   `visibility` 防御**限定本单据的 `data-print-target`**（#4983 / #4965）；
4. 在 `tests/unit_ci_workflows/test_print_media_matrix_guard.py` 的 `PRINT_DOCS` 登记
   （**未登记 ⇒ C3 判红**）；若该单据有列清单，登记进 `SINGLE_PROJECTION`；
5. 在 `lib/print-doc.ts` 的 `PRINT_TARGETS` 加 target（标题与介质的**唯一真值**），并在**它所属的那个页面**的
   **可打印清单**里登记（订单详情 = `OrderDetail.tsx` 的 `ORDER_PRINT_DOCS`；加工单生产明细 =
   `processing-orders/[id]/production/page.tsx` 的 `printDocs`）——
   🔴 **不要再加一个按钮**（issue #7544）：同页多份单据的入口是**页面级唯一那个「打印」**，
   加的是菜单里的一项；入口与订单状态无关（`closed` / `refund` 同样能补打），
   所以也不许把入口塞进任何一个 `status === …` 分支（判据 = `test_order_print_entry_matrix.py` 的 G2）；
6. 测试要带**红证**（把实现改坏 ⇒ 判据必红）；缺值/缺码/长名的处置见 §4 与
   `SalesDoc.test.tsx` / `ProcessingDoc.test.tsx` 的判据。

## 8. 打印前自检与截图（issue #5914）

浏览器自带的打印预览**答不了**三件事，所以打印前多一层「纸面自检」（Preview / `PrintDocPreview.tsx`）：

1. **内容会不会被裁** —— 销售单固定单联 128mm（`overflow: hidden`），实测明细 **>6 行**即溢出，
   被裁掉的恰好是「本单应收 / 账户余额 / 页脚温馨提示」；自检量 `[data-print-sheet]` 的 `scrollHeight`
   报「超出 N mm」；
2. **本次是哪张纸** —— 非标纸型（241×140 / 50×70）在驱动里没登记自定义纸型时会有落差，自检把
   纸型与版心（mm）明写在标题行；
3. **这次到底打哪一份** —— 同页四份单据时，自检层只摆**本次那一份**；换一份不用退出重进：
   自检层顶部那排**单据标签**就是选择器（issue #7544，点标签只换预览、**不改这次的打印目标**，
   也不会因此出纸 —— 只有点「打印」才 `requestPrint`）。

两个出口：**打印**（走 `usePrintDoc().requestPrint()`，目标提交后才 `window.print()`）与
**复制截图**（`lib/print-capture.ts`：计算样式内联 → `SVG foreignObject` → canvas → PNG → 剪贴板；
剪贴板不可用 ⇒ 下载 PNG + 明示提示）。截图与打印**共用同一份单据组件** —— 不产生第二份字段映射
（守卫 C5 仍成立），预览实例用 `inline` 渲染且**不带** `data-print-target`，故打印媒体下不上纸。

## 9. 边界（本设计**不做**的事）

- ❌ 不改标签类（50×30 / 30×60 / 水洗码）的既有版式 —— 归 #4946 / #5052 / #5646；
- ❌ 不引入新的打印服务 / 中间件（浏览器打印 + 现场驱动配置是既定口径）；
- ❌ 不造金额/库存逻辑（金额一律复用服务端字段：`lib/order-amount.ts` + 订单字段）；
- ❌ 不做工人端页面、不做蓝牙打印通道。
