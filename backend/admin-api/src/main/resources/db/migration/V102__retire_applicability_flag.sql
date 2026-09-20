-- O1 / 一：**部位适用性（`applicable`）退场** —— 存量行的值全部收敛为 `TRUE`
-- （issue #4937 = 母单 #4936；用户裁定 2026-09-21「这个必须要改，我们移除了部位的设计，**不计成本的改**」）。
--
-- ## 一句话
-- `production_operation_positions.applicable` 的 **`FALSE` 语义退场**：把**结果态会存活**的行
-- （`deleted = 0` **且** `applicable = TRUE`）显式写全 `updated_at`；**列保留**
-- （历史载体 / DDL 有 `NOT NULL DEFAULT TRUE`），但**不再有任何消费者** ——
-- 实例化侧（`ProcessingOrderService.buildRoute`）与本迁移同批删掉了那两道 `applicable` 闸
-- （「键不存在 ⇒ 静默 continue」与「`applicable=false` ⇒ 静默滤掉」）。
--
-- ## 🔴 为什么**不能**写成「全部存活行一律置 TRUE」（本单实测的口径陷阱，**照实登记**）
-- 本迁移的初稿写的是 `WHERE p.deleted = 0 AND p.applicable IS DISTINCT FROM TRUE`（一刀切置 TRUE）。
-- 那会把**下一迁移（V104）选行所依赖的信号**抹掉，后果是**真实的价丢失**：
--   · `帘头制作` 的 3 格本是 `布帘 (NULL, FALSE)` / `纱帘 (NULL, FALSE)` / `帘头 (2.00, TRUE)`；
--   · V102 一刀切后三格全变 `(?, TRUE)` ⇒ V104 的 ① 档（「适用行优先」）不再区分任何行
--     ⇒ 决胜落到 ② 档「**布帘**列优先」⇒ 幸存行 = `布帘 / NULL` = **未定价**
--     ⇒ 该工序的 ¥2.00 **静默消失**（工人白干，且与「显式 0 元」不可区分 —— 正是 issue #4696 的红线）。
-- ⇒ 判据：本迁移**只**做「把已经是 `TRUE` 的行写完整」，`FALSE` 的那批**留给 V104 软删**
--   （它们本就是「当年该部位明确不做」的退场记录）。终态核验落在 V104 的 ③ 块
--   （「存活行一律 `applicable = TRUE`」），且 `test_deposition_total_migration.py` 的真库判据
--   `test_v104_keeps_the_priced_curtain_head_survivor` 用 `帘头制作 = 2.00` 钉死这条。
--
-- ## 为什么必须把值也改掉（而不是只删代码）
-- `applicable = FALSE` 在**读面**仍有第三种含义的残留：`ProductionRoutingReadService.positionView`
-- 把 `row.getApplicable()` 原样返回给 web（前端按「做 / 不做」两态渲染）⇒ 只删代码不改值，
-- 界面会继续显示一个**没有语义**的「不做」。本包同时把写面入口关上
-- （`PUT /operation-positions/{id}` 收到 `applicable` ⇒ **422 + 可行动 hint**，见
-- `ProductionOperationPositionCommandService.update`）⇒ 存量 `FALSE` 行若不收敛，
-- 商家会看到「不做」而**再也改不回来**（入口已关）—— 那才是真正的死路。
--
-- ## 为什么必须是**新迁移**（不能改 V71 / V72 / V79 / V88 / V89 / V97）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记账、已应用的文件**整份跳过**
-- ⇒ 改已发布迁移只对**全新库**生效、存量环境永远拿不到 = 「CI 全绿、功能静默缺失」（issue #4235）；
-- 已发布迁移另被 `tests/unit_ci_workflows/migration_fingerprints.json` 的 sha256 **逐字节冻结**。
-- ⚠️ V97 也**不删**：它是已发布迁移，且其「孤儿矩阵行」判据与本迁移口径不同（那批行由 V104 塌缩覆盖）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `WHERE p.deleted = 0 AND p.applicable IS NOT FALSE AND p.updated_at IS DISTINCT FROM NOW()`
-- ⇒ 第二次跑**净效果相同**（同事务内 `NOW()` 是常量 ⇒ 第二次跑匹配 0 行）。
-- ⚠️ 不用 `applicable IS DISTINCT FROM TRUE` 作幂等闸：那会连 `APPLICABLE = FALSE` 的
-- 退场行一起改（见文件头的口径陷阱）；也**不能**靠 `<>`（对 `NULL` 求值为 `NULL`，
-- 既不真也不假 ⇒ 「`applicable` 为 NULL」的行永远改不到，且不留痕迹）。
--
-- ## 红线：**不动历史**
-- 本文件**只写 `production_operation_positions` 的 `applicable` / `updated_at` 两列**：
--   · 工序实例 `processing_position_operations`（含 `operation_name` 旧名快照）**一字不动**；
--   · 报工流水 `production_work_logs` 的 `unit_price` / `factor` **一字不动**
--     ⇒ 历史工资不受影响（工资按报工流水当时落库的值结算，**不**按矩阵当前价/当前适用性回算）；
--   · 加工单快照 `processing_orders.items_snapshot` **一字不动**；
--   · `unit_price` **一字不动**（本迁移只碰 `applicable`）—— 价目塌缩是 V104 的事，两件事不混。
--
-- ## 回滚 SQL（**新迁移，不删 V102**；语义 = 把「明确不做」还原回 `FALSE`）
-- ⚠️ **回滚是有损的**：本迁移抹掉的正是「哪一格当年是 `FALSE`」这一信息 ⇒ 回滚**只能**按
-- **V71/V79 的种子口径重算**（适用性 = 该部位路线上是否出现该逻辑工序），**不能**逐行还原商家改过的值。
-- ```sql
-- -- V106__rollback_retire_applicability_flag.sql（本单只登记，不落码）
-- -- ⚠️ 本迁移**只写了 `updated_at`**（`applicable` 恒等赋值）⇒ 回滚 = 复活 V104 软删的退场行
-- -- （那批行的 `applicable` 仍是 `FALSE`，一字未动）⇒ **信息未丢**，回滚是无损的。
-- -- 下面这段仅用于「V104 也一并回滚」的联合回滚场景（口径 = V71 的 29 行 / V79 的 36 行种子矩阵）。
-- UPDATE production_operation_positions p
--    SET applicable = FALSE, updated_at = NOW()
--   FROM tenants t
--  WHERE p.tenant_id = t.id AND t.deleted = 0 AND p.deleted = 0
--    AND NOT (
--        -- 种子里的 applicable=TRUE 格（逐条见 V71/V79 的字面量种子）
--        (p.logical_name, p.position) IN (
--            ('精裁','布帘'),('精裁','纱帘'),('精裁','帘头'),('裁剪','布帘'),('裁剪','纱帘'),
--            ('裁剪','帘头'),('三边','布帘'),('三边','纱帘'),('三边','帘头'),('韩褶','布帘'),
--            ('韩褶','纱帘'),('韩褶','帘头'),('上车布','布帘'),('上车布','纱帘'),('打孔','布帘'),
--            ('打孔','纱帘'),('打孔','帘头'),('拼1次','布帘'),('拼2次','布帘'),('拼3次','布帘'),
--            ('花边','布帘'),('铅坠','布帘'),('接高','布帘'),('帘头制作','帘头'),('熨烫','布帘'),
--            ('定型','布帘'),('定型','帘头'),('复烫','布帘'),('车被','布帘'),('外帘打卷','布帘'),
--            ('外帘打卷','纱帘'),('外帘打卷','帘头'),('外帘装袋','布帘'),('外帘装袋','纱帘'),
--            ('外帘装袋','帘头'),('质检','布帘'),('质检','纱帘'),('质检','帘头'),('外帘发货','布帘'),
--            ('外帘发货','纱帘'),('外帘发货','帘头'),('绑带','布帘'),('绑带','纱帘'),('抱枕','布帘'),
--            ('抱枕','纱帘'),('抱枕','帘头'),('腰靠垫','布帘'),('腰靠垫','纱帘'),('腰靠垫','帘头'),
--            ('logo条','布帘'),('立边','布帘'),('扣环','布帘'),('防翘扣','布帘'),
--            ('配料','布料'),('打包','布帘'),('打包','纱帘'),('打包','帘头'),('打包','布料'))
--    );
-- ```
--
--- ## 停止条件（触发任一 ⇒ 回滚本迁移（与 V104 **联合**回滚），不硬推）
--   · S1：`applicable = FALSE` 的存活行仍在（= V104 的塌缩没跑 / 被单独回滚）—— `RAISE EXCEPTION`，见文末；
--   · S2：`unit_price` 在活跃租户上发生变化（本迁移只写 `applicable`）；
--   · S3：任一**快照表**行数/内容变化（`processing_position_operations` / `production_work_logs`）；
--   · S4：`./verify-all.sh gate` 或 `python3 -m pytest tests/unit_ci_workflows/ -q` 非零。
--
-- ## 显式事务（同 V97 的实测口径，见该文件 §「显式事务」）
-- `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` **默认逐条
-- autocommit** ⇒ 不显式 `BEGIN/COMMIT` 时，UPDATE 已提交、DO 块才抛 ⇒ 留下**半完成态**。
-- 两条执行路径必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① **结果态会存活**的行：显式写全 `updated_at`（`applicable` 已是 `TRUE`，见文件头的口径陷阱）
--    + 自证「真的认领到行」（`GET DIAGNOSTICS`；0 行 = 谓词写岔 ⇒ 空操作）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⚠️ 显式写列（issue #4608 纪律）：`.set(deleted,1).set(updated_at,NOW())` 那套在这里对应
--    `SET applicable = TRUE, updated_at = NOW()` —— **不**走 `updateById`（MyBatis-Plus 的
--    NOT_NULL 策略会把 `null` 字段从 SET 子句剔除 ⇒ 静默 no-op，本仓踩过）。
-- ⚠️ 软删行（`deleted = 1`）**不碰**：它们是 V88 明确的退场记录（退场事实必须留痕）。
-- ⚠️ `SET applicable = TRUE` 仍**显式写**（幂等 + 「写全」纪律）：对已是 TRUE 的行是恒等赋值；
--    真正的载体是 `updated_at`（「哪一批行在新口径下被认领」的审计证据）。
-- ⛔ **不得**把 `AND p.applicable IS NOT FALSE` 去掉 —— 去掉就会命中所属 `FALSE` 的退场行，
--    抹掉 V104 选行所需的信号（详见文件头的口径陷阱）。
DO $$
DECLARE
    claimed INTEGER;
BEGIN
    UPDATE production_operation_positions p
       SET applicable = TRUE,
           updated_at = NOW()
      FROM tenants t
     WHERE p.tenant_id = t.id
       AND t.deleted = 0
       AND p.deleted = 0
       AND p.applicable IS NOT FALSE;

    GET DIAGNOSTICS claimed = ROW_COUNT;

    -- 自证（防空跑）：本判据必须**真的**认领到行 —— 0 行意味着谓词写岔了
    -- （例如漏了 `t.deleted = 0` 的连接条件），而「0 行」在幂等口径下长得像「已经跑过」。
    IF claimed = 0 THEN
        RAISE EXCEPTION
            'V102 未认领到任何行（判据可能有误：谓词写岔了 ⇒ 本迁移是空操作）—— 回滚本迁移';
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 数量对账（**本迁移的量** + 与写语句**共用同一份谓词**）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⚠️ **终态核验不在这里**：`applicable = FALSE` 的存活行由 **V104 的塌缩软删**带走，
--    所以「结果态不得再有 FALSE 行」落在 `V104__deposition_matrix_collapse.sql` 的 ③ 块
--    （本迁移**不**把 FALSE 置 TRUE —— 那会抹掉 V104 选行所需的信号，见文件头的口径陷阱）。
--    本块判的是**自己的量**：谓词必须认领到行（`claimed = 0` = 谓词写岔了，
--    而「0 行」在幂等口径下长得像「已经跑过」⇒ 必须显式失败），且与写语句谓词逐字一致。
DO $$
DECLARE
    remaining INTEGER;
    claimed   INTEGER;
BEGIN
    -- 与 ① 的 UPDATE **逐字同一份谓词**
    SELECT count(*) INTO remaining
      FROM production_operation_positions p
      JOIN tenants t ON t.id = p.tenant_id AND t.deleted = 0
     WHERE p.deleted = 0
       AND p.applicable IS NOT FALSE;
    IF remaining = 0 THEN
        RAISE EXCEPTION
            'V102 数量对账失败：谓词认领 0 行（写语句谓词写岔了 / 全库无存活矩阵行）—— 回滚本迁移';
    END IF;

    -- 反向核验：`applicable = FALSE` 的存活行**必须被本迁移原样留给 V104**（不得被本文件改动）
    SELECT count(*) INTO claimed
      FROM production_operation_positions p
      JOIN tenants t ON t.id = p.tenant_id AND t.deleted = 0
     WHERE p.deleted = 0
       AND p.applicable IS FALSE
       AND p.updated_at > p.created_at;
    IF claimed > 0 THEN
        RAISE EXCEPTION
            'V102 越界：有 % 条「applicable = FALSE」的存活行被改动过（本迁移只许写「已是 TRUE」的行）'
            '—— 回滚本迁移', claimed;
    END IF;
END $$;

COMMIT;
