# 2026-10-04 本轮方法笔记（含一次**自我纠错**）

> 用途：给集成与复核留可直接引用的方法事实；每条都带**现取读数命令**，便于复算。

## N1（自我纠错）跨租户表级计数会被读成「缺陷」——计数必须带 `tenant_id` 过滤

- **我的错误读数**：`select count(*) from production_operations` = **82**、`production_operation_positions` = 232、
  `production_route_templates` = 4、`production_route_rules` = 54 —— 而开租时（08:31）读到的 41/116/2/27 **恰好翻倍**，
  我据此怀疑「开租种子模板被套了两次（非幂等）」。
- **真因（现取）**：

  ```sql
  select tenant_id, count(*) from production_operations group by 1 order by 1;
  --  25 | 41      （米高测试环境）
  --  26 | 41      （米高测试环境-隔离对照 ← 线③ 按 BRIEF §4.3 于 09:04:48 建立）
  ```

  ⇒ 那是**两张租户表的合计**，单租户读数不变（`tenant25_ops=41 / tpl=2 / rules=27`）。**无重复套用缺陷**。
- **教训（与 `migao-acceptance`「归因纪律」同族）**：跨租户的表级合计**不是**任何单租户的事实；
  在被测租户只有 25 的前提下，任何全局 `count(*)` 都要先按 `tenant_id` 分解再解读。
  ⇒ 本轮三线的判据**必须**限定本线探针对象（BRIEF §3 纪律第 8 条：判据命名空间化、禁止断言租户级全局计数）。

## N2 隔离对照租户 = tenant 26（线③ 建立，收尾必须清空）

- 现取：`select id,name,code,status,to_char(created_at,'HH24:MI:SS') from tenants order by id;`
  → `25 米高测试环境 shop-8yn7 active 08:31:29` / `26 米高测试环境-隔离对照 shop-4c53 active 09:04:48`
- **集成验收前置**：线③ 收尾必须清空 tenant 26 并删 `tenants` 行；集成时**必须**复算「tenants 只剩 25」，
  否则本轮视为**留下残留**（BRIEF §4.3「清理失败 ⇒ 报告首行红字登记」）。

## N3 租户 25 冷启动配置面（探针夹具失败时的**第一归因入口**）

| 表 | tenant 25 | 说明 |
|---|---|---|
| `processing_categories` / `processing_items` | **0 / 0** | 加工项目录为空 —— 建单/加工单链路的首要怀疑点（#4316 同族：非 1 号租户工序库为空 ⇒ 建单 fail-closed） |
| `craft_calc_configs` / `cutting_height_configs` | 0 / 0 | 算料与裁高配置未初始化 |
| `production_operations` / `positions` | 41 / 116 | 开租模板已种（#4361） |
| `production_route_templates` / `rules` | 2 / 27 | 同上；`ProcessingOrderService` 的 `ERR_ROUTING_NOT_FOUND` 依赖它 |
| `production_crafts` | 2 | — |
| `tenant_apps` / `tenant_ai_configs` / `agent_employees` | 0 / 0 / 0 | 小程序入口与 AI 配置未初始化 |
| `notification_templates` / `worker_page_configs` | 0 / 0 | 通知模板与工人端页面配置未初始化 |

> ⚠️ 这些数字**只作归因入口**，不预先断言为缺陷：能否走通取决于该链路是否真的依赖它们
> （例：`ProcessingOrderService` 的依赖点见 `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java`
> 的 `ERR_ROUTING_NOT_FOUND` / `ERR_OPERATION_NOT_FOUND` 与「订单无加工项，无需生成加工单」分支）。

## N4 覆盖面对账基线

`acceptance/2026-10-04/env/endpoint-inventory.md` —— 从被测 SHA `ff655a06c` 机械抽出的
**32 个 controller / 154 个端点**（按线分组：`/api/worker/**`、售后/退款/财务、写端点分布）。
集成时用它核对三线报告里的覆盖声明：**声明覆盖 ≠ 端点被调用**（协议「交付物可达性判据」）。

## N5 集成侧独立收敛：线② 的 `LB1-SETUP-category-gap` 是 **P2 体验缺口**，不是 P1 阻断

- **线② 的读数**（`aftersales-refund-sweep/out/B1-category-gap.json` + `SUMMARY.json` 的 `LB1-SETUP-category-gap`，verdict=`fail`）：
  租户 25 初始 `active_categories=0`，而 `POST /api/admin/products` 的 `categoryId` **必填**
  ⇒ 新租户「开箱建商品」的前置分类不存在。该线**有意不下更强归因**（原文：能否由前端兜住不在本线射程）。
- **我的独立收敛（只读源码，SHA `ff655a06c`）**——三条判据，逐条可复算：

  | # | 判据 | 读数 | 复算命令 |
  |---|---|---|---|
  | ① | 分类管理页存在 | `frontend/admin-web/src/app/(dashboard)/categories/page.tsx` | `git ls-tree -r --name-only ff655a06c -- frontend/admin-web/src/app` |
  | ② | **建商品表单内联「新建分类」** | `components/products/ProductForm.tsx:882` 渲染 `<CategoryTree>`、`:895` 渲染 `<CategoryDialog>` ⇒ 建商品时可**就地**建分类 | `git show ff655a06c:frontend/admin-web/src/components/products/ProductForm.tsx \| sed -n '875,900p'` |
  | ③ | 分类页在「商品管理」域内可达 | `components/layout/Header.tsx:57` 面包屑 `商品管理 → 商品分类管理`；`app/(dashboard)/layout.tsx:32` 前缀门禁码 `product:category:view` | `git grep -n "/categories" ff655a06c -- frontend/admin-web/src` |

  逐字取证（**自助恢复路径完整**，三段都在同一个表单里）：
  - `ProductForm.tsx:550` —— 建商品表单上的 **「管理分类」按钮**；
  - `ProductForm.tsx:856` —— 打开的是 `title="分类管理"` 的 `Modal`，其头部工具行含
    **`<Button onClick={handleCatAdd}>…添加分类</Button>`**（空分类时该按钮**仍在**，不是死路）；
  - `ProductForm.tsx:895` —— 「添加分类」再打开 `CategoryDialog` 子弹窗完成新增。
  另：`RegistrationService` 的开租授权含 `product:category` / `product:category:view`（`":" 商品分类"` 权限码行），
  ⇒ 新租户 admin **有权限**自建分类。
- **结论（归因强度匹配证据强度）**：功能**可自助恢复**（就地建分类即可建商品）⇒ 记为
  **P2「新租户开箱引导/开租种子不含商品分类」**，**不记为 P1 阻断**。
- **未覆盖（如实登记）**：本收敛是**源码静态可达性**，未做浏览器级实点（建商品弹窗内建分类的真机走查）；
  若要升级为 L2/UA 证据，需 Playwright 真实登录实点一条（重启条件 = 本轮 UI 腿）。

## N6 集成侧新发现（我的探针撞出来的）：超长 `skuCode` ⇒ **500 而非 4xx**

- 触发：`POST /api/admin/products`，`skuCode` 长 32 字符（> 列定义 `character varying(30)`）。
- 服务端栈逐字（`docker logs migao-deploy-admin-api-1`，2026-10-04 09:23 +08）：

  ```
  ### Error updating database.  Cause: org.postgresql.util.PSQLException: ERROR: value too long for type character varying(30)
  ### The error may exist in com/migao/admin/mapper/ProductMapper.java (best guess)
  ### The error may involve com.migao.admin.mapper.ProductMapper.insert-Inline
  ```
- 用户可见面 = `{"success":false,"error":{"code":"INTERNAL_ERROR","message":"服务器内部错误"}}`（**500**）。
- **应然判据（与本仓既有范式同族）**：超长入参属**可预期输入**，应 **4xx + 可行动文案**（本仓同族先例：
  `StockQuantity::requireOneDecimal`、`InboundOrderService::requireItemNumbers`、#6228 的 `MoneyScale` 准入）。
- 归因状态：**待新构建复验**（旧构建 `de614623d` 实测 500；`origin/main` 侧我 grep 未见 skuCode 长度准入 ⇒
  疑似 main 仍在，但**以 postdeploy 重放读数为准**，不预先开单）。

## N7 集成侧自曝（判据缺陷）：重放脚本首版让 R2/R3 共用同一张订单 ⇒ R3 读数被 R2 的副作用污染

- 现象：R2 的并发完结会给订单打上 300 元退款 ⇒ 紧接着的 R3「0.001 应被拒」拿到的是 **422「超实收」**，
  看似「已经拒绝」，其实是**别的原因**——若不修，就会把「未修」读成「已修」（**假绿方向**）。
- 修法：R3 改用**独立商品 + 独立订单**；README/判据里记明「判据之间不得共享会被副作用改写的夹具」。
- 同族教训（与 N1 一致）：**判据的判别力要靠单变量对照来保证**，共享夹具是隐性耦合。

## N8 工具面缺陷（集成侧发现）：harness 把**活会话 token** 写进 `out/` 产物

- 现象：`race-sweep/out/fixtures.json`、`worker-miniapp-sweep/out/.session.json`（及重放目录同名文件）
  内含**真实 JWT**（`eyJhbGciOiJSUzI1NiJ9…`）——这是 harness 登录后直接落盘会话凭据。
- 风险：验收产物按惯例要**提交进仓库**（`acceptance/**`）⇒ 一条 `git add acceptance/` 就会把活 token 推进远端；
  本轮的 Secret Scan / 人工扫描是**事后**兜底，不是机制。
- 本轮处置：**4 个文件逐个脱敏**（JWT → `<REDACTED-JWT>`），删除 2 个运行态 `.session.json`（仓库既有 2026-10-03 也未跟踪它），复扫为空。
- 建议固化（另开单，属工具面）：在底座 `harness/lib.mjs` 的落盘函数里加**写时脱敏**（命中 `eyJ…` 即替换），
  并加一条**元守卫**：`acceptance/**` 下任何被 git 跟踪的 `.json` 含 JWT 形态即红 —— 让"带 token 的产物"进不了仓，
  而不是靠每次人工扫。

## N9 工具面缺陷（集成侧发现）：幂等键落盘被 gitleaks 判成密钥 ⇒ **CI 必需检查被阻塞**

- 现象：`git push` 后 PR #6304 的 **`Secret Scan (gitleaks)` 必需检查 FAILURE**，日志只写 `leaks found: 20`（明细在 SARIF 工件里，snippet 被工具自己抹成 `REDACTED`）：
  ```
  gh run download <run-id> --name gitleaks-results.sarif   # → 20 条，规则全是 generic-api-key
  ```
- 命中对象：**幂等键**，形态 `"key": "<IDEM-KEY-3>"` / `"key": "<IDEM-KEY-1>"`
  落在 `race-sweep/out/probe-idem*.json`、`aftersales-refund-sweep/out/B1-idem-raw.json`、`B1-serial.json` 及其重放副本（共 8 文件 22 处）。
- **不是真密钥**（是探针自己造的幂等键），但**判据面必须服从扫描器**：既然仓库把 Secret Scan 列为必需检查，
  这些产物就不能带着"看起来像密钥"的形态入库。
- 本轮处置：**按值做确定性映射**脱敏（12 个不同键 → `<IDEM-KEY-1..12>`），保留"同键/异键"的区分
  （否则幂等读数的可读性会被破坏）；映射表落盘 `env/out/idem-key-redaction-map.json`；复扫 0 残留。
- 建议固化（与 N8 同族，另见 #6303）：harness 落盘时对**幂等键/会话 token 一类"我们自己造但形似密钥"的字段**统一走
  `redact-on-write`；并加一条**入库前**判据：`acceptance/**` 里被跟踪的 `*.json` 若命中 `"key": "<长随机串>"` 或 JWT 形态即红——
  让"被扫描器拦下"从 CI 事后阻塞变成提交前可自检。

## N10（2026-10-04 12:5x +08）探针的"静默默认"害我开了一张错单 —— 集成侧错判，已撤回

**发生了什么**：我用线③ 的探针手工复算 #6301 的修复，得到"同 runId 6 并发仍 5xx×5"，据此开了 **#6318**（缺陷口径）。
失败包把前提顶了回来，我复算确认：那两次探针**打的是本机 :8080 的一个陈旧实例**
（worktree `main-live` @ `43ca70322`，其 `StockBatchConsumptionMapper.class` 常量池 `ON CONFLICT` 计数 = **0**），
该实例 stdout 里**逐字含我两次探针的 runId**。根因 = `race-sweep/harness/lib.mjs` 的 `API_BASE || 'http://localhost:8080'`
＋ **我手工调用时漏传 `API_BASE`**（`env/postdeploy-replay.sh` 本身是正确 export 的）。#6301 的原子闸在端点上**是生效的**
（修复构建：6/6 全 200、5xx 0、分录 1 行、库存 Δ-3；同一探针打陈旧实例仍 `1/6 + 5xx×5` ⇒ 判别性对照成立）。

**教训（可复用的三条）**
1. **静默默认 = 假读数工厂**：端点级探针**必须**显式给 base，没给就**大声失败**。
   已就地固化：`lib.mjs` 改为 fail-closed（不传 `API_BASE` 即 exit 2，仅 `ALLOW_LOCAL_API=1` 允许回落本机）。
2. **"打到了哪个进程"本身要取证**：报"线上红"之前，必须让读数能被**同一进程**的日志/构建指纹对上
   （进程 pid + classpath + 产物 mtime + 请求 runId 在日志里的命中行数）。我这次只查了**部署环境容器的日志**就下了"无日志"的结论 ⇒ 错。
3. **别人的反证要当成一等证据**：这次是失败包用可复核指纹把我的结论顶回来；**错判就地撤回、单据就地重定性**，
   而不是把错单偷偷关掉 —— 留痕比"看起来没犯过错"重要。

**另两条同批发现的工具口径差（不是产品缺陷，已在集成侧载体修）**
- W5 读 `data.results[].status`，而回执 DTO 字段是 **`lines`** ⇒ "replayed 回执 0" 是恒 undefined 的**工具口径差**（正确 = 1 applied + 5 replayed）；
- W5 的台账过滤拿 runId 去匹配 `note/ref_no`，而盘点行 `ref_no` = 批次号 ⇒ `ledgerForRun: 0` 恒成立。
