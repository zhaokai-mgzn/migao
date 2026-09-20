# #4715 真库核实 —— 三道套级工序的 `scope` 实际取值分布

> 环境：云 dev 库 `ai_customer_service`（阿里云 RDS，本地 admin-api 同源）。凭据从
> `backend/admin-api/.env` 读取，**未写入任何产物**。
> 复跑：`./run.sh`（纯 `SELECT`，**无写操作**；SQL 见 `recon.sql`）。
> ⚠️ 本机出口 IP 间歇性不在 RDS 白名单（实测同一会话内 `psql` 在成功与
> `Operation timed out` 之间反复）—— 首次成功读数见下（`recon-output.txt` / 下文逐条）。

## 结论（读数来自真库，不是推理）

### ① 活跃租户 = 3 个

| tenant_id | name | industry |
|---|---|---|
| 1 | 词元通达 | other |
| 20 | 米高POC演示布艺 | curtain |
| 21 | POC彩排5605 | curtain |

### ② 三道工序的 `scope` 分布（逐活跃租户）

| tenant_id | 外帘打卷 | 外帘装袋 | 外帘发货 | source |
|---|---|---|---|---|
| 1 | `set` | `set` | `set` | 占位待确认 |
| 20 | —（工序库 0 行） | — | — | — |
| 21 | —（工序库 0 行） | — | — | — |

汇总：`scope='set'` **3 行 / 1 个租户**；`scope='position'` **0 行**。
⇒ **存量库里这三道没有错值行** —— 本单的缺陷载体是**开租播种模板**（`seed.json`），
即**修复后才开租的租户**；V95 的存量纠正本次在真库上匹配 **0 行**（幂等/安全，不是没生效）。

> ⚠️ 这与 issue 正文的推断（「开租租户上落 position」）**不矛盾**：模板是**新租户**的路径，
> 而真库现存的 3 个租户里只有 1 号有工序库（V54/V56 字面量种子 + V67 回填），
> 20/21 号是**空工序库**（历史遗留，与 #4685 实测一致）。故存量侧读数为 `set` 是对的。

### ③ `source` 列能否区分「播种 vs 商家自建」（V95 的判据）

| source | rows | tenants | id 前缀（op-v54-/v56-/v79-） |
|---|---|---|---|
| 占位待确认 | 33 | 3 | 33 |
| 推算 | 5 | 1 | 5 |
| **NULL** | **0** | 0 | 0 |

⇒ 判据可用：**`source IS NULL` = 0 行**（商家自建/历史行），播种来源一律非空
（V62 列注释冻结口径：`NULL` = 来源未知，不许读成「占位待确认」）。V95 按
`source IN ('占位待确认','推算')` 限定 ⇒ 真库上**不可能误伤商家自建**。

## 复跑命令与原始输出

```bash
./acceptance/2026-09-20/4715-tenant-scope-double-pay/run.sh
```

原始输出（首次成功读数，2026-09-20）：

```
=== ① 活跃租户 ===
 id |      name       | industry
----+-----------------+----------
  1 | 词元通达        | other
 20 | 米高POC演示布艺 | curtain
 21 | POC彩排5605     | curtain
(3 行记录)
=== ② 三道工序 scope × source（活跃租户，本单核心读数）===
 tenant_id |   name   | scope |   source   | verdict
-----------+----------+-------+------------+---------
         1 | 外帘发货 | set   | 占位待确认 | ok
         1 | 外帘打卷 | set   | 占位待确认 | ok
         1 | 外帘装袋 | set   | 占位待确认 | ok
(3 行记录)
=== ③ 汇总：活跃租户里 position / set 各多少行 ===
 scope | rows | tenants
-------+------+---------
 set   |    3 |       1
(1 行记录)
=== ④ source 分布（能否区分「播种 vs 商家自建」）===
   source   | rows | tenants | id_prefixed
------------+------+---------+-------------
 占位待确认 |   33 |       3 |          33
 推算       |    5 |       1 |           5
(2 行记录)
```

## 未完成 / 边界（如实登记）

- **`recon-output.txt` 的 ⑤~⑧ 段**（配料/打包对照、`source IS NULL` 计数、报工历史指纹、
  实例快照侧出现次数）在首次成功窗口内未跑完 —— 本机出口 IP 随后被 RDS 白名单拒（
  `Operation timed out`，同 #4548 的实测形态）。**已成功读到的 ①~④ 段足够支撑本单的判据**
  （三处口径分裂的载体是模板，不是存量库；V95 的判据 = `source`，读数 ④ 已证 `NULL` = 0）。
  剩余段的复跑入口已留在 `run.sh`（在有白名单的机器上直接跑即可）。
- **`processing_work_logs` 历史计件指纹**：本迁移的 DML **不碰**该表（由
  `ProductionOperationScopeMigrationTest#v95NeverTouchesHistoricalPieceworkValues` 落码，
  且该表的 `unit_price`/`factor` 不在 V95 的 `SET` 列表里）⇒ 无需真库读数即可判定「一字不动」。
