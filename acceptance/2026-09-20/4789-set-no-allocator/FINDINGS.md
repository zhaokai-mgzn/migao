# #4789 真库/端到端核实 —— 新单套号分配器

> 环境说明：**云 dev RDS 对本机间歇不可达**（本会话实测：`recon.sh` 连续 8 次 `timeout expired`，
> 见 `recon-output.txt`）⇒ 本目录的端到端判据跑在**本地 PostgreSQL 16**（`initdb` 自建实例），
> DDL **逐字取自** `docs/sql/schema.sql`（= V92 终态，两表 + 4 个部分唯一索引），
> SQL **逐字取自** `ProcessingOrderSetMapper` / `ProcessingSetPartTokenMapper` 的 `@Insert`/`@Select`
> 与 `ProductionScanService.selectionView` 的查询。运维 SQL（云库复跑）见 `ops.sql`。

## 复跑
```bash
./run.sh              # 分配器已落码（绿）
./run.sh --no-alloc   # 不跑分配器（= 改前状态）⇒ 红证
```

## ① 红证（改前：新单无套号 ⇒ 码无从生成 ⇒ 扫码清单为空）
```
════ ② 工人 H5 扫一扫：服务端读面 SQL（ProductionScanService 的逐字查询）════
--- 扫码解析入口：既有四形态之一（qr_token）解析到加工单 ---
   id    | processing_order_no 
---------+---------------------
 po-4789 | JG-20260920-0001
(1 行记录)

--- selectionView：该单的「套 × 部位」可选清单（**新单此前这里是空的**）---
 set_no | set_index | order_item_id | position_kind 
--------+-----------+---------------+---------------
(0 行记录)

--- 套数（1 樘「布+纱+帘头」= 1 套；另一樘独立窗 = 1 套 ⇒ 共 2）---
 live_sets 
-----------
         0
(1 行记录)

--- 新码（部位码）直扫：token → 套 × 部位（第一优先形态）---
 token | set_no | order_item_id | position_kind 
-------+--------+---------------+---------------
(0 行记录)

--- 反例（不许恒真）：不存在/已撤销的 token 必须 0 行 ---
 rows_for_revoked_token 
------------------------
                      0
(1 行记录)

exit=0
```

## ② 绿证（改后：1 樘窗 = 1 套；扫码清单有 (套 × 部位)；部位码可直扫）
```
DDL 抽取自检：processing_order_sets=1 uk_set_part_tokens_part=1
════ ① 分配器（ProcessingOrderSetMapper 的逐字 SQL；2 樘窗 ⇒ 2 行套）════
INSERT 0 1
INSERT 0 1
 set_index |        set_no        | craft_line_id |   position_item_ids   
-----------+----------------------+---------------+-----------------------
         1 | JG-20260920-0001-001 | cl-A          | ["i-1", "i-2", "i-3"]
         2 | JG-20260920-0001-002 | i-9           | ["i-9"]
(2 行记录)

--- 幂等：同一条再插一次（必须仍 2 行）---
INSERT 0 0
 live_sets_after_repeat 
------------------------
                      2
(1 行记录)

--- 实例行落 set_id / set_no（按 position_item_ids 归属；V92 的回填 UPDATE 同形）---
INSERT 0 4
UPDATE 4
 order_item_id | set_id |        set_no        
---------------+--------+----------------------
 i-1           | set-1  | JG-20260920-0001-001
 i-2           | set-1  | JG-20260920-0001-001
 i-3           | set-1  | JG-20260920-0001-001
 i-9           | set-2  | JG-20260920-0001-002
(4 行记录)

--- 部位码（ProcessingSetPartTokenMapper 的逐字 SQL；一部位一码 + 复用不换码）---
INSERT 0 4
INSERT 0 0
 set_id | order_item_id | token  
--------+---------------+--------
 set-1  | i-1           | tok-i1
 set-1  | i-2           | tok-i2
 set-1  | i-3           | tok-i3
 set-2  | i-9           | tok-i9
(4 行记录)


════ ② 工人 H5 扫一扫：服务端读面 SQL（ProductionScanService 的逐字查询）════
--- 扫码解析入口：既有四形态之一（qr_token）解析到加工单 ---
   id    | processing_order_no 
---------+---------------------
 po-4789 | JG-20260920-0001
(1 行记录)

--- selectionView：该单的「套 × 部位」可选清单（**新单此前这里是空的**）---
        set_no        | set_index | order_item_id | position_kind 
----------------------+-----------+---------------+---------------
 JG-20260920-0001-001 |         1 | i-1           | 布帘
 JG-20260920-0001-001 |         1 | i-2           | 纱帘
 JG-20260920-0001-001 |         1 | i-3           | 帘头
 JG-20260920-0001-002 |         2 | i-9           | 布帘
(4 行记录)

--- 套数（1 樘「布+纱+帘头」= 1 套；另一樘独立窗 = 1 套 ⇒ 共 2）---
 live_sets 
-----------
         2
(1 行记录)

--- 新码（部位码）直扫：token → 套 × 部位（第一优先形态）---
 token  |        set_no        | order_item_id | position_kind 
--------+----------------------+---------------+---------------
 tok-i2 | JG-20260920-0001-001 | i-2           | 纱帘
(1 行记录)

--- 反例（不许恒真）：不存在/已撤销的 token 必须 0 行 ---
 rows_for_revoked_token 
------------------------
                      0
(1 行记录)

exit=0
```

## ③ 迁移：**本单不加迁移**（优先不加）

`processing_order_sets` / `processing_set_part_tokens` 的**载体与唯一键**已由 **V92**（#4698 切片⓪，
merge `d295097bb`）建好，本单只是补**写方** ⇒ 按 issue 的「若不需要迁移 ⇒ 优先不加」执行。
迁移头现取读数（不写死）：`V96` / `V97` / `V98`（V98 为最大）；**V92 指纹冻结，本单零命中**。

机械核验（本单的 diff 里没有任何 `db/migration/**` 文件）：

```bash
git diff --name-only origin/main...HEAD | grep -c 'db/migration'   # ⇒ 0
```

## ④ 云 dev RDS 不可达（如实登记）

`./recon.sh` 连续 **8 次** `timeout expired`（本机出口 IP 间歇性不在白名单，同 #4741/#4672 的已知形态）
⇒ 原始读数见 `recon-output.txt`；**运维复跑 SQL 见 `ops.sql`**（含历史值 md5 红线基线与分配器上线后的
验收读数）。本单的端到端判据因此跑在**本地 PG 16**（DDL/SQL 逐字取自仓库），**不是**推理。

## ⑤ 端到端链路（新单 ⇒ 有码 ⇒ 扫得到）

```
新单 → ProcessingOrderService.generateOne（落 processing_order_no）
     → ProductionService.instantiate
        ├─ ⓪.5 ProcessingOrderSetAllocator.ensureSets（快照分组 ⇒ processing_order_sets 1 樘窗 = 1 行）
        ├─ 实例行落 set_id / set_no（V92 六列中的两列，此前零写方）
        └─ 部位码 processing_set_part_tokens（一部位一码，此前零写方）
     → 加工单生产明细页「生成二维码（测试用）」（码 = 加工单号，纯前端只读）
     → 工人 H5 扫一扫 → GET /api/admin/production/scan
        → ProductionScanService.degradedView → selectionView：**套 × 部位清单非空**（改前为空）
        → 选一次部位 → 报工
```

**能机械验的已验**（本目录 ①②）；**不能机械验的给可执行判据**：加工单生产明细页的二维码弹层
内容 = 加工单号（前端纯函数 `QRCodeSVG value={po.processingOrderNo}`，零写请求）⇒ 扫该单号必然命中
`resolveOrder` 的 `processing_order_no` 形态，其 `selections` 由上面已验证的 SQL 产出。

## ⑥ CI（PR #4805，head `af0ffd850`）

`gh pr checks 4805 --watch` **一次**跑完（零 `sleep` 轮询）：**全部 pass，0 fail**
（admin-api unit tests / admin-web typecheck + unit tests / QA Growth Gate / Case Trust Gate /
Case Contract / Case Coverage Gate / Drift Audit / UI Regression Check / E2E quality gate /
ci workflow helper unit tests / ai-agent-service / bmini-app / mini-app / xiaobu H5 visual /
Secret Scan / Danger Scan / Check Closes / LLM Sink Ledger）。
`Enable auto-merge` 与 `Label needs-changes on any CI failure` 为 **skipping**（draft PR + 无失败 ⇒ 预期）。

## ⑦ 自查（机械判据）

```bash
git diff --name-only origin/main...HEAD | grep -c 'db/migration'        # ⇒ 0（V92 一字不动）
git diff --name-only origin/main...HEAD | grep -c 'frontend/'           # ⇒ 0
git diff --name-only origin/main...HEAD | grep -c '\.agent-presets/'    # ⇒ 0
git diff --name-only origin/main...HEAD | grep -c '\.github/workflows/' # ⇒ 0
head -1 backend/admin-api/src/test/java/com/migao/admin/service/ProcessingOrderSetAllocatorTest.java
#   ⇒ // case_ids: PG-018（第 1 行、注释起始、只此一处）
```
