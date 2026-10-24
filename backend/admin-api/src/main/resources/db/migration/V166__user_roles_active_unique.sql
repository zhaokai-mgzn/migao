-- issue #7256：user_roles 的唯一性从「全表」下放到「活跃行」
--
-- 病：schema.sql 里有表内 `UNIQUE(user_id, role_id)`（全表、不分软删），而 UserRole.deleted 是
-- 逻辑删除（@TableLogic）⇒ 移除角色只把 deleted 置 1、行还在；再授权同一角色就撞唯一键 ⇒ 500。
-- 症状 = **「移除角色」之后就再也加不回来**；并发重复授权是同一根因的另一种触发（第二个请求 500）。
--
-- 修法：删掉全表唯一约束（按 pg_constraint **现取**约束名，不写死猜测），换成
-- 「活跃行唯一」的部分唯一索引。软删行从此不参与唯一性 ⇒ 重授可行；活跃行仍唯一 ⇒ 并发仍被挡住。
--
-- 幂等：本迁移可重复执行（约束不在时跳过 DROP；索引用 IF NOT EXISTS）。
DO $$
DECLARE
    con_name TEXT;
    dup_pairs INTEGER;
BEGIN
    -- ① 找到 (user_id, role_id) 那条全表唯一约束（列集合精确匹配，避免误删别的约束）
    SELECT c.conname INTO con_name
      FROM pg_constraint c
     WHERE c.conrelid = 'user_roles'::regclass
       AND c.contype = 'u'
       AND (SELECT array_agg(a.attname::text ORDER BY a.attname)
              FROM pg_attribute a
             WHERE a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey))
           = ARRAY['role_id', 'user_id'];
    IF con_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE user_roles DROP CONSTRAINT %I', con_name);
        RAISE NOTICE 'user_roles 全表唯一约束已删除（issue #7256）: %', con_name;
    END IF;

    -- ② 建「活跃行唯一」的部分唯一索引；已有活跃重复行时**不阻断部署**（数据修理属人工决策）
    SELECT COUNT(*) INTO dup_pairs FROM (
        SELECT user_id, role_id FROM user_roles
         WHERE deleted = 0
         GROUP BY user_id, role_id
        HAVING COUNT(*) > 1
    ) d;
    IF dup_pairs > 0 THEN
        RAISE WARNING 'user_roles 存在 % 组活跃重复的 (user_id, role_id) ⇒ 本次**不建**部分唯一索引；'
                      ' 请先清理重复行再重跑本迁移（issue #7256）', dup_pairs;
    ELSE
        CREATE UNIQUE INDEX IF NOT EXISTS uk_user_roles_active
            ON user_roles (user_id, role_id) WHERE deleted = 0;
        RAISE NOTICE 'user_roles 活跃行唯一索引已就绪（issue #7256）';
    END IF;
END $$;
