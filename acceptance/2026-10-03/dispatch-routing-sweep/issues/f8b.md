人为要求：用户 2026-10-03 逐字「按「发现即并行」继续推进」；证据来自线③ 配置写面横切扫描（`acceptance/2026-10-03/config-writeface-sweep/REPORT.md` §F1）与线① 的 F8Z-03。

## 现象（写后等价性越界；#6102 只修了「价取错」，没修「行本就不该被建」）

对一道**矩阵里没有「布帘」行**的工序发一个**与价目无关**的写请求：

```
POST /api/admin/production/operations {name:…, group_name:…, unit:"米", unit_price:0.55, scope:"position", positions:["通用"]}
  ⇒ 建成时矩阵只有「通用」一行
PUT  /api/admin/production/operations/{id}  body {"scope":"set"}   （payload 键数 = 1）
  或更短：                                body {}                  （键数 = 0）
  ⇒ 字段级 diff 越界 1 处：production_operation_positions 多出一行 position=布帘
```

**触发前置（必须显式构造，否则假绿）**：该工序矩阵里**没有**「布帘」行（`attachPositions` 只补**不存在**的列；已有 ⇒ 幂等跳过）。

**活体读数（既有生产数据）**：租户 20 上「只有 `通用` 一行」的工序有 **8 道**；`打包` 上累计的软删 `布帘` 孤儿行在**同一会话内从 6 → 9 → 13** 条（两次独立快照）⇒ **每次保存都往价目表塞一行，只增不减**。

## 与 #6102 的关系

`#6102`（已合并 `1d1fe5e55`，并已在本机修复后构建 `a4aaa3c24` 上**重放验证**：`p9-price-drift` 3/3 绿、工资侧 `3.33` 正确）修的是「**新行的价格取错**」⇒ 有效价被静默改写。
**本单修的是「新行本就不该被创建」** —— 残余的写面副作用（③ 已据此把级别从 P1 降为 P3：暂不伤钱，但等价性仍越界、且**只增不减**）。

## 验收判据（冻结，必须会红）

1. **最锋利的一条**：`PUT /api/admin/production/operations/{id}` body **`{}`（键数 0）** ⇒ 该工序的**价目行集合**（逐行逐字段，含 `deleted` 标记）**零变化**、有效价零变化。
2. **一般形态**：body 只含与价目无关的键（如 `{"scope":…}` / `{"group_name":…}`）⇒ 允许变化集 **只**等于 payload 键（外加显式声明的审计/版本字段）。
3. **不回归（三条都要判）**：① 显式带 `unit_price` ⇒ 按明示值生效；② **`create` 路径**（新建工序）的兜底建行行为**保持不变**；③ #6102 的既有判据（有效价逐字不变）仍绿。
4. **类级固化**：判据要写成「**任何工序设置写面调用后，该工序的价目行集合与有效价都必须逐字不变，除非该写面显式带 `unit_price` / `positions`**」，并**参数化覆盖多道工序**（不要只钉 `打包`）。
5. **红证**：把修复摘掉（或恢复兜底建行）⇒ 判据 1/2 必须红；读数逐字进 PR body。

## 可用工装（只读参考，别改）

`acceptance/2026-10-03/config-writeface-sweep/harness/*.mjs`（③ 的 before/after 字段级快照 + diff + 「前缀自建自清」写法）与 `out/*.json`（逐条读数）。真库凭据在 `backend/admin-api/.env`；**探针必须自建自清**并给出「探针存活残留 = 0」的机器读数。

## 写面纪律

`CHANGELOG.md` 不许碰（集成方独占）；**不许改 `.github/cases/**`**（同批另一包独占，测试文件只声明**既有**用例 id，候选 `PG-020`，确需新用例在回报里提）；不许碰 `frontend/**`、`schema.sql`、归档迁移、`.agent-presets/**`、以及 `ProductionOperationPositionCommandService`（另一包在改它）。
