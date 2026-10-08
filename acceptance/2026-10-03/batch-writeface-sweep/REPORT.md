# 线② 独立验证包 —— 破坏性写面 + 并发/幂等（2026-10-03）

> 包路径：`acceptance/2026-10-03/batch-writeface-sweep/`
> 角色：**线② 独立验证**（只取证、不改 MIGAO 业务代码、不开 issue、不派单）
> 被测面：商品导入 / 导出 / 批量写 / 工序「设为不做并删除」/ 6 个上传端点 / 并发·幂等·竞态（发货面**不在**射程）

---

## §0 核心判据（一句话结论）

| 面 | 结论 | 依据 |
|---|---|---|
| **A 导入** | ✅ **通过**（含逐行报告、失败行零副作用、幂等、整包级 4xx） | A1/A2/A3/A4 共 12 条断言全绿 |
| **A 导出** | 🔴 **发现 P1 真缺陷**：导出行数**静默截断在 500**（列表 total=989 而导出 500 行） | A5.2 + 根因 `MybatisPlusConfig.setMaxLimit(500L)` |
| **B 批量写** | ✅ **通过**（部分失败如实报告、跨租户零写、软删语义、终态拒绝） | B1/B2/B3 共 17 条断言全绿（含 3 条正对照） |
| **C 工序删删** | ✅ **通过**（依赖闭包活跃引用=0、护栏照拦、二次调用非 5xx、跨租户 404 零写） | C1 共 6 条断言全绿 |
| **D 上传边界** | 🔴 **发现 2 条 P2 真缺陷**：①5MB 图片上限可被客户端 `Content-Type` 绕过（19MB 落库）②`directory` 无校验 ⇒ 500 | D2.5 / D3.2 |
| **E 并发/幂等** | 🔴 **发现 P1 真缺陷**：**库存可为负**（`PUT /products/{id}` 写 -5 落库，并发 5 次全过）；**重复提交无服务端幂等**（同 `X-Client-Request-Id` 并发 5 次 ⇒ 6 条商品） | E2.1/E2.2、E1.1 |
| **F 红证** | ✅ 通道可用（3 条注入式红证 + 1 条故意失效控制项；其中 **1 条判据被红证推翻**） | F1~F4 |

**最终读数：`pass 54 / fail 8 / skip 0 / total 62`；零残留 = 真（13 张表逐表计数全 0）。**

8 条 fail 的三态分解（**不要按字面数当 8 个缺陷**）：

| 类别 | 条数 | 断言 |
|---|---|---|
| 🔴 **真缺陷** | **6 条断言 / 5 个缺陷** | A5.2、D2.5、D3.2、E1.1、E2.1、E2.2 |
| ⚪ **故意失效控制项**（必须红） | 1 | F4 |
| 🟡 **判据/harness 自身缺陷**（假红，非产品） | 1 | F2（回绿半段；红半段成立） |

---

## §1 构建点自证（含**切换前后两个构建点**）

| 项 | 值 |
|---|---|
| 仓工作树 HEAD | `0a28014ff`（`fix(logistics): #6185 …`，2026-10-03T13:01:25+08:00） |
| `origin/main`（取证时） | `d877f19ef` |
| **构建点①（旧）** | `main-live @ d1c09d02f`，pid 99086，进程启动 **2026-10-03 13:09:45 +08** |
| **构建点②（新，当前）** | `main-live @ 7e9f66ce5`「fix(6181): 商家发货三步原子化 … (#6190)」，pid **60585**，进程启动 **2026-10-03 13:44:16 +08** |
| 切换时刻（主会话实测） | **2026-10-03 13:44:16 +08** |
| 本报告读数的测量窗口 | **2026-10-03 13:45:00 → 13:56:35 +08**（UTC 05:45:00Z → 05:56:35Z） |
| 服务是否再次重启 | 否（窗口内 pid 恒为 60585；`buildpoint-shift.json` 与 `SUMMARY.json` 同源） |

**判据分界（按 `at` 字段切分）**

| 时间区间 | 归属构建点 | 覆盖断言 |
|---|---|---|
| `< 13:44:16` | `d1c09d02f` | 仅**首轮探索**（13:42–13:43）：A 首轮 13/7、B 首轮 7/7 —— **已全部作废**（见 §7 假红台账） |
| `>= 13:44:16` | **`7e9f66ce5`** | **本报告全部有效读数**：A(13:52)、B(13:46–13:48)、D(13:49/13:52)、E(13:51)、F(13:56) |

⇒ **跨切换窗口的判据已整段重跑**（A/B/D/E/F 五个段全部在 `7e9f66ce5` 上重跑），不是"只登记不重测"。

**构建切换对本包判据的影响：无。** `#6181/#6190` 是**商家发货三步原子化**（发货面），本包射程 = 商品/工序/上传/并发幂等，
与该改动无交集；重跑后结论与首轮一致（首轮的真缺陷在重跑中**同样复现**，首轮的 4 条 fail 全部被定性为假红并消失）。
读数为：切换前后**没有任何一条断言因构建点变化而翻转**。

---

## §2 断言矩阵（pass / fail / 假红 / skip 四态分列）

### 2.1 pass（54）

| 段 | 条数 | 覆盖要点 |
|---|---|---|
| A 导入（A0~A4、A6） | 20 | 逐行报告恒等式 `total==success+fail+blank`；失败行**零落库**+成功行落库（DB 判定）；租户归属；幂等（商品/SKU 不翻倍 + 主键不变 + 第2次报 updated）；空文件/缺表头/缺必填列/伪 xlsx 各 4xx；超大文件（9.46MB）不 5xx 且逐行如实；导入模板表头==`IMPORT_HEADERS` |
| A 导出（A5） | 5 | 非空正对照；表头逐字==`EXPORT_HEADERS`；精度核对（DB 原文 vs cell）；**不含他租户**；空结果非畸形（3.5KB 合法 xlsx、表头齐、0 行） |
| B 批量写 | 17 | `draft` 负例（如实拒绝+DB 零变更）；同 payload 连发不漂移；**正对照链**（状态机 draft→on_sale→batch/off-shelf→batch/on-shelf 两跳全成功）；部分失败如实报告（ghost+他租户各进 `errors[]`）；他租户零写；软删语义（parent 行在、子行保留）；读面可达性（软删后 GET/列表/导出均不可读回） |
| C 工序 detach-and-delete | 6 | 正对照（工序落库）；跨租户 404 零写；一键删除（`detached_positions=2/deleted_positions=2`、工序 `deleted=1`、格 `applicable=false`+价清空）；4 组引用列活跃命中全 0 + 价目账读面不暴露；二次调用 404（非 5xx）；护栏①主线照拦（422 + details） |
| D 上传（含正对照） | 11 | 4 个上传端点成功路径 + **URL 可访问且字节一致**（69B 真 PNG）；空文件 422；`.exe` 422；6MB `.png` 422（5MB 上限）；文件名穿越 `../../l2evil.png` 不逃逸（存储名走 UUID）；批量端点条数正确；存储隔离（URL 含 `images/yyyy/MM/dd/`） |
| E 并发 | 4 | 串行正对照；库存合法值 7 真的落库（正对照）；终态对象并发写全拒 + 零写（含活体正对照）；并发 5 次 detach 恰好 1 次成功 + 终态 `deleted=1` |
| F 红证 | 2 | F1（**注入被 FK 拒绝** ⇒ 判据无判别力，如实登记）；F3（库存不变式注入式红证 + sha256 自证） |

### 2.2 fail（8）→ 三态分解

| 断言 | 类别 | 期望 | 实得 | 证据文件 |
|---|---|---|---|---|
| **A5.2** 导出行数==列表 total | 🔴 **真缺陷** | 500 == 989 | 导出 **500** / 列表 **989** | `out/A5-export-all.json` |
| **D2.5** 5MB 图片上限不可被绕过 | 🔴 **真缺陷** | 4xx | **200**（19,922,953B 落 OSS） | `out/D2-boundaries.json` |
| **D3.2** `directory` 穿越须干净拒绝 | 🔴 **真缺陷** | 4xx | **500** `INTERNAL_ERROR` | `out/D3-traversal.json` |
| **E1.1** 并发同幂等键只落一份 | 🔴 **真缺陷** | 1 | **6**（`client_request_keys` 0 行） | `out/E1-duplicate-submit.json` |
| **E2.1** 库存 -5 须拒绝 | 🔴 **真缺陷** | 4xx 且库存仍 7 | **200**，`products.stock=-5.0`、`product_skus.stock=-5.0` | `out/E2-stock-negative.json` |
| **E2.2** 并发写负库存全拒 | 🔴 **真缺陷**（与 E2.1 同根因） | 5×4xx | **5×200**，终值 `-1.0` | `out/E2-stock-negative.json` |
| **F4** 故意失效控制项 | ⚪ 控制项（**必须红**） | 1===2 | false | `out/F-redproof.json` |
| **F2** 幂等判据回绿半段 | 🟡 **判据缺陷** | 注入后回到 1 | **2**（红半段 1→2 ✅ 成立） | `out/F2-idempotence-redproof.json` |

### 2.3 假红（判据缺陷，**不计 fail**，7 条 —— 详见 §7）

导出 0 行解析失败 / batch 上架期望 / 闭包"孤儿" schema 前提 / C1.3 两处列名 / D5.1 正则自相矛盾 / A4.3 CSV 半条 / F2 回绿半段。

### 2.4 skip（**0**，但"未判定"另列，见 §5）

本包**没有**把任何一条记成 `pass` 来掩盖未覆盖；不可达的判定一律进 §5「未覆盖面」，措辞为**未判定**而非通过。

---

## §3 红证台账（注入 ⇒ 红 ⇒ 还原 ⇒ 绿，sha256 自证）

| 红证 | 注入方式 | 注入前 | 注入后（红） | 还原后 | 内容指纹自证 | 判定 |
|---|---|---|---|---|---|---|
| **F1** 孤儿不变式 | `insert into product_skus(product_id='l2orph…')`（真孤儿） | 0 | **注入被 DB 拒绝**（`product_skus_product_id_fkey`） | 0 | 无行可指纹 | ✅ **红证**成立 —— 但**推翻的是判据本身**：孤儿=0 是**约束的结果**，不是被测行为 ⇒ B3.2 无判别力（改判 skip，见 §5/§7） |
| **F2** 幂等判据 | `insert into products(id='l2dup…', sku_code=<同货号>)` | 1 | **2** ✅ 判据当场红 | 2 ❌ 未回绿 | `770c016f…` → `eb93f353…`（不同 ⇒ 注入/还原真的动了数据） | 🟡 红半段成立、回绿半段**未证**（harness 缺陷，见 §7-7） |
| **F3** 库存不变式 | `PUT /products/{id}` `stock=-5` | 7 | **-5** ✅ 判据当场红 | **7** ✅ 回绿 | DB 行指纹 `fpGreen ≠ fpRed` | ✅ 完整红证（同时**证明 E2.1 是真缺陷**，不是空断言） |
| **F4** 故意失效控制项 | 断言 `1===2` | — | **fail** ✅ | — | — | ✅ 证明 fail 桶可达 |
| **B3 系列等价红证** | 见 F1：结构上无法注入孤儿 ⇒ 反向取证（8 条 FK 现查） | — | — | — | — | 已如实改判 |
| **E2 系列等价红证** | F3 即其注入式复算（同一条不变式） | — | — | — | — | ✅ |

**"不会红的断言 = 空断言"执行情况**：本包每条 fail 类判据都有对应红证或正向注入；**唯一被红证推翻的判据（B3.2 孤儿扫描）已改判**，未留在矩阵里充数。

---

## §4 发现清单（5 个真缺陷 + 4 条观察项）

> 级别口径：P1 = 数据完整性/库存决策面；P2 = 护栏可绕过 / 输入校验缺失 / 无幂等。
> 每条给「一句话 + 证据文件 + 可复制复现步骤 + 涉钱/权限/不可逆」。

### 🔴 D-1（P1）导出静默截断在 500 行，与列表 `total` 口径不一致

- **一句话**：`GET /api/admin/products/export` 只导出 **500** 行，而同筛选条件的 `GET /api/admin/products` 报 `total=989`；用户拿到的是**残缺文件且没有任何提示**。
- **证据**：`out/A5-export-all.json`（`rowCount:500`，`listTotal:989`）；断言 A5.2。
- **根因**（读 `origin/main` 之外的**运行构建点源码** `main-live`）：`MybatisPlusConfig.java` 的 `paginationInterceptor.setMaxLimit(500L)` 把单页上限钉在 500；而 `ProductService.exportProducts` 里 `query.setSize(10000L)` 的意图是"全量导出"（注释逐字「查询商品列表（不分页，全量导出）」）⇒ 两者叠加后被静默夹到 500。
- **复现**：
  ```bash
  TOKEN=$(curl -s -X POST :8080/api/auth/sms/login -H 'Content-Type: application/json' \
    -d '{"phone":"13870217889","code":"123456"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['accessToken'])")
  curl -s -H "Authorization: Bearer $TOKEN" ":8080/api/admin/products?page=1&size=10000" | python3 -c "import sys,json;d=json.load(sys.stdin)['data'];print('total',d['total'],'items',len(d['items']))"
  curl -s -H "Authorization: Bearer $TOKEN" -o /tmp/e.xlsx ":8080/api/admin/products/export"
  # 解析 xl/worksheets/sheet1.xml 的 <row 数 = 500，而 total 更大
  ```
- **涉钱**：否（但**迁移/期初对账按导出件重算会漏 489 行**，间接影响账）｜**涉权限**：否｜**不可逆**：否（只读）

### 🔴 D-2（P1）库存可为负 —— `PUT /api/admin/products/{id}` 无超卖护栏

- **一句话**：把商品库存改成 **-5** 返回 **200** 并**真的落库**（`products.stock=-5.0`、`product_skus.stock=-5.0`），同时写一条台账 `delta=-12, before=7, after=-5, reason=manual`；并发 5 次同样全 200，终值 `-1.0`。
- **证据**：`out/E2-stock-negative.json`（`negative.http=200`、`after.product=-5.0`、`ledger` 4 行）；断言 E2.1/E2.2 + 红证 F3。
- **口径不一致（判别性对照）**：同仓**其它**库存写路径**有**护栏 —— 导入用 `StockQuantity.requireOneDecimalOrNull`、`batch-stock/stocktake` 有 `INSUFFICIENT_STOCK`（注释逐字「盘亏会让 SKU 库存变负 ⇒ 422」）⇒ **表单改品这条路径漏了同一份判据**。
- **复现**：
  ```bash
  # 1) 建探针商品（或在既有 draft 商品上）→ 取 id 与 skuCode
  # 2) 同一 payload，把 stock 设为 -5：
  curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"name":"x","skuCode":"<sku>","basePrice":20,"stock":-5,"unit":"米","pricingType":"per_meter","status":"draft",
         "colors":[{"colorName":"米白"}],"doorWidths":["2.8m"],
         "skus":[{"colorName":"米白","doorWidth":"2.8m","price":20,"stock":-5}]}' \
    ":8080/api/admin/products/<id>"      # ⇒ 200
  ```
- **涉钱**：**间接是**（库存失真 ⇒ 可售量/超卖决策面）｜**涉权限**：否｜**不可逆**：否（可改回），但**并发下可被推到任意负值**

### 🟠 D-3（P2）上传：图片 5MB 上限可被**客户端自报的 `Content-Type`** 绕过

- **一句话**：`filename=big19.png` + `Content-Type: application/pdf` + **19.9MB** ⇒ **200**，对象落 `images/2026/10/03/…png` 且**公共可读**。
- **证据**：`out/D2-boundaries.json`（`pdfCtPngExt19MB.http=200, bytes=19922953`）；断言 D2.5。
- **根因**：校验用 `isImageType(file.getContentType())` 决定 5MB / 20MB 上限，而 `Content-Type` 是**客户端可控**；扩展名仍是 `.png`。
- **复现**：
  ```bash
  head -c 19000000 /dev/zero > /tmp/big19.png
  curl -s -X POST -H "Authorization: Bearer $TOKEN" \
    -F "file=@/tmp/big19.png;type=application/pdf" -F "directory=images" \
    ":8080/api/admin/files/upload"     # ⇒ 200 + url
  ```
- **涉钱**：否（但**存储配额/成本**面）｜**涉权限**：否｜**不可逆**：否（可删）

### 🟠 D-4（P2）`directory` 参数**无校验** ⇒ `../../` 触发 500（本地实现有校验、该实现没有）

- **一句话**：`directory=../../l2evil` ⇒ **HTTP 500 `INTERNAL_ERROR`**（不是干净的 422）。
- **证据**：`out/D3-traversal.json`（`directoryTraversal.http=500`、无 `url`）；断言 D3.2。
- **对照（同一份接口的两种实现）**：`LocalFileStorageService#safeResolve` 会 `normalize` 后校验必须位于 uploads 根内 ⇒ 抛 `validationError("非法文件路径")`（422）；而**运行中的** `OssService#generateObjectKey` **完全没有该校验**，直接把 `directory` 拼进对象键。⇒ 运行期表现为 500（SDK 抛错被兜底成 `INTERNAL_ERROR`）。
- **复现**：`curl -s -X POST -H "Authorization: Bearer $TOKEN" -F "file=@/tmp/a.png" -F "directory=../../l2evil" :8080/api/admin/files/upload`
- **涉权限/安全**：**是（输入校验缺失，且实现间护栏不一致）**｜**不可逆**：否
- **⚠️ 未判定项**：OSS 侧**是否**真写下了一个含 `..` 的对象键 —— 无法列举（见 §5）。当前读数只有「响应 500、未返回 url」。

### 🟠 D-5（P2）重复提交**没有服务端幂等**：`X-Client-Request-Id` 完全未被消费

- **一句话**：同一 `X-Client-Request-Id` **并发 5 次**相同建品请求 ⇒ **多出 5 条商品**（并发前 1 → 6），且 `client_request_keys` 表**0 行**命中 ⇒ 该链路**根本不读幂等键**。
- **证据**：`out/E1-duplicate-submit.json`（`afterSerial=1`、`afterConc=6`、`clientRequestKeys=[]`、5×200）；断言 E1.1（配 E1.0 串行正对照）。
- **复现**：
  ```bash
  for i in 1 2 3 4 5; do curl -s -X POST -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' -H 'X-Client-Request-Id: l2-e1-fixed' \
    -d '{"name":"线②验收重复提交","skuCode":"L2-E1-DUP-FIXED","basePrice":9,"stock":1,"unit":"米","pricingType":"per_meter","status":"draft"}' \
    ":8080/api/admin/products" & done; wait
  # ⇒ 6 条同货号商品（1 条来自串行正对照）
  ```
- **涉钱**：否｜**涉权限**：否｜**不可逆**：否（可删），但**脏数据会进列表/导出/C 端**

### ⚪ 观察项（判据红不了，按纪律**不造成单**，登记备查）

| # | 观察项 | 读数 | 性质 |
|---|---|---|---|
| O-1 | 非图片内容 + `.png` 名 ⇒ 200（**无魔数校验**） | `out/D2-boundaries.json` `fakeContentPng.http=200` | 产品**未声明**内容嗅探 ⇒ 未定义行为，登记 |
| O-2 | 批量上传**部分失败无语义**：第 2 个非法 ⇒ 整体 422，但第 1 个的 `upload()` 已在循环里执行（**无事务**，源码逐字 `for (MultipartFile file : files)`）⇒ 首件 URL 被丢弃 | `out/D4-batch-partial.json` | OSS 侧对象**无法列举** ⇒ 残留未判定（§5） |
| O-3 | `.csv` 扩展名 + **合法 xlsx 内容** ⇒ 200（按内容解析） | `out/A4-bad-inputs.json` `csvExt.http=200` | 产品只声明 xlsx（前端 `accept=".xlsx,.xls"`、模板名 `商品导入模板.xlsx`）⇒ 未定义行为 |
| O-4 | 导入**无文件大小上限**：9,462,328B（4000 行）⇒ 200，4000 行逐行报告 | `out/A4-bad-inputs.json` `big.http=200` | 未声明上限；**未观察到副作用异常**（3636 行失败均带行号） |

---

## §5 未覆盖面（照实，含**未判定**项；本包 skip=0）

| # | 未覆盖 / 未判定 | 为什么 | 影响 |
|---|---|---|---|
| U-1 | **"不落盘"判据无法判定** | 运行存储 = **OSS**（`OssService` @Primary + 凭据齐备，日志 `初始化 OSS 客户端`）⇒ 落点不在本机；本地 `backend/admin-api/uploads/`（152 文件）是**本地实现时期/历史遗留**，**不是**本轮落点。OSS 无列举权限 ⇒ 无法证明"零对象" | D 段所有"不落盘"只能退化为「响应 4xx/5xx 且无 url」+「本地目录未变」；**已如实降级，未记 pass** |
| U-2 | **OSS 侧对象残留** | 同上（无法列举）；D 段对 8 个已返回 url 的对象用 `DELETE /api/admin/upload/image` 清理，**8/8 返回 200**，但"删成功"不等于"桶里没有别的" | 上传面的零残留只在**端点口径**上成立 |
| U-3 | **`POST /api/admin/batch-stock/stocktake` 并发同 `runId` 幂等** | 需自建 `stock_batches` 夹具（外部依赖：入库批次），本轮时间预算不足 | 库存的**批次级**并发幂等未判定（表单级已判，见 D-2） |
| U-4 | **导入并发**（同一文件并发两次） | 与 U-3 同因：本轮优先保"导入正确性+幂等"的串行面 | 导入幂等**串行已判**（A3 全绿），并发未判 |
| U-5 | **大批量 batch（>500 ids）与 batch×单条 API 交叉并发** | 需造数百个探针商品，属重活（§27 锁）+ 与并发包争用 | 批量写的**规模边界**未判 |
| U-6 | `DELETE /api/admin/files/{fileId}` 与 `DELETE /api/admin/upload/image` 的**跨租户/越权删除** | 本轮聚焦"写面 + 边界"；删除面按 url 入参，越权面需另一套夹具 | 上传删除面的权限边界未判 |
| U-7 | **导出 xlsx 的字节级编码/单元格类型**（styles、日期序列化、公式） | 已判：行数=total、表头逐字、数值精度、空结果非畸形 | 编码/样式细节未判 |
| U-8 | **UI 级复核**（admin-web `:3001`；worker-h5 `:3100`） | 任务口径「以真实 HTTP + DB 为主」 | 未做 UI 级复核 |

**已跑完的端点清单（6 个上传端点全部跑到）**：`POST /api/admin/files/upload`、`/files/upload-batch`、`/upload/image`、`/upload/images`、`DELETE /upload/image`（清理用，8/8 成功）；`DELETE /files/{fileId}` **未跑**（见 U-6）。

---

## §6 零残留自证

**终态读数**（`out/Z-residue.json`，测量时刻 2026-10-03 13:56:35 +08）：

| 表/口径 | 计数 |
|---|---|
| `products`（id `l2%`） | **0** |
| `products`（name `线②验收%`） | **0** |
| `product_skus` / `product_colors` / `product_attributes` | **0 / 0 / 0** |
| `production_operations` / `production_operation_positions` / `…_price_versions` | **0 / 0 / 0** |
| `production_route_templates` / `production_route_rules` | **0 / 0** |
| `stock_ledger_entries`（按 product_id / ref_no） | **0 / 0** |
| **合计** | **0（`clean: true`）** |

- 探针命名域：id `l2%` ∪ name `顶部线②验收%`（实际前缀 `线②验收`）∪ sku_code `L2-%`；**只**动这三种命中的行。
- 清理器缺陷已修并留痕：`cleanupProbe` 首轮按 id 前缀清 ⇒ **API 建的商品 id 是随机 32 位 hex**，被 `stock_ledger_entries_product_id_fkey` 当场拦下（`update or delete … violates foreign key`）⇒ 改为**按 name/sku_code 命中 + CTE 子行先删**（FK 顺序即安全顺序）。
- 跨包隔离：曾误把 `production_operation_positions` 按不存在的 `operation_id` 列过滤（报错被读成 dangling，见 §7-4）；修正后本包只按 `logical_name like '线②验收%'` 命中，**未动任何非本包行**。
- **⚠️ 外部事件（如实登记）**：13:55 前后，`acceptance/2026-10-03/` **整棵树被移出仓库**到 `/private/tmp/migao-acceptance-stash/2026-10-03/`（含线①/线③的包与 `SUMMARY-next-round.md`）。本包在 13:55:50 从其 stash 副本**原样恢复到** `acceptance/2026-10-03/batch-writeface-sweep/`，随后补跑 F 段并复算零残留。**其他包的产物是否已被主会话取走，本包不掌握**。

---

## §7 假绿 / 假红自查（**本包最有价值的自查项之一**）

> 首轮 4 组 fail **全部**定性为假红/期望错 —— 若不做这一步，会把 4 条"判据自身的缺陷"写成 4 个产品缺陷。

| # | 假红形态 | 表象 | 根因（**判据侧，不是产品侧**） | 治法 | 纠正后读数 |
|---|---|---|---|---|---|
| 1 | **测试自行解析被测系统的产物** | A5.1~A5.6 全红：「导出 0 行 0 表头」 | 自写 zip 解析器按 **local file header** 读长度；而 **Apache POI 写的是 streamed zip**（general-purpose flag bit 3 = data descriptor），local header 的 size 字段**全为 0** ⇒ 9 个条目全读成空。**自相矛盾读数**（5500 字节却"0 行"）本该当场发现 | 改为**从 central directory（EOCD）解析**；并加"自写 xlsx 回读"非空自证 | 导出 **402 行 == 列表 total 402**、表头逐字 7 列 ✅ |
| 2 | **期望与真实契约不符** | B1.1/B1.2/B1.3 全红：「批量上架 3/3 失败」 | 期望写成了"draft 应能上架"，而 `batchOnShelf` 白名单 = `Set.of("off_sale")`（注释逐字）⇒ 系统**正确地**拒绝 | `draft` 改判**负例**（如实拒绝+DB 零变更）；补**正对照链**（状态机 `draft→on_sale` → `batch/off-shelf` → `batch/on-shelf` 两跳全成功） | B1 全绿（含 2 条正对照）✅ |
| 3 | **schema 前提不成立 + 软删语义误读** | B3.1 红：「孤儿 `product_skus/product_colors/stock_ledger_entries` 各 1 行」 | ①`product_skus`/`product_colors` **没有** `deleted` 列；②`batch/delete` 是**软删**（parent 行仍在 `deleted=1`）⇒ 子行保留**是设计**；**孤儿只能定义为"parent 行不存在"** | 改判：软删语义（parent 在、子行留）+ **真孤儿全表扫描** | 真孤儿 **0**、8 条 FK 现查 ✅ |
| 4 | **给不存在的列加过滤条件** | C1.3 两处「dangling = `ERR … column does not exist`」 | 我把 `production_operation_positions` 写成有 `operation_id`（实际按 `logical_name` 寻址）、给 `…_position_price_versions` 加了 `status`（该表无此列）。**psql 报错 ≠ 命中** | 列名以 `information_schema` **实测**为准；不可执行记 skip | 4 组引用列活跃命中 **全 0** ✅ |
| 5 | **判据自相矛盾** | D5.1 红：「存储隔离失败」 | 我的正则要求"**含** directory 段 **且** **不得**以 `uuid.ext` 结尾"—— 后半句与远端存储规则 `{directory}/{yyyy/MM/dd}/{uuid}{ext}` **正面冲突**（每个合法 URL 都以 uuid.ext 结尾） | 改为只判"含 `{dir}/{yyyy}/{MM}/{dd}/`" | D5.1 绿 ✅ |
| 6 | **期望过严（产品未声明的行为）** | A4.3 红（半条） | 我把"`.csv` 扩展名也必须 ≥400"当判据，而产品只声明 xlsx（前端 `accept=".xlsx,.xls"`、模板名 `.xlsx`、POI `WorkbookFactory`）⇒ CSV 属**未定义行为** | 拆成两半：伪 `.xlsx` ⇒ 4xx（**保留为有效判据**）+ `.csv` ⇒ **口径登记** | A4.3a ✅ / A4.3b 登记 |
| 7 | **夹具命名碰撞**（本轮唯一未完全回绿者） | F2 红：注入后 `restored=2`（未回到 1） | `probeSku()` 的 `<tag>` 用 `Date.now().toString(36)`（**毫秒**精度）⇒ 同毫秒内连续两次调用产出**完全相同的货号**（实测三次连续调用全为 `L2-F-MURZCCP8`）⇒ "按货号计数"把两个商品并成一个口径 | 待修：`probeSku` 加随机后缀/自增序号 | F2 **红半段成立**（1→2，sha256 `770c016f…`≠`eb93f353…`）、**回绿半段未证**（已如实记 fail，未粉饰） |

**另有一条"注入被拒"的诚实登记**（F1）：我原想用「注入一条真孤儿 ⇒ 扫描必须 >0」给孤儿扫描做红证，**注入被 FK 当场拒绝** ⇒ 该判据**在结构上无法被违反** ⇒ 判定它**无判别力**，把 B3.2 从 pass 改判为 §5 的"未判定（结构性保证）"。**这正是红证的价值：它推翻的是判据，不是产品。**

### 7.1 事实订正（我原先的假设错了，已订正）

| # | 我原先的假设 | 实测事实 |
|---|---|---|
| C-1 | 「`products` 的这些引用表都没有 FK，所以必须显式扫孤儿」 | **错**：实测 **8 条 FK** 指向 `products`（`fabric_remnants` / `inbound_order_items` / `product_attributes` / `product_colors` / `product_skus` / `stock_batch_consumptions` / `stock_batches` / `stock_ledger_entries`）。我最初的 `information_schema` 查询写法有误（`constraint_column_usage` 的 join 方向）⇒ 得出了"无 FK"的错误结论 |
| C-2 | 「API 建的商品 id 会带我给的 `l2` 前缀，所以清理可按 id 前缀」 | **错**：id 是服务端生成的**随机 32 位 hex**。按 id 前缀清理会漏（并被 FK 拦下）⇒ 命名域必须含 `name`/`sku_code` |
| C-3 | 「上传落本地磁盘，可查 `uploads/` 判"不落盘"」 | **错**：运行存储是 **OSS**（`@Primary` + 凭据齐备）。本机 `uploads/` 的 152 个文件**不是**本轮落点 |
| C-4 | 「`.csv` 内容不是 xlsx，一定 4xx」 | **错**：`WorkbookFactory.create` **按内容**解析，扩展名不参与判断；我给的文件内容是合法 xlsx ⇒ 200 |
| C-5 | 「`detach-and-delete` 二次调用应是 200 幂等 no-op（Service 注释逐字如此）」 | **实测 404**。注释与实现有落差（`selectById` 被 MP 逻辑删除过滤 ⇒ `notFound`）。**按"不得 5xx"判为通过**，落差记为本条口径登记，**不计产品缺陷** |

### 7.2 环境/纪律遵守

- 未跑全量档（`verify-all.sh gate/full`、`batch-gate`、全量 pytest）—— 遵守 §27 与任务硬纪律 7。
- 未改 MIGAO 业务代码、未改 `.github/cases/**`、未开 issue、未派单。
- 所有写 SQL 带 `-- probe-ok`；写操作前先做只读预演（`SELECT` 影响面）。
- 时间口径：本机 +08；harness 用 `Intl.DateTimeFormat{timeZone:'Asia/Shanghai'}`（**踩过**：进程 `TZ` 非 +08，`getTimezoneOffset()` 返回 0 ⇒ 会把 13:40 +08 读成 21:40）。
