# issue #7597 验收证据：V189 破坏性数据迁移的真库执行

## 为什么单独留一份证据

V189 会把**所有租户**的 `product_skus.stock` 重算一遍（用户已裁定：「清零，只认真实入库」，
该选项原文写明「会改变现网可售数量，风险最高」）。而仓库对迁移的判据是**静态**的：

- `test_migration_immutability.py`（指纹账本只追加）
- `test_migration_idempotency.py`（文本层幂等线索）
- `test_migration_references_exist_in_schema.py`（表/列名存在）

**没有任何测试真的在 PostgreSQL 上执行 V189** ⇒ 语法错误、FK 违例、`ck_stock_ledger_reason`
约束、`NUMERIC` 类型不匹配这类问题在 CI 上都是零信号。所以本目录留一份**可重放**的真库脚本。

## 怎么重放

需要 `initdb` / `pg_ctl` / `psql`（本机 Homebrew 或 CI 的 PG 二进制均可）：

```bash
python3 acceptance/2026-10-24-7597-product-stock-from-documents/verify_v190_migration.py
```

脚本在 `/tmp/v189pg`（端口 55499、unix socket、只监听 socket 不监听 TCP）起一个**一次性**集群，
`db/init/schema.sql` 建全量 schema，造 6 种库存形态，跑迁移两遍，逐项断言，最后关集群。
不碰任何既有数据库。

## 覆盖的形态与期望

| 形态 | 改前 `stock` | 台账 | 迁移后 | 为什么 |
|---|---|---|---|---|
| 纯手工库存（从没入过库） | 30 | 无 | **0** + 一条 `manual` 补偿行 30→0 | 用户选择的「清零」 |
| 入库 100 + 订单 -10 | 100 | inbound/order | **90**，补偿行 100→90 | 真实单据净额保留，不误清零 |
| 入库 50 + **手工调整** -20 | 30 | inbound + manual(手工调整) | **50**，补偿行 30→50 | 手工调整不算真实单据 |
| 入库 20 + **批次盘点** +5 | 0 | inbound + manual(「库存盘点：」) | **25**，补偿行 0→25 | 盘点属于真实单据口径 |
| 入库 5 + 订单 -12（净额 -7） | 0 | inbound/order | **0**，**不落补偿行** | clamp ≥ 0；0 变更不写噪声行（与手工调整同口径） |
| 无 SKU 的商品 | 77 | — | **0** | 派生列 = SKU 汇总 |

## 实跑输出（2026-10-24）

```
✅ V189 真库验证通过：清零 / 真实单据保留 / 盘点计入 / 负数 clamp / 补偿行 / 幂等 / 账实一致
```

幂等读数：第二遍执行 ⇒ `stock_ledger_entries` 行数不变（`before_cnt == after_cnt`）、
各 SKU 库存不变。账实一致读数：所有补偿行的 `after_qty` 都等于库里 `product_skus.stock`。

## 边界

- 脚本只验证**迁移本身**（数据面），不验证应用启动链路（`MigrationRunner` 的登记/跳过语义由
  `MigrationRunner*Test` 覆盖）。
- 临时集群只监听 unix socket（`listen_addresses=''`），端口固定 55499，仅本机可见。
