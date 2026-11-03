-- issue #7255：收款码 / 角色两张表的唯一键 ensure（应用层幂等写的守门人）
--
-- 病（#7255 台账第 3、4 行）：两处写面都是「selectOne 判空 → insert」——并发下两个请求都判「不存在」，
-- 于是都插。表上有唯一键时第二个请求抛 DuplicateKeyException 冒泡成 500（用户看到「服务器内部错误」）；
-- 表上没有唯一键时更坏：静默写出第二行，而读侧 selectOne 直接 TooManyResultsException（同样是 500）。
--
-- 🔴 为什么本迁移还要再写一遍（既有载体各缺一半，仓内**无法证明**存量库的形状）：
--   ① `roles (tenant_id, code)`：这条 UNIQUE **只出现在建库脚本 `db/init/schema.sql` 的表定义里**，
--      归档链（V1..V122）与活目录里**没有任何一条迁移承载它** ⇒「存量库到底有没有它」仓内无法证明
--      —— #7255 台账把它记成「无 uk」正是这个证据缺口的产物（不是记错了）。
--   ② `tenant_payment_qrcodes`：部分唯一索引 `uk_payment_qrcode_tenant_type` 在**归档链 V48** 里
--      （存量库已经跑过它），本迁移对它**必然是 no-op**。写进来只为把「唯一键一定存在」钉成
--      **不依赖归档链**的保证：归档链将来若被重切 / 重建（#5243 那套制度），这条保证不会跟着消失。
-- ⇒ 两份都是 **ensure 语义**（已经存在 ⇒ RAISE NOTICE，什么都不做），本迁移**可重复执行**。
--
-- 🔴 存量重复行会怎样：**本迁移不删任何数据、不改任何行**。
--    发现重复 ⇒ RAISE WARNING + **跳过建索引**，部署照常成功（与 V166 / V167 同口径：
--    删数据是业务决策，迁移不替人决定）。人工清理后**重跑本迁移**即可（重跑幂等）。
--    运维先查口径（只读，可直接复制）见 PR body 的「存量重复行处置」节。
--
-- 🔴 本迁移**故意**把 roles 的唯一性建成**全表**（不带 `WHERE deleted = 0`），与建库脚本的表内
--    UNIQUE **逐字同语义**。改成「活跃行唯一」会放松「删掉的角色 code 不能被新角色复用」这条
--    现有语义 —— 那是**权限面口径**决策，不属于本单（#7256 只对 user_roles 做过那种下放）。
--
-- 执行形态：**整份文件 = 一个 DO 块 = 一条语句**（`MigrationRunner` 是 `jdbc.execute(整份文本)`，
-- 一条语句 ⇒ 一个隐式事务；任一步失败整份回滚且不记账，下次启动重跑）。
DO $$
DECLARE
    dup_pairs INTEGER;
    covered   BOOLEAN;
BEGIN
    -- ────────────────────────────────────────── ① 收款码：(tenant_id, payment_type) 活跃行唯一
    SELECT COUNT(*) INTO dup_pairs FROM (
        SELECT tenant_id, payment_type
          FROM tenant_payment_qrcodes
         WHERE deleted = 0
         GROUP BY tenant_id, payment_type
        HAVING COUNT(*) > 1
    ) d;
    IF dup_pairs > 0 THEN
        RAISE WARNING 'tenant_payment_qrcodes 存在 % 组活跃重复的 (tenant_id, payment_type) ⇒ 本次**不建**唯一索引；'
                      ' 请先清理重复行（保留哪一行属人工决策）再重跑本迁移（issue #7255）', dup_pairs;
    ELSE
        CREATE UNIQUE INDEX IF NOT EXISTS uk_payment_qrcode_tenant_type
            ON tenant_payment_qrcodes (tenant_id, payment_type) WHERE deleted = 0;
        RAISE NOTICE 'tenant_payment_qrcodes 活跃行唯一索引已就绪（issue #7255）';
    END IF;

    -- ────────────────────────────────────────── ② 角色：(tenant_id, code) 全表唯一
    -- 「是否已覆盖」按 pg_index **现取**，不猜约束名（表内 UNIQUE 的名字是 PG 自动生成的，
    -- 与索引名不同；写死猜测会在不同建库路径上漏判 ⇒ 建出第二条冗余索引）。
    -- 只认**非部分**索引（indpred IS NULL）：部分索引（WHERE deleted = 0）语义不同，不算已覆盖。
    SELECT EXISTS (
        SELECT 1
          FROM pg_index i
         WHERE i.indrelid = to_regclass('roles')
           AND i.indisunique
           AND i.indpred IS NULL
           AND (SELECT array_agg(a.attname::text ORDER BY a.attname)
                  FROM pg_attribute a
                 WHERE a.attrelid = i.indrelid
                   AND a.attnum = ANY (i.indkey::int2[]))
               = ARRAY['code', 'tenant_id']
    ) INTO covered;

    IF covered THEN
        RAISE NOTICE 'roles (tenant_id, code) 唯一键已存在 ⇒ 跳过（issue #7255）';
    ELSE
        SELECT COUNT(*) INTO dup_pairs FROM (
            SELECT tenant_id, code
              FROM roles
             GROUP BY tenant_id, code
            HAVING COUNT(*) > 1
        ) d;
        IF dup_pairs > 0 THEN
            RAISE WARNING 'roles 存在 % 组重复的 (tenant_id, code) ⇒ 本次**不建**唯一索引；'
                          ' 请先清理重复行再重跑本迁移（issue #7255）', dup_pairs;
        ELSE
            CREATE UNIQUE INDEX IF NOT EXISTS uk_roles_tenant_code ON roles (tenant_id, code);
            RAISE NOTICE 'roles (tenant_id, code) 唯一索引已就绪（issue #7255）';
        END IF;
    END IF;
END $$;
