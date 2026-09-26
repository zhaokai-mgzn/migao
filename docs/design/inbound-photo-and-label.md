# 拍照入库 + 入库标签打印 —— 设计真值源（工人拍上游标签 → 米宝识别 + 人工确认 → 入库单过账 → 50×30mm 入库标签）

> **状态**：**设计单**（docs-only，**不改生产代码、不碰 ai-agent**）。issue **#5052**。
>
> **落地路径（#5052 正文末尾逐字）**：「首个 PR 只落 `docs/design/inbound-photo-and-label.md`（设计 + 用户裁定），再开实现 PR」
> ⇒ **本包只出这一份文档**，不写实现代码；实现另开 PR。
>
> **配套真值源 / 既有设计**：
> 客户端包 **#5061**（Android 壳 App，**§8 对其立论提出改判动议**）·
> 入库单本体 **#5045**（已闭环，本单**只消费其过账能力**）·
> 工人端 H5 范式 **#4716**（已闭环）·
> 标签打印范式 **#4946**（已闭环，本单**照其范式、不复用其表**）·
> 工人登录态 **#4733**（已闭环）·
> 工人零商家权限 **#4727**（已闭环）·
> 库存米数小数化 **#5063**（已闭环）·
> 工人档案创建 **#4869**（**OPEN —— 本单唯一未解阻塞**）。
> 同目录参考密度与结构：[worker-h5-scan-and-report.md](worker-h5-scan-and-report.md)、
> [set-code-and-scan-loop.md](set-code-and-scan-loop.md)、[worker-scan-terminal.md](worker-scan-terminal.md)。
>
> ## 本文的三类断言（**逐条标来源，不许混**）
>
> | 标记 | 含义 | 处置 |
> |---|---|---|
> | **【实测】** | 本次在 `origin/main` = `78c67effc` 的独立工作区现场复核，命令见 **附录 A** | 可直接作为设计前提 |
> | **【转述】** | 主会话 2026-09-26 提供（用户裁定 / 依赖状态 / npm 版本），本次**未**逐条复核 | 文中显式写「据转述」，不升格为事实 |
> | **【待核】** | 需厂商书面答复 / 样机实测 / 外部资料 | 集中登记在 §8.5 与 §13；**未核实前不得当成立** |
>
> 🔴 **两条不许**：**不许**把【转述】写成【实测】；**不许**把「npm 上有包」读成「厂商官方支持」（§8.4）。

---

## 1. 一句话 + 用户需求原文

**一句话**：给仓库收货侧补一条**工人可用的拍照入库链** —— 工人用手机拍**上游标签**（布卷/包装上原有的、带商品 SKU 信息的标签）
→ 米宝识别并**引导确认** → 工人确认后**经入库单过账** → 服务端出 **50×30mm 入库标签**并打印贴到布卷/塑料袋上。

**设备侧只买「手机/平板 + 标签机」**，不买 PDA 一体机（**一体机后降为人体工学备选**，见裁定 10）。

### 1.1 用户裁定逐字（**本文不得自行改判**）

| # | 日期 | 逐字 | 落法 |
|---|---|---|---|
| 逐字① | 2026-09-21 | 「**不是固定的，工人频繁移动**」 | ⇒ 「车间 PC 常驻打印工位」不成立 ⇒ 打印通道取**方案 ②（随身打）** |
| 逐字② | 2026-09-21 | 「**工人已有可用的安卓手机**」这个条件**成立** | ⇒ 「手机 + 便携蓝牙标签机」的**成本结论成立**（只需买打印机，不必给工人配手机） |
| 逐字③ | 2026-09-26（据转述） | B 端**统一到 `frontend/bmini-app`**；`frontend/worker-h5` **保留为「扫码直达免安装」轻入口，不重写** | 见 §3 增量裁定 12 / 13、§5.4 |

### 1.2 主链的一次往返（本设计的目标形态）

**今天**：工人拿到上游布卷 → 翻找/辨认手写或打印的品名色号 → 凭记忆或纸质单据 → 交给文员在 admin-web 建入库单 → 打印标签 →
（或干脆不入库、不入账）。**环节多、无留痕、易错**，且**入库这一步卡在"有 admin-web 权限的人"手里**。

**改完**：工人**拍一张照** → 识别结果回显 → **确认/补录** → 提交 → **过账即动库存** → **标签当场打出来贴上**。
一次入库 = 「一次拍照 + 一次确认」，**库存与标签的真值都在服务端**（§4、§9）。

---

## 2. 现状（`origin/main` 实测：每行都有可复核依据）

> 复算方式见 **附录 A**；基线 = `78c67effc`（= 本次开工时的 `origin/main`）。

### 2.1 库存与入库单（**本单要接的东西**）

| 能力 | 现状（**实测**） | 依据（仓库相对全路径 + 符号锚点） |
|---|---|---|
| 库存权威 | `product_skus.stock`，**`NUMERIC(12,1)`**（1 位小数 = 0.1 米粒度，标注 `V115/#5063`）；`products.stock` 是**派生冗余**列 | `backend/admin-api/src/main/resources/db/init/schema.sql`（`product_skus` 表定义的 `stock` 列 + 列注释） |
| 库存台账 | `stock_ledger_entries`：`delta NUMERIC(12,1)`、`before_qty`/`after_qty` 同精度 | 同上（`stock_ledger_entries` 表定义） |
| **入库单（建单/过账/批次/成本）** | ✅ **已闭环（#5045 CLOSED）**。控制器挂在 `/api/admin/inbound-orders`：`GET`（列表）、`GET /batches`、`GET /opening-template`、`POST /opening-import`、`POST`（建单）、`GET /{id}`、`PATCH /{id}`（过账/作废动作） | `backend/admin-api/src/main/java/com/migao/admin/controller/InboundOrderController.java`（类上的 `@RequestMapping("/api/admin/inbound-orders")` + 各 `@GetMapping`/`@PostMapping`/`@PatchMapping`） |
| **过账服务方法（本单复用的唯一入口）** | `InboundOrderService` 的 `create(...)` / `post(String rawId, Long tenantId, String operator)` / `cancel(...)` / `list(...)` / `detail(...)` / `batches(...)` | `backend/admin-api/src/main/java/com/migao/admin/service/InboundOrderService.java`（方法签名） |
| 建表与幂等 | `V111__create_inbound_orders_and_batches.sql`（建表 + `reason` 放行 `inbound`）、`V117__inbound_order_idempotency_and_source.sql`（幂等键 + source）、`V118__stock_batch_legacy_no_and_opening_register.sql` | `backend/admin-api/src/main/resources/db/migration-archive/` 下上述三个文件（注：**已归档**，现行 schema 以 `db/init/schema.sql` 为准） |
| 入库单 UI | 建单（草稿）→ 过账（自动生成批次号 + 自动加库存 + 移动加权平均）+ 期初建账导入（建单并直接过账，**幂等命中不重复加库存**） | `frontend/admin-web/src/app/(dashboard)/inbound-orders/page.tsx`；前端 API 封装 `frontend/admin-web/src/lib/api.ts`（`inboundOrderApi`） |
| 权限码 | `inbound:view`（读）、`inbound:create`（写）—— **工人一律没有**（§9） | 菜单/权限判据见 `frontend/admin-web/src/lib/menu-nav.test.ts`、`frontend/admin-web/src/components/Sidebar.test.tsx` 的用例语料 |
| 非整数米 | ✅ **已闭环（#5063 CLOSED）**：三层粒度一起升到 **1 位小数**，前端单一真值 = 「**> 0 米**且**最多 1 位小数**」，超 1 位**显式拒绝、不静默取整** | `frontend/admin-web/src/lib/stock-quantity.ts`（`STOCK_QUANTITY_RULE` / `checkStockQuantity` / `formatStockQuantity`）+ 上表 `NUMERIC(12,1)` |

🔴 **对 #5052 原文的一处口径订正（照实登记）**：#5052 正文把「**非整数米**」列为「对本单是**现实阻塞**」——
该阻塞**已解除**（#5063 CLOSED，且 `schema.sql` 里的 `NUMERIC(12,1)` 已是**现状**而非计划）。
⇒ 本单**不再需要**「先只支持整数米」这类折中，**直接按 0.1 米粒度收**（判据见 §11）。

### 2.2 工人侧可达面（**本单必须扩建的地方**）

| 能力 | 现状（**实测**） | 依据 |
|---|---|---|
| 工人身份与路径 | `/api/worker`：`POST /login`、`POST /session/switch`、`POST /session/logout`、`POST /session/current` | `backend/admin-api/src/main/java/com/migao/admin/controller/WorkerAuthController.java` |
| 工人生产业务 | `/api/worker/production`：`GET /orders/{orderId}/operations`、`POST /orders/{orderId}/operations/{operationId}/report`、`GET /scan`、`POST /scan/complete`、`GET /current-worker` | `backend/admin-api/src/main/java/com/migao/admin/controller/WorkerProductionController.java` |
| 工人短链入口 | `GET /s/{shortCode}`（302 换回 `/w/?t=<token>`）；短码 = 8 位、字母表 `0123456789ABCDEFGHJKMNPQRSTVWXYZ`（去 `I/L/O/U`，人可读可抄） | `backend/admin-api/src/main/java/com/migao/admin/controller/WorkerShortLinkController.java`；`backend/admin-api/src/main/java/com/migao/admin/service/WorkerShortLinkService.java`（`ALPHABET` / `CODE_LENGTH` / `REPORT_PAGE_PATH`） |
| 工人零商家权限 | `ADMIN_API_REJECTED_ROLES = Set.of("customer", "agent", "worker")` ⇒ 工人持 session 打 `/api/admin/**` 被拒 | `backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java` |
| **图片识别（商家侧）** | `POST /api/admin/image-recognition`；**权限码按 `targetType` 动态取**（`product` → `product:create`，`order` → `order:create`），未知 target **400 fail-closed** | `backend/admin-api/src/main/java/com/migao/admin/controller/ImageRecognitionController.java`（`TARGET_PERMISSIONS` + `PermissionInterceptor.requirePermission`） |
| **🔴 工人可达面缺口（本次实测结论）** | `/api/worker/**` 现有端点**没有任何**图像识别 / 标签解析 / 入库端点；而唯一的识别控制器挂在 `/api/admin/image-recognition` 且**按 target 取商家写码** ⇒ **工人双重被拒**（① 路径在 `/api/admin/**` 被 `ADMIN_API_REJECTED_ROLES` 拒；② 即便放行，工人**零商家权限码**，`requirePermission` 仍拒） | 上面三行合起来即结论；复算命令见附录 A |
| 工人档案创建 | ❌ **#4869 OPEN**：没有任何产品路径能创建工人档案 ⇒ 首个工人都建不出来 | 关联 **#4869**（状态【实测】） |

### 2.3 识别链路现状

| 能力 | 现状（**实测**） | 依据 |
|---|---|---|
| vision 客户端 | 有：`LLMFactory.create_vision_llm(model_override)` | `backend/ai-agent-service/app/llm/factory.py` |
| vision 识别入口 | 有：`recognize(...)`（内部取 `create_vision_llm()`） | `backend/ai-agent-service/app/vision/recognizer.py` |
| 图片上限 | **单条消息最多 3 张**（上传面与 chat 面各有一道） | `backend/ai-agent-service/app/api/upload.py` 的「单次最多上传 3 张」常量与 docstring；`backend/ai-agent-service/app/api/chat.py` 的「单条消息最多支持 3 张图片」错误分支；`backend/ai-agent-service/app/api/internal.py` 的字段描述「1~3 张」 |
| **前端条码解码库** | ❌ **全仓零命中**（`jsqr` / `zxing` / `barcode` 在**所有** `package.json` 里都没有） | 复算命令见附录 A ⇒ §6 的「解码优先」需要**新增依赖**（这是有意的采购决策，不是遗漏） |
| 现有扫码能力 | 仅 `Taro.scanCode({ scanType: ['qrCode'] })`（B 端小程序生产页）——**只扫二维码、且是微信/小程序侧能力** | `frontend/bmini-app/src/pages/production/index/index.tsx` |

### 2.4 前端形态现状（**2026-09-26 裁定的落点**）

| 项 | 现状（**实测**） | 依据 |
|---|---|---|
| B 端小程序工程 | Taro **4.2.1**；`@tarojs/taro` / `@tarojs/cli` / **`@tarojs/plugin-platform-h5` 均 4.2.1（已安装）** | `frontend/bmini-app/package.json` |
| 一端双编译 | ✅ **现成能力**：`config/index.ts` 里有 `h5` 段（`publicPath` / `staticDirectory` / postcss），且 `package.json` 已有 `build:h5` 与 `dev:h5` 脚本 | `frontend/bmini-app/config/index.ts`、`frontend/bmini-app/package.json` |
| 工人相关页面 | `frontend/bmini-app/src/pages/worker/login/`（仅登录页） | 实测列出 |
| 轻入口 H5 | `frontend/worker-h5`：**零依赖**（无 `package.json`，纯 `.mjs` + `index.html`），同源调 `/api/worker/**`（页面与 API 同在 `app.migaozn.com` ⇒ 无跨域），部署在 `/w/` | `frontend/worker-h5/src/api.mjs`、`frontend/worker-h5/src/scan-input.mjs` |
| **`/i/` 码空间** | ❌ **全仓零命中** ⇒ 是**新建**码空间（≠ 已有的 `/s/`） | 复算命令见附录 A |
| 打印计数与留痕范式 | 已有列 `print_count`（`processing_set_part_tokens.print_count`，列注释写明「原子自增，多人同时打印不丢计数」；`processing_orders.print_count` 同族） | `backend/admin-api/src/main/resources/db/init/schema.sql`；实体 `backend/admin-api/src/main/java/com/migao/admin/entity/ProcessingSetPartToken.java` |
| 审计 | 有通用审计服务 `AuditLogService` | `backend/admin-api/src/main/java/com/migao/admin/service/AuditLogService.java` |
| 标签版式范式 | `@page { size: 30mm 60mm; margin: 0 }` + 固定尺寸容器 + `overflow: hidden` + 每张独占一页（洗水码，竖版 30×60） | `frontend/admin-web/src/components/production/TaskCardPrint.tsx` |
| 打印端点范式 | `POST /api/admin/production/orders/{orderId}/print`（生产侧打印入口） | `backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java` |

---

## 3. 锁定裁定表（**已拍板，本文不得自行改判**）

### 3.1 #5052 累计 11 条（评论 4 轮裁定记录，逐条落进本设计）

| # | 议题 | 裁定 | 落在本文 |
|---|---|---|---|
| 1 | 入库粒度 | **按 SKU**（一个入库单行 = 一个 SKU；沿用 #5045 的行粒度与批次口径） | §4、§5、§11 |
| 2 | 标签载体 | **布卷 / 塑料袋** ⇒ 合成纸 + **强粘永久胶** | §7.4 |
| 3 | 标签尺寸 | **50mm × 30mm** | §7.1 |
| 4 | 识别与确认 | **AI 识别 + 人工确认**（**不做免确认**） | §4、§6.5、§11 |
| 5 | 操作者 | **工人** ⇒ `/api/worker/inbound/**`（能力保留、载体分离） | §5 |
| 6 | 打印通道 | **方案 ②（随身打）** —— 理由逐字「不是固定的，工人频繁移动」 | **§8（本文对它的立论提出改判动议，但裁定本身未被本文推翻 ⇒ §13 待裁定 1）** |
| 7 | 首版范围 | **一步到位（含入库单过账）** —— 不做两步走 | §4、§10 |
| 8 | 非整数米 | **并入「库存米数小数化」改动**（不在本单内自造折中） | §2.1 订正块（**该改动已闭环**） |
| 9 | 离线 | **不支持离线 —— 必须联网** | §8.3、§11、§12 |
| 10 | 设备形态 | **手机（工人自有安卓机）+ 便携蓝牙标签机**；一体机（岳冉 HA550D）为**人体工学备选** | §3.2、§13 |
| 11 | 交付物 | 含 **Android 壳 App**（WebView + JS Bridge + 蓝牙 SPP/BLE）—— 已拆到 **#5061** | **§8（改判动议对象）**、§13 |

### 3.2 BYOD（工人自有手机）带来的 5 条新约束（**必须进设计，逐条落码口径**）

| # | 约束（#5052 评论逐字口径） | 本设计的落法 |
|---|---|---|
| B1 | **安全边界必须在服务端** —— 手机在工人手里、装不了 kiosk、随时能切出去 ⇒ **壳 App 不是安全边界** | **窄接口（只入库、不接受负数、不接受任意 `adjustment`）+ 幂等键 + 打印计数 + 审计**四条从「好习惯」升级为**唯一防线** ⇒ §5.2、§9 |
| B2 | **设备差异 ⇒ 拍照识别成功率不一致** —— 工人手机 5MP 到 1 亿像素都有，光线/对焦差异大 | H5 侧**拍照质量提示（太暗/太模糊就提示重拍）**；AI **不确定就不预填**（沿用既有降级判据）⇒ §6.4、§11 |
| B3 | **安装门槛** —— 企业内部分发 apk 需开「未知来源安装」，部分厂商 ROM 会拦 | 需**安装指引页**；或后续 MDM ⇒ **§13 待裁定 4** |
| B4 | **会话撤销** —— 离职 / 换手机必须能立即踢掉 | **复用**既有 `worker_sessions` 的**结束 + 闲置超时**机制（#4733 已落码），**不新造** ⇒ §9.3 |
| B5 | **隐私与制度** —— 私人手机拍公司货物、照片上传到公司 OSS | 制度与隐私告知 + 技术侧**图片保留期** + **只存必要字段** ⇒ §9.4 |

### 3.3 设备选型调研结论（#5052 评论，**采购侧输入，非代码交付**）

| 项 | 口径 |
|---|---|
| **第一候选机型** | **德佟 DETONGER DP30S** —— 列为**便携蓝牙标签机的第一候选**，理由 = SDK 可验证性优于其他候选（官网导航含 **LPAPI**，华为生态市场有 LPAPI SDK 上架；有公开第三方封装 `cordova-plugin-lpapi`、Flutter 包 `flutter_dothantech_lpapi_thermal_printer`） |
| DP30S 的 **4 条必须先向厂商确认** | ① **最大打印宽度 / 纸宽**（203dpi 的 2 英寸头通常有效打宽 **48mm/384dots**，而我们要 **50mm** ⇒ 右侧约 2mm 打不到 ⇒ 对策：**50×30mm 纸 + 有效版心 ≤48mm**，或直接改 48×30mm 纸）② 是否支持**黑标（black mark）检测**（价格标签机常只支持**间隙定位**）③ **亚银必须是「热敏亚银」**（普通亚银 PET 需碳带，而 DP30S 是**热敏机、不带碳带** ⇒ 买错耗材打不出字）④ **热敏耐久性 ≠ 不翘边**（「酒精擦洗不翘边」说的是**胶**，不代表热敏涂层不掉字 ⇒ 仓库长期摩擦/酒精/暴晒要**实测褪色**，或改碳带机型） |
| **仍未核实（需厂商索取）** | 打印宽度精确值（dots/mm）、纸宽范围、**最小标签高度**、打印头寿命、电池容量与满电连续打印张数、重量、打印速度、防护等级、价格与阶梯价、交期、质保、备件供应年限 |
| **样机验收三步** | ① 打 50×30mm 热敏亚银 100 张看定位与黑标/间隙；② 贴**布卷曲面**与 **PE 袋** 24h；③ 用 LPAPI 从手机蓝牙打一张**服务端位图**（验证「位图直打」这条最省事的路径成不成立） |
| **`cordova-plugin-lpapi` 的意义** | 壳 App **几乎有现成骨架**（Cordova 默认形态 = WebView + 插件）⇒ 壳工作量可能从「几周」降到「几天」；**这条比机器价格更影响项目周期** |
| **采购清单（方案 ②）** | 便携蓝牙标签机：**2 英寸（介质宽 57~58mm，够打 50mm）**、**TSPL** 指令集、**BLE + SPP 都支持**、可换电池或 Type-C 边充边打、**≤600g**、**IP54+**、有 Android SDK 或指令手册；手机：**安卓机**（后摄 ≥1300 万 + 自动对焦 + 闪光灯） |
| **耗材（与机器同等重要，先问耗材再定机器）** | 逐字「**50mm×30mm 三防热敏合成纸不干胶 + 强粘永久胶**（布卷曲面 / PE 袋低表面能，普通胶会翘边，不可移胶）」—— 注意是**强粘永久胶**，**不可移胶** |
| 采购前 8 问（一体机路线的口径，**若回退到一体机仍适用**） | ① 纸仓可打宽度范围（能否稳定打 **50mm×30mm**）② 黑标/间隙检测与间隙下限（需 ≤2mm）③ 打印头寿命 + 胶辊更换周期与单价 ④ 电池容量 + 满电连续「拍照+打印」张数、能否换电池 ⑤ 防护等级（IP）+ 跌落高度 + 工作温度 ⑥ SDK：是否免费、有无中文文档与样例、**3 天内能否跑通打一张 50×30 标签**（最大进度风险）⑦ 4G 频段 + WiFi 双频（**无离线兜底 ⇒ 网络是硬前提**）⑧ 价格（1/10/100 台阶梯）+ 交期 + 质保 + 备件供应年限（≥3 年） |

### 3.4 本包新增的裁定（**2026-09-26，据转述**）

| # | 议题 | 裁定 | 不确定度标注 |
|---|---|---|---|
| 12 | **B 端前端载体统一** | **统一到 `frontend/bmini-app`**（Taro 4.2.1，`@tarojs/plugin-platform-h5@4.2.1` 已安装、`config/index.ts` 有 `h5` 段 ⇒ **一端双编译 weapp + h5 是现成能力**） | 【实测】**能力面已复核**（§2.4）；「用户逐字裁定」本身【转述】 |
| 13 | **`frontend/worker-h5` 定位** | **保留为「扫码直达免安装」轻入口，不重写**（已部署 `app.migaozn.com/w/`，走 `/s/{短码}` 扫码直达） | 【实测】部署形态与同源调用已复核（§2.4）；「保留」的裁定本身【转述】 |
| 14 | **打印通道改判动议** | 不构成裁定 —— **须先核实 DP30S 的 BLE 口是否开放**（厂商书面 + 样机实测）⇒ **§13 待裁定 1** | §8.4、§8.5 |

---

## 4. 端到端链路（每步标清「谁做 / 在哪做 / 真值在哪」）

| 步 | 动作 | 谁做 | 在哪做 | **真值在哪** |
|---|---|---|---|---|
| 1 | 拍**上游标签**（布卷/包装原有标签）+ 可选的布卷/外包装照 | **工人** | `frontend/bmini-app` 的 h5 编译产物（§3.4 裁定 12） | 原图 = OSS 对象；**元数据**（谁/何时/哪个租户）由服务端从工人 session 解 |
| 2 | **条码/二维码解码优先** | 前端（浏览器/小程序运行时） | **设备侧**（前端库，**0 次 LLM 调用**） | 解码结果 = **候选**，**非真值**（可能扫到别的码） |
| 3 | 解码失败 ⇒ **vision 兜底** | 米宝 agent | 服务端 `backend/ai-agent-service`（`app/vision/recognizer.py`） | 识别结果 = **候选**（带不确定度），**非真值** |
| 4 | 两条路都不行 ⇒ **工人手输** | 工人 | 设备侧表单 | 工人输入 = **待确认值** |
| 5 | **SKU 匹配门禁**（品名 + 色号必须命中既有 `product_skus`） | 服务端 | admin-api | 🔴 **`product_skus` 是唯一真值**；零命中 ⇒ **拒绝入库、不自动建品**（§6.3） |
| 6 | **回显 + 引导确认**（交互卡 / 逐字段追问；**不确定不预填**） | 米宝 agent + 工人 | 服务端出卡 / 设备侧确认 | 工人**确认动作本身**落库（未确认不落库，§11） |
| 7 | **建单草稿**（不动库存） | 服务端 | `/api/worker/inbound/**` → **复用 #5045 的 `InboundOrderService.create`** | `inbound_orders` / `inbound_order_items`（草稿态） |
| 8 | **提交过账** | 服务端 | 同上 → **复用 `InboundOrderService.post`**（**本单不新造任何库存增减逻辑**） | 🔴 **过账才动库存**：`product_skus.stock` + `stock_ledger_entries`（`reason='inbound'`）+ `stock_batches`（批次号 + 移动加权平均成本） |
| 9 | **出标签位图** | 服务端 | admin-api（新端点） | 位图 = **服务端单一真值源**（设备侧只负责「把这张图打出来」）；**50×30mm**，像素口径见 §7.2 |
| 10 | **打印** | 设备侧（三个候选通道，§8） | 小程序 BLE / 浏览器 Web Bluetooth / 壳 App | 🔴 **打印前必须先调服务端端点**（`print_count` 原子自增 + 审计），**设备侧不得本地直打绕过**（§9.2） |
| 11 | **留痕** | 服务端 | admin-api | `print_count` + `audit_logs`（§7.3）；**标签短码落库**，撤销**置 NULL** ⇒ 扫码 **410** |
| 12 | 贴标 | 工人 | 现场 | 标签上的码 = `https://app.migaozn.com/i/<短码>`（**一次定死**，§7.1） |

**三条不变量（本设计的骨架）**：
1. **入库单是入库的唯一载体**（不新造库存增减逻辑）—— §5.3；
2. **过账才动库存**（建单是草稿）—— 沿用 #5045 口径；
3. **设备侧永远不是真值源**（识别结果是候选、位图由服务端出、计数与审计在服务端）—— 与 B1「壳 App 不是安全边界」同源。

---

## 5. 工人可达面设计（**新端点清单**）

### 5.1 现状缺口（这是本单**必须新建**的部分）

**实测结论**：`/api/worker/**` 现有端点（§2.2）**没有任何**图像识别 / 标签解析 / 入库端点；
唯一可用的识别控制器 `backend/admin-api/src/main/java/com/migao/admin/controller/ImageRecognitionController.java` 挂在
`/api/admin/image-recognition`，且**权限码按 target 取**（`product:create` / `order:create`）
⇒ 工人**双重被拒**：① 路径被 `ADMIN_API_REJECTED_ROLES`（含 `worker`）拒；② 即便放行，工人**零商家权限码**，`requirePermission` 仍拒。

🔴 ⇒ **「工人拍照识别」这条链必须新建工人可达入口**；**不得**通过给工人挂商家权限码来「复用」现有端点（那正是 #4727 要防的形态）。
另注：现有识别控制器的 `targetType` 只认 `product` / `order`，**未知 target 一律 400 fail-closed** ⇒ 入库识别**不能**靠新增一个 target 塞进它（那会把商家写码语义带进工人路径）。

### 5.2 新端点清单（`/api/worker/inbound/**`）

> 全部走**工人 session**（复用 #4733 的 `worker_sessions`）；**全部不接受商家权限码**（不是「有码就放行」，而是**这条路径根本不查商家码**）。

| 方法 | 路径 | 语义 | 拒绝口径（**每条都要能红**） |
|---|---|---|---|
| `POST` | `/api/worker/inbound/recognize` | 上传照片（1~3 张）→ 解码优先 / vision 兜底 → 回**候选**（品名/色号/米数/条码原文 + 不确定度）；**不落库、不动库存** | 无/过期工人 session ⇒ 401；非图片或超 3 张 ⇒ 400；图片超尺寸 ⇒ 400；**任何情况下不返回「凭空构造的 SKU」**（只回候选 + 是否需要人工确认） |
| `POST` | `/api/worker/inbound/drafts` | 建**入库单草稿**（一个入库单行 = 一个 SKU）；**复用 `InboundOrderService.create`** | **负数 / 0 / 超 1 位小数 ⇒ 400**（沿用 #5063 判据：`> 0` 且最多 1 位小数）；`skuId` 不存在或**零命中匹配** ⇒ 400/409，**不自动建品**；请求体**没有** `adjustment` / `reason` / `operator` 这类字段（**结构上不可表达**） |
| `POST` | `/api/worker/inbound/drafts/{id}/post` | **提交过账**（过账才动库存）；**复用 `InboundOrderService.post`**；带 `Idempotency-Key` | 未确认（缺人工确认标记）⇒ 409；非本人/非本租户草稿 ⇒ 404；同 `Idempotency-Key` 重复提交 ⇒ **幂等命中，不再加库存**（回同结果）；已过账再提交 ⇒ 409 |
| `GET` | `/api/worker/inbound/labels/{shortCode}/bitmap` | 出**标签位图**（PNG，50×30mm，像素口径 §7.2） | 跨租户 ⇒ **404**（不是 403，避免存在性泄露）；**已撤销 ⇒ 410**；归属非本人可打范围 ⇒ 403 |
| `POST` | `/api/worker/inbound/labels/{shortCode}/print` | **打印计数原子自增 + 审计留痕**（设备侧打印**前**必须先调它） | 未登录 ⇒ 401；已撤销 ⇒ 410；同短码并发调用 ⇒ **计数不丢**（原子自增） |
| `GET` | `/i/{shortCode}` | **公开**短码入口（302 到落地页 / 410） | 不存在 ⇒ 404；已撤销 ⇒ **410**；**公开入口必须绕过多租户拦截器**（照 `WorkerShortLinkService` 既有注释的口径），但**只回跳转、不泄露业务字段** |

### 5.3 三条硬约束

1. **只表达入库语义**：请求体**结构上**不接受任意 `adjustment`、**不接受负数**、不接受「把库存改成 N」（**不是靠校验拒绝，而是根本没有这个字段**）。
2. **内部复用 #5045 的过账服务方法**（`InboundOrderService.create` / `post` 签名见 §2.1）——**不新造库存增减逻辑**，**不直接写** `stock_ledger_entries`。
3. **能力保留、载体分离**（照 #4727 先例）：工人**走 `/api/worker/inbound/**`**，**零商家权限码**。

### 5.4 入口衔接（**登记缺口，本文不拍板**）

**实测**：`frontend/worker-h5` 是**零依赖纯 H5**（无 `package.json`），其唯一写入口是 `POST /api/worker/production/scan/complete`；
而路径 `/s/{短码}` 302 落到 **`/w/`**（`WorkerShortLinkService.REPORT_PAGE_PATH`）。
⇒ 若拍照入库链按裁定 12 落在 `frontend/bmini-app`，则**工人的「扫码直达」入口（`/w/`）与「拍照入库」页面（bmini-app h5）不在同一个应用里** ——
**衔接方式**（在 `/w/` 页给一个去入库页的入口 vs 入库另配短码入口）**未定**，登记在此，由**实现 PR** 处置（**不要**为了衔接把 `worker-h5` 重写成有依赖的工程 —— 与裁定 13「不重写」冲突）。

---

## 6. 识别策略（**解码优先 → vision 兜底 → 手输**）

### 6.1 第一优先：条码/二维码**前端解码**（0 次 LLM 调用）

| 项 | 口径 |
|---|---|
| 库 | `jsQR` / `ZXing-js`（**前端解码，0 次 LLM 调用**） |
| 现状 | ❌ **全仓零命中**（§2.3 实测）⇒ 需要**新增依赖**；落在 `frontend/bmini-app`（裁定 12 的载体） |
| 为什么必须这样 | 成本守卫：照片含可解条码时**不得**走 LLM（§11 有对应判据，能红） |
| **已知缺口（登记）** | 现有扫码只用 `Taro.scanCode({ scanType: ['qrCode'] })`（**weapp 侧能力、且只扫二维码**）⇒ **h5 编译产物下没有微信 JSSDK 兜底**，「拍照 → 前端解码」这条等价路径必须在**实现 PR** 里落实（`<input type="file" capture>` / `Taro.chooseImage` + 解码库）。**本文不拍板实现方式**，只钉住判据 |

### 6.2 第二优先：vision 兜底

- 复用 `backend/ai-agent-service/app/vision/recognizer.py` 的 `recognize(...)`（内部 `LLMFactory.create_vision_llm()`）；
- **调用上限 3 张图**（沿用现状，`app/api/upload.py`）；
- **vision 只在解码失败后触发**（顺序由服务端控制，不由设备侧决定）。

### 6.3 🔴 SKU 匹配门禁（**防 AI 幻觉造出假 SKU**）

| 判据 | 口径 |
|---|---|
| 命中条件 | 识别出的**品名 + 色号**必须**命中既有 `product_skus`**（唯一真值，§2.1） |
| 零命中 | **拒绝入库、不自动建品** —— 不落库、不建商品、不建 SKU、**不落任何台账** |
| 为什么 | AI 幻觉造出的假 SKU 会**带着库存流水**进系统：库存对不上账，且**没有任何东西会变红**（最贵的坏形态） |
| 多命中/歧义 | 由**工人确认**消歧（裁定 4：AI 识别 + 人工确认）；**不许**服务端替工人猜 |

### 6.4 不确定 = 不预填（B2 的落法）

- vision 返回**降级 / 不确定**文案 ⇒ **不预填**、提示人工录入（**不编造**）；
- 设备侧（B2）：**拍照质量提示** —— 太暗 / 太模糊就提示重拍（不同手机像素与对焦差异极大，**这是识别率的第一个变量**）。

### 6.5 不做免确认

裁定 4 逐字落地：**AI 识别 + 人工确认**，**跳过人工确认直接提交 ⇒ 拒绝**（§11 有判据）。
⇒ 服务端必须能**区分**「有工人确认」与「无工人确认」的提交（不能只靠前端按钮形态）。

---

## 7. 标签设计

### 7.1 版式与码形态（**域名/路径一次定死**）

| 项 | 口径 | 理由 |
|---|---|---|
| 尺寸 | **50mm × 30mm**（裁定 3） | 布卷 / 塑料袋可贴面 |
| 版式范式 | 照 #4946：`@page { size: 50mm 30mm; margin: 0 }` + 固定尺寸容器 + `overflow: hidden` + **每张独占一页** | 复算参照：`frontend/admin-web/src/components/production/TaskCardPrint.tsx` |
| 长名截断 | **按规则截断，不静默裁切**（截断必须可见：省略号或显式标注） | 「静默裁切」= 账实不符的另一种形态 |
| **码形态** | **`https://app.migaozn.com/i/<短码>`** | 🔴 **一次定死**：码一旦打印就是 URL，**换域名 / 改路径会让已打印的码全部失效** |
| 短码规格 | 沿用 `WorkerShortLinkService` 同款口径：**8 位、字母表 `0123456789ABCDEFGHJKMNPQRSTVWXYZ`（去 `I/L/O/U`，人可读可抄）** | 与既有工人短码**同族但不同表**（#5052 边界：「照其范式、不复用其表」） |
| 🔴 **`/i/` 是新码空间** | **实测全仓零命中**（§2.4）⇒ **不得**与既有 `/s/` 混用；`/s/` 是**工人报工短链**（302 → `/w/?t=`），`/i/` 是**入库标签** | 两个码空间语义不同，混用会把「扫标签」变成「进报工页」 |
| **缺码不画假码** | 未拿到短码（服务端未生成 / 生成失败）⇒ **显式报错或留空位并标注**，**绝不画占位二维码** | 假码扫出来是错的 ⇒ 比没有码更坏 |

### 7.2 位图像素口径（**与目标机 dpi 绑定**）

| 项 | 值 | 说明 |
|---|---|---|
| 纸宽 | 50mm | 裁定 3 |
| dpi / 步进 | **203dpi = 8 dots/mm** | DP30S 口径 |
| 全宽像素 | **400px**（50mm × 8） | 若机器能打满 50mm |
| **有效打印宽** | **48mm ⇒ 384px** | 203dpi 的 2 英寸头常见有效打宽 |
| 高度像素 | **240px**（30mm × 8） | — |
| 出图口径 | **服务端按目标机 dpi 精确出图**，**1:1 不缩放不裁切** | 位图 = 服务端**单一真值源**；设备侧只负责「把这张图打出来」 |
| ⚠️ **待核** | DP30S 的**精确打印宽度（dots/mm）**与纸宽范围 | §3.3「4 条必须先确认」之①；**未核实前按有效版心 ≤48mm 设计**（安全侧） |

### 7.3 打印计数 / 审计 / 撤销（**复用既有范式，不新造**）

| 机制 | 口径 | 参照 |
|---|---|---|
| `print_count` | **原子自增**（`COALESCE(print_count,0)+1` 同款口径），**并发不丢计数**；**重打同样计数** | `backend/admin-api/src/main/resources/db/init/schema.sql` 的 `processing_set_part_tokens.print_count` 列注释 |
| 审计 | 每次打印落 `audit_logs`（谁 / 何时 / 哪个短码 / 第几次） | `backend/admin-api/src/main/java/com/migao/admin/service/AuditLogService.java` |
| 撤销 | 撤销标签 ⇒ **短码置 NULL** ⇒ 扫码 **410** | 照 #4946 口径 |
| 打印必留痕 | 设备侧打印**前**先调服务端端点；**壳/前端不得本地直打绕过** | §5.2 的 `POST .../print`；#5061 同款约束 |

### 7.4 介质与耗材（**采购侧，与机器同等重要**）

**50mm × 30mm 三防热敏合成纸不干胶 + 强粘永久胶** —— 布卷曲面与 PE 塑料袋**都是低表面能表面**，普通胶会翘边，**不可移胶**。
⚠️ 若走 DP30S：**必须是「热敏亚银」（合成纸）**，不能用普通亚银 PET（需碳带，而 DP30S 是热敏机）——§3.3 确认项③。

---

## 8. 打印通道（**改判章**）

> 🔴 **本章是本文相对 #5052 **唯一**提出改判动议的地方，且**本文不自行拍板** ——
> 原裁定 6 / 11（方案 ② 随身打 + Android 壳 App）**逐字保留**（§3.1），**是否改判进 §13 待裁定 1**。
> 本章只做三件事：**给出新证据**（§8.2）、**列三个候选分支与各自覆盖缺口**（§8.3）、**登记未核实项**（§8.5）。

### 8.1 原「方案 ②」的立论（#5061 逐字）

> 「浏览器**驱动不了**蓝牙标签机：Web Bluetooth 只支持 BLE（不支持经典蓝牙 SPP）、iOS Safari 不支持、微信小程序也不支持 SPP。
> ⇒ 「手机端点打印」这一步**网页自己做不到**，必须由一个装在手机上的原生 App 承接。」

### 8.2 新证据：德佟（DothanTech / DETONGER）已在 npm 发布**整条 BLE SDK 矩阵**

**本次实测**（`npm view <pkg> version time.modified homepage repository.url`，2026-09-26，见附录 A）：

| npm 包 | 目标平台 | 最新版本 | `time.modified`（实测） | `homepage`（实测） |
|---|---|---|---|---|
| `lpapi-ble-wx` | **微信小程序 BLE** | **1.7.260715** | 2026-07-17 | `https://thanmore.net` |
| `lpapi-ble` | **浏览器 Web Bluetooth** | **1.7.260618** | 2026-06-24 | `https://thanmore.net` |
| `lpapi-ble-uni` | uni-app | 1.7.260715 | 2026-07-17 | `https://thanmore.net` |
| `lpapi-ble-ww` | 企业微信 JS-SDK | 1.7.260618 | 2026-06-24 | `https://thanmore.net` |
| `lpapi-ble-cdv` | Cordova（BLE） | 1.5.251216 | 2025-12-18 | **`https://www.dothantech.com`** |
| `lpapi-spp-cdv` | Cordova（经典蓝牙 SPP） | 1.5.251107 | 2025-11-07 | **`https://www.dothantech.com`** |
| `dtpweb` | 打印助手（兜底） | 2.7.260720 | 2026-07-21 | `https://thanmore.net` |
| `lpapi-dtpweb` | 打印助手（兜底） | 1.7.260909 | 2026-09-09 | `https://thanmore.net` |
| `cordova-plugin-lpapi` | Cordova 插件（= #5061 原方案） | 1.7.0 | 2025-02-13 | `https://github.com/GemHu/LPAPIPlugin` |

**包结构实测**（`lpapi-ble-wx`）：`main` = `lib/index.umd.js`、`module` = `lib/index.js`、`types` = `lib/index.d.ts`、
`dependencies` = `{ "lpapi-ble": "^1.5.260618" }`（**依赖 `lpapi-ble` 核心包**）、`description` = 「蓝牙打印接口」。
**`lpapi-ble`（核心）实测**：`main` = `libs/index.umd.js`、`module` = `libs/index.esm.js`、`types` = `libs/index.d.ts`、
`description` = 「一款基于浏览器自带蓝牙的标签打印接口」。`dtpweb` 的 `description` = 「interface of DothanTech print service」。

**⇒ 推论（改判动议的核心）**：若标签机支持 **BLE**（**#5052 的采购清单里本来就要求「BLE + SPP 都支持」**），
则「**小程序内直打**」成立 ⇒ **#5061 的整个 Android 壳 App 从「必须」降级为「iOS 浏览器 / 非微信环境的兜底」，甚至可退役。**
理由：BLE 是**标准 GATT**，小程序/浏览器/iOS 都是**各自运行时的 BLE 客户端**，**原立论依赖的「SPP 只有原生能做」这一条对 BLE 不成立**。

⚠️ **但结论的成立有条件**（不满足则动议不成立，退回原裁定）：见 §8.5 的三条未核实项。

### 8.3 三个候选分支对比（**含各自覆盖缺口**）

| 项 | **A. 小程序 BLE 直打**（`lpapi-ble-wx`） | **B. 浏览器 Web Bluetooth**（`lpapi-ble`） | **C. Android 壳 App 兜底**（#5061 原方案） |
|---|---|---|---|
| 载体 | `frontend/bmini-app` 的 **weapp** 编译产物 | `frontend/bmini-app` 的 **h5** 编译产物 | 新增 Cordova/Android 工程（#5061） |
| 是否需装 App | **不需要**（微信内即用） | **不需要** | **需要**（apk + 未知来源安装） |
| 覆盖的工人面 | **微信用户**（国内安卓 + iOS **都能用**，因走微信运行时） | **桌面 Chrome/Edge + 安卓 Chrome** | **安卓**（含非微信环境） |
| 🔴 **覆盖缺口 1** | **非微信环境**（没装微信 / 用企业微信外的浏览器打开）⇒ 打不了 | **iOS Safari 不可用**（§8.5 ③）⇒ **iPhone 全灭** | iOS 亦无（#5061 未做 iOS 壳） |
| 🔴 **覆盖缺口 2** | 依赖**微信 BLE 权限与机型适配**（安卓 ROM 差异） | 依赖**浏览器版本**与 **HTTPS + 用户手势**要求 | 依赖**安装成功**（B3：ROM 拦未知来源） |
| 覆盖缺口 3 | 仍受**联网**硬约束（裁定 9） | 同左 | 同左 |
| 新增工程量 | **最小**（加依赖 + 一个打印适配层） | 小（同左，h5 分支） | **最大**（新工程 + 蓝牙适配调试 + 权限引导 + 分发） |
| 与裁定 12（统一到 bmini-app） | ✅ **天然一致**（就是 bmini-app 的 weapp 端） | ✅ **天然一致**（就是 bmini-app 的 h5 端） | ⚠️ 不一致（另开工程） |
| 与裁定 11（交付物含壳 App） | ⚠️ **若退役则与裁定 11 冲突 ⇒ 必须由用户裁定**（§13 待裁定 1） | 同左 | ✅ 一致 |
| 复用既有范式 | `Taro.scanCode` 同工程；H5 能力探测照 #5061（`window.LPAPI` → 统一 `migaoPrint(payload)`） | 同左 | #5061 已设计（JS Bridge + 权限引导） |
| 结论（**动议**） | **首版首选**（若 §8.5 ① 成立） | 作为**桌面/安卓浏览器**补充 | **降级为 iOS / 非微信环境的兜底**，甚至退役 |

🔴 **三个分支的共同洞 = iOS 浏览器**（A 靠微信运行时绕开、B 撞 Apple 未实现 Web Bluetooth、C 本来就没做 iOS）
⇒ **「iOS 工人怎么办」是绕不开的独立裁定**（§13 待裁定 2；原 #5061 待裁定 1 仍悬着）。

**唯一「零 App 且零 BLE」的希望（采购时问一句，照 #5052 既有口径）**：
若标签机支持 **IPP / AirPrint / Mopria**（通常是**网口/WiFi 机型**，便携蓝牙机基本不支持），则系统打印服务可直接打
⇒ 但 **50×30mm 的尺寸与间隙控制依赖打印服务/驱动**，必须实测；且机型从「便携蓝牙」变「便携 WiFi」，选择面小很多。
**值得问，但不要指望。**

### 8.4 🔴 来源与不确定度（**不许把「npm 上有包」写成「厂商官方支持」**）

**照实登记的观察**（本次实测，只陈述读到的字段，不推断归属）：

1. **`-ble-*` 全家与 `dtpweb` 的 `homepage` = `https://thanmore.net`**，而德佟官网是 `detonger.com` / `dothantech.com`
   ⇒ **域名不一致** ⇒ **不能据此断定是厂商官方发布**；
2. 但 **`lpapi-ble-cdv` / `lpapi-spp-cdv` 的 `homepage` = `https://www.dothantech.com`**（= 德佟官网）
   ⇒ **同一矩阵内部不一致**：Cordova 两支指向厂商域名，BLE 四支指向 `thanmore.net`；
3. `-ble-*` 各包的 `repository.url` 实测为 **UNC 内网路径**（形如 `\\server\GitRoot\Web\weida`），**不是**公开 git 仓库
   ⇒ 说明发布方有内部构建流程，但**仍不足以证明「厂商官方」**；
4. `cordova-plugin-lpapi` 的 `repository.url` = `git+https://github.com/GemHu/LPAPIPlugin.git`
   ⇒ 这是**公开第三方个人仓库**（与 #5052 评论「有公开第三方封装」的措辞一致），**不是**厂商官方包；
5. `dtpweb` 的 `description` 逐字含 **`DothanTech`** ⇒ 弱证据（**是线索，不是结论**）。

⇒ **本设计的写法**：**只能**说「npm 上存在覆盖小程序/浏览器/uni-app/企业微信的 BLE SDK 矩阵，且与德佟 LPAPI 同名同族」，
**不能**说「德佟官方支持小程序直打」。**官方性必须向厂商书面确认**（§8.5 ②）。

### 8.5 未核实项清单（**改判动议成立的前置**）

| # | 未核实项 | 为什么必须核实 | 核实方式 | 不成立的后果 |
|---|---|---|---|---|
| ① | **德佟 DP30S 的 BLE 口是否开放、能否用 `lpapi-ble-wx` 直打** | 整个改判动议的**唯一支点**：机器若只开放 SPP（或 BLE 口被固件锁），A 分支**直接不成立** | **厂商书面确认 + 样机实测**（样机验收第③步：用 LPAPI 从手机蓝牙打一张服务端位图，**改成用小程序端打**） | 退回原裁定（C 分支 = Android 壳 App），§8.3 的「工程量最小」优势消失 |
| ② | 这些 npm 包是**厂商官方**还是**第三方封装** | 「官方支持」意味着**长期维护 + 兼容性承诺**；第三方封装可能停更（`cordova-plugin-lpapi` 最后更新 2025-02-13，**已近 1.5 年**） | 向厂商书面确认；或核对厂商官网 SDK 下载页是否指向 npm 包名 | 包停更 ⇒ 适配成本回流到我们；但**首版仍可用**（可 vendor 锁定版本） |
| ③ | **`lpapi-ble`（Web Bluetooth）在 iOS Safari 不可用** | 决定 B 分支能不能算「覆盖 iOS」 | 外部资料（[caniuse Web Bluetooth](https://caniuse.com/web-bluetooth)：Safari 未实现；Apple 侧长期只有第三方 App/扩展绕行，如 [beacio](https://apps.apple.com/au/app/beacio/id6761301368)）；**本次未在真机实测** | iOS 覆盖只能靠 A 分支（微信运行时）或公司配机 ⇒ 直接决定 §13 待裁定 2 |
| ④ | DP30S 精确打印宽度（dots/mm）与纸宽范围 | 决定 50mm 能否打满 / 是否必须改 48×30mm 纸（§7.2） | 厂商书面答复 + 样机打 100 张看定位 | 版心口径要改（**安全侧已按 ≤48mm 设计**，故不阻塞） |
| ⑤ | 热敏亚银（合成纸）在布卷曲面 / PE 袋的 24h 附着与**褪色**实测 | 耗材买错 = 打不出字 / 标签掉（§3.3 确认项③④） | 拿样品试贴 + 酒精/摩擦实测 | 耗材返工（采购侧成本，不影响代码结构） |

---

## 9. 安全边界（**BYOD：服务端是唯一防线**）

### 9.1 前提（B1 逐字含义）

**手机在工人手里、装不了 kiosk、随时能切出去 ⇒ 壳 App / 小程序 / 页面都不是安全边界。**
⇒ 原方案的「窄接口 + 幂等 + 计数 + 审计」四条，**从「好习惯」升级为「唯一防线」**。

### 9.2 四条防线（**逐条给落点**）

| 防线 | 落点 | 能红的判据（§11） |
|---|---|---|
| **窄接口** | §5.2 六个端点：**只表达入库语义**；结构上无 `adjustment`、无负数、无「设为 N」 | 传负数 / 任意 `adjustment` ⇒ 拒绝 |
| **幂等键** | 建单与过账都带 `Idempotency-Key`；复用 #5045 既有幂等（`V117__inbound_order_idempotency_and_source.sql`） | 同键重复提交 ⇒ 库存只加一次、台账只有一行 |
| **打印计数** | `print_count` **原子自增**（服务端端点，设备侧打印前必调） | 并发打印不丢计数；**设备侧直打绕过 ⇒ 无计数**（判据要求「打印必留痕」） |
| **审计** | `print_count` + `audit_logs` 双留痕；短码落库、撤销**置 NULL** | 每次打印有审计；撤销后扫码 410 |

### 9.3 工人零商家权限（**红线**）

- 工人**一律没有** `inbound:view` / `inbound:create`（更没有任何其它商家权限码）；
- 工人 session 打 `/api/admin/**` **任一端点** ⇒ 拒绝（`ADMIN_API_REJECTED_ROLES` 含 `worker`）；
- **不许**给工人挂 `inventory_manage` 之类的码来「复用」商家端点 —— 那等于**变相给商家权限**（#4727 的病灶）；
- 米宝（agent）**只做识别，不做写入**：**工具集只含识别与查询类，不含任何库存写入工具**（#5052 范围 2 逐字）。

### 9.4 会话与隐私（B4 / B5）

| 项 | 口径 |
|---|---|
| **会话撤销**（B4） | **复用**既有 `worker_sessions` 的**结束 + 闲置超时**（#4733 已落码），**不新造**；离职/换手机能立即踢掉 |
| **隐私与制度**（B5） | 工人私人手机拍公司货物、照片上传 OSS ⇒ **制度与隐私告知**必须明确；技术侧：**图片保留期** + **只存必要字段** |
| 图片上限 | 每次识别最多 **3 张**（沿用现状，§2.3） |

---

## 10. 依赖与阻塞（**照实登记**）

### 10.1 依赖状态（**2026-09-26 复核**；凡标「据转述」者为待核）

| 依赖 | 状态 | 对本单的意义 |
|---|---|---|
| **#5045 入库单（建单/过账/批次/移动加权成本/`inbound:view`·`inbound:create`）** | ✅ **CLOSED 且代码在**（【实测】§2.1） | **前置已解** ⇒ 本单**可以**落库存接线（裁定 7「一步到位」不再被它卡住） |
| **#5063 库存米数小数化** | ✅ **CLOSED**（【实测】`NUMERIC(12,1)` 已是现状） | 裁定 8 的依赖**已解** ⇒ 非整数米**不再是阻塞**（§2.1 订正块） |
| **#4946 洗水码 30×60mm 版式 + `print_count` + 短链** | ✅ **CLOSED**（【实测】`TaskCardPrint.tsx` + `print_count` 列） | 标签范式**照抄**（本单不复用其表） |
| **#4733 工人登录态（工号 + PIN，服务端解身份）** | ✅ **CLOSED**（【实测】`WorkerAuthController`） | 工人可达面的身份底座 |
| **#4727 工人零商家权限** | ✅ **CLOSED**（【实测】`ADMIN_API_REJECTED_ROLES` 含 `worker`） | §9.3 的机制底座 |
| **#4716 工人端 H5 设计** | ✅ **CLOSED**（【实测】`frontend/worker-h5` 在） | `worker-h5` 的既有形态（裁定 13 保留它） |
| **🔴 #4869 没有任何产品路径能创建工人档案** | ❌ **OPEN，正在修**（另一个包在做；【实测】issue 状态） | **唯一未解阻塞**：首个工人建不出来 ⇒ 工人登录不了 ⇒ **本单在真实部署里无法交付使用**。**POC 阶段可先用开发手段直插一条工人档案**（#5052 既有口径） |
| `#5061` Android 壳 App | OPEN（【实测】） | **§8 改判动议的对象**；动议成立则降级为兜底或退役 |
| `#4924` 米宝读库存流水 | OPEN（#5052 判为**不在本单**） | 本单不修；但**「不确定就不预填」的判据不依赖它** |

### 10.2 尚未落码的能力清单（**本单要实现的部分**）

1. `/api/worker/inbound/**` 六个端点（§5.2）—— **现有零覆盖**（§5.1 实测缺口）；
2. 前端解码依赖（`jsQR` / `ZXing-js`）—— **全仓零命中**（§2.3）；
3. `/i/{短码}` 码空间 —— **全仓零命中**（§2.4）；
4. `frontend/bmini-app` 的**拍照入库页**（weapp + h5 双端）—— 现有 `pages/worker/` 只有登录页（§2.4）；
5. 入库标签表（`print_count` / 短码 / 撤销）与位图端点；
6. 打印适配层（§8 三选一，**待裁定 1**）。

### 10.3 阻断与非阻断（**别把两者混为一谈**）

| 类别 | 项 |
|---|---|
| **真阻断交付** | **#4869**（工人档案）—— 不解决则**真实部署不可用** |
| **阻断某条分支** | **DP30S 的 BLE 口**（§8.5 ①）—— 不解决则 A 分支不成立，退回 C |
| **不阻断（安全侧已取保守值）** | DP30S 有效打宽（§7.2 已按 ≤48mm 设计）、耗材实测（§7.4 采购侧） |
| **不阻断（可并行）** | 照片识别成功率（B2）—— 先用现有安卓机跑 POC 测掉最大的未知数（#5052「阶段 0」既有口径） |

---

## 11. 验收标准（可执行，**每条都要能红**）

> **前 12 条逐字保留 #5052 正文的验收标准**（不删、不改判），**其后是本包新增**（打印通道改判带来的判据 + 本设计的结构判据）。

### 11.1 #5052 原文 12 条（**逐字保留**）

1. 工人 session 调 `/api/admin/**` 任一端点 ⇒ 拒绝（零商家权限）；
2. 工人端入库接口传负数 / 任意 `adjustment` ⇒ 拒绝；
3. 每次入库在 `stock_ledger_entries` 落一行 `reason='inbound'`，且同 SKU 相邻行 `before_qty == 上一行 after_qty`、`after_qty - before_qty == delta`；
4. 同 `idempotency_key` 重复提交 ⇒ 库存只加一次、台账只有一行；
5. 跳过人工确认直接提交 ⇒ 拒绝（未确认不落库）；
6. 识别到**不存在**的色号 ⇒ 不落库、**不新建商品/SKU**；
7. 照片含可解条码时走解码路径、**不调用 LLM**（成本守卫）；
8. vision 返回降级/不确定文案 ⇒ **不预填**、提示人工录入（不编造）；
9. 标签码形态 = `https://app.migaozn.com/i/<短码>`；撤销后扫码 **410**；
10. 打印计数原子自增（并发不丢计数）+ `audit_logs` 有留痕；
11. 跨租户查不到入库单与标签码；
12. 标签版式：`@page size: 50mm 30mm`、容器 `50mm × 30mm` 且 `overflow: hidden`、每张独占一页、长名按规则截断（**不静默裁切**）。

### 11.2 本包新增（**打印通道改判 + 设计结构**）

| # | 判据 | 能红的形态 |
|---|---|---|
| N1 | **小程序 BLE 路径：能力探测失败时不静默失败** | 环境无 BLE API / 未授权 / 非微信环境 ⇒ **显式提示**并给出可行动出口（换环境或提示用兜底通道）；**静默失败 = 红** |
| N2 | **HTTP 打印兜底通道不得绕过计数** | 任何通道（小程序 / 浏览器 / 壳）打印 ⇒ **必先**命中 `POST /api/worker/inbound/labels/{短码}/print`；跳过 ⇒ 红（`print_count` 与 `audit_logs` 必须都能观测到） |
| N3 | **工人可达面零复用商家识别端点** | `/api/worker/inbound/recognize` 的实现里**不得**调用 `/api/admin/image-recognition`（也不得给工人挂 `product:create` / `order:create`）；工人持 session 打该 admin 端点 ⇒ 拒绝 |
| N4 | **入库识别不接受 `targetType` 扩展** | 入库识别**不经** `ImageRecognitionController` 的 `TARGET_PERMISSIONS` 机制（该机制只认 `product`/`order`，未知 target 400）⇒ 若实现里出现新增 target 即红 |
| N5 | **入库端点结构上不可表达「任意调整」** | 请求体 schema 里**不存在** `adjustment` / `delta` / `setStock` / `reason` 字段；传这些字段 ⇒ 400（**不是**被忽略） |
| N6 | **0.1 米粒度**（#5063 口径） | 收 `60.5` ⇒ 通过；收 `2.755` ⇒ **显式拒绝**；收 `0` / 负数 ⇒ 拒绝；**静默取整 = 红** |
| N7 | **`/i/` 与 `/s/` 不混用** | 入库标签的码**只能**是 `/i/<短码>`；扫 `/s/<短码>` **不得**进拍照入库页；两个码空间各自解析（互不命中） |
| N8 | **缺码不画假码** | 短码未生成 / 生成失败 ⇒ 位图端点**显式报错**（或位图留空位并带可见标注）；**位图里出现占位二维码 = 红** |
| N9 | **位图几何与服务端口径一致** | 位图像素 = **384×240**（有效打宽口径）或 **400×240**（全宽口径），**二选一并与目标机 dpi 绑定后写进判据**；设备侧 **1:1 不缩放不裁切** |
| N10 | **过账复用既有服务方法** | 工人端过账**必须**落到 `InboundOrderService.post(...)`（同一事务语义）；**不得**在 worker 侧新写库存增减 / 直接写 `stock_ledger_entries`（代码级判据：worker 侧无库存写入语句） |
| N11 | **入口衔接不重写 `worker-h5`** | 裁定 13：`frontend/worker-h5` **保持零依赖**（无 `package.json`）；为其新增 npm 依赖 = 红 |
| N12 | **B 端双编译不破** | `frontend/bmini-app` 的 `build:weapp` 与 `build:h5` **都能出产物**（新增拍照入库页后仍成立） |

---

## 12. 明确不做（边界清单，**逐字保留 #5052 的边界**）

- ❌ 不做 PDA 一体机 / 原生 Android 打印壳（首版走手机/平板 + 标签机）；
  > ⚠️ **口径说明（照实登记）**：此条与**裁定 10/11**（设备形态 = 手机 + 便携蓝牙标签机；交付物含 Android 壳 App）在**同一条 issue 内并存**：
  > 「不做 PDA 一体机」= 不买一体机，「原生 Android 打印壳」的口径在评论裁定 11 里被**明确要求交付**（并已拆到 #5061）。
  > 本文**不改判**：以「裁定 10/11 + §8 改判动议 + §13 待裁定 1」为准。
- ❌ 不做免确认自动入库；
- ❌ 不建采购域 / 供应商主数据（首版只记送货单号 + 照片留痕）；
- ❌ 不给工人任何商家权限码；
- ❌ 不让米宝持有库存写入能力；
- ❌ 不引新域名。

**本包（设计交付）另有两条自我边界**：
- ❌ 本包**只落这一份文档**，不写实现代码、不动 CHANGELOG（`docs` 类改动按仓库铁律豁免）；
- ❌ 本包**不改判**任何已锁定裁定（§3.1 的 11 条 + §3.2 的 5 条 BYOD 约束**原样保留**）。

---

## 13. 待裁定（**必须显式留出，本文不自行拍板**）

| # | 议题 | 选项 | 取决于 | 来源 |
|---|---|---|---|---|
| **1** | 🔴 **打印通道改判是否成立** | ① 首版走「**小程序 BLE 直打**」（`lpapi-ble-wx`）+ 保留 §8.3 的 B 分支作补充 ② **仍按原裁定**做 Android 壳 App（#5061）③ 两者都做（A 为主 + C 兜底） | **§8.5 ①：DP30S 的 BLE 口是否开放**（**厂商书面确认 + 样机实测**）；次要：§8.5 ② 官方性 | 本包（2026-09-26 新证据）；动议对象 = 裁定 6 / 11 |
| **2** | **iOS 工人怎么办**（原 #5061 待裁定 1，**仍悬着**） | ① **只支持安卓**（要求工人用安卓机，最省）② 申请 **Apple 企业证书** ③ **公司配机** ④ iPhone 工人退回「厂商 App 中转」 | §8.3 的共同洞：**iOS 浏览器在三个分支里都没有出口**（A 靠微信运行时、B 撞 Apple 未实现 Web Bluetooth、C 没做 iOS） | 原 #5061 待裁定 1 |
| **3** | **打印机最终机型** | DP30S（LPAPI 生态最好）还是其他（芯烨 XP-P441B / 岳冉 HA550D 等） | 采购答复（§3.3 的 4 条 + 8 问）+ 样机实测 | 原 #5061 待裁定 2 |
| **4** | **分发方式** | ① 企业内部分发 apk（需工人开未知来源）② 应用市场 ③ **MDM 下发** | 与待裁定 2 联动（选 iOS 则分发路径完全不同）；B3 的 ROM 拦截实测 | 原 #5061 待裁定 3 |
| **5** | **打印机绑定粒度** | ① 按**工人** ② 按**手机** ③ **每次手选** | 避免打开错机器（`openPrinter("")` 同族问题）；若走 A 分支（小程序）则绑定存哪一侧需一并定 | 原 #5061 待裁定 4 |

**另有两条本文**不列为待裁定、但**必须由实现 PR 处置**的登记项**（本文不拍板，避免越权）：
- **§5.4 入口衔接**：`worker-h5`（`/w/`，扫码直达轻入口）与 `bmini-app h5`（拍照入库页）**不在同一应用**，衔接方式未定；
- **§6.1 h5 侧解码路径**：`Taro.scanCode` 是 weapp 侧能力，**h5 编译产物下需另行落实**「拍照 → 前端解码」等价路径。

---

## 附录 A：复算命令（**本文件的【实测】行都可复算**）

工作区 = 本仓库任一在 `origin/main`（`78c67effc`）上的检出。

```bash
# ① 基线自证
git rev-parse HEAD origin/main            # 两者相同 = 本文的"现状"基线

# ② 入库单端点与过账服务方法（§2.1）
grep -nE '@(Get|Post|Patch)Mapping|@RequestMapping' \
  backend/admin-api/src/main/java/com/migao/admin/controller/InboundOrderController.java
grep -nE 'public .*\(' \
  backend/admin-api/src/main/java/com/migao/admin/service/InboundOrderService.java

# ③ 工人可达面（§2.2 / §5.1）—— 期望：只有 login/session/production/短链，无识别无入库
grep -nE '@(Get|Post)Mapping|@RequestMapping' \
  backend/admin-api/src/main/java/com/migao/admin/controller/WorkerAuthController.java \
  backend/admin-api/src/main/java/com/migao/admin/controller/WorkerProductionController.java \
  backend/admin-api/src/main/java/com/migao/admin/controller/WorkerShortLinkController.java
grep -n 'ADMIN_API_REJECTED_ROLES' backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java
grep -nE 'TARGET_PERMISSIONS|requirePermission|RequestMapping' \
  backend/admin-api/src/main/java/com/migao/admin/controller/ImageRecognitionController.java

# ④ 库存粒度（§2.1）
grep -nE 'stock NUMERIC|delta NUMERIC|quantity NUMERIC' backend/admin-api/src/main/resources/db/init/schema.sql

# ⑤ 标签/打印范式（§2.4）
grep -nE 'print_count' backend/admin-api/src/main/resources/db/init/schema.sql
grep -nE '@page|task-card-label' frontend/admin-web/src/components/production/TaskCardPrint.tsx

# ⑥ 前端形态（§2.4）：双编译能力 + worker-h5 零依赖 + /i/ 零命中 + 解码库零命中
grep -nE '"@tarojs/plugin-platform-h5"|"build:h5"' frontend/bmini-app/package.json
grep -n 'h5:' frontend/bmini-app/config/index.ts
ls frontend/worker-h5/            # 期望：无 package.json（零依赖）
grep -rn "'/i/'\|\"/i/\"" --include=*.java --include=*.ts --include=*.tsx --include=*.py .   # 期望：零命中
grep -rn 'jsqr\|zxing\|barcode' --include=package.json .                                     # 期望：零命中

# ⑦ npm SDK 矩阵（§8.2 / §8.4）—— 期望：版本与 homepage 见 §8.2 表
for p in lpapi-ble-wx lpapi-ble lpapi-ble-uni lpapi-ble-ww lpapi-ble-cdv lpapi-spp-cdv dtpweb lpapi-dtpweb cordova-plugin-lpapi; do
  printf '%-22s ' "$p"; npm view "$p" version time.modified homepage repository.url | tr '\n' ' '; echo
done
npm view lpapi-ble-wx main module types dependencies description
```

---

## 附录 B：关联（**不带关闭意图**）

- 拍照入库主链 ⇒ **#5052**
- 客户端（Android 壳 App，**§8 改判动议对象**）⇒ **#5061**
- 入库单过账本体 ⇒ **#5045**（已闭环）
- 工人档案创建（**唯一未解阻塞**）⇒ **#4869**
- 工人端 H5 设计（已闭环）⇒ **#4716**
- 标签打印范式（洗水码，已闭环）⇒ **#4946**
- 工人登录态 / 零商家权限（已闭环）⇒ **#4733** / **#4727**
- 库存米数小数化（已闭环）⇒ **#5063**
