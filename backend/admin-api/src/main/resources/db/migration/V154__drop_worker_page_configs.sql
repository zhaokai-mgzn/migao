-- 移除工人端**页面开关**（企业级）配置层（issue #6828；用户 2026-10-13 逐字
-- 「是不是可以移除工人端页面的配置，我们已经通过权限控制 工人的菜单可见问题了」⇒ 裁定「一步到位移除」）
--
-- ## 一句话
-- 工人端「出现哪些页面」从此**只有一层真值** = 工人档案上的 `users.worker_pages`（V152，issue #6788）；
-- 企业级那一层（本表 + `GET/PUT /api/admin/worker-page-config` + 设置页「工人端页面」域）整层退场。
--
-- ## 为什么删（冗余，不是缺陷）
-- 同一件事曾有两个配置面：企业级「全开/关某页」与档案级「逐人收窄」，实际下发 = 两者求交。
-- 逐人能表达企业级能表达的全部意图（且更精确）⇒ 企业级只剩「新工人默认值」这一个副作用，
-- 而默认值本来就等于**全开**（`WorkerPages.defaultPages()`）⇒ 这一层没有独占能力。
--
-- ## 🔴 不可逆（照实登记）
-- 已配过「关掉某页」的企业，其**该页会回来**（缺行 = 全开）。用户已裁定接受该损失。
-- 回滚段重建的只是**空表**：旧配置值不在这里留存（退场前未做数据搬运）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `DROP TABLE IF EXISTS` ⇒ 第二遍净效果相同。
DROP TABLE IF EXISTS worker_page_configs;

-- 顺带把 `users.worker_pages` 的**列注释**同步成单层口径（issue #6828 复核发现的分叉）：
-- V152 里那条 `COMMENT ON COLUMN` 写的是「实际下发 = 企业页（worker_page_configs）∩ 本列 ⇒ 企业级仍是天花板」，
-- 而企业级层已由本迁移移除 ⇒ 存量库（走过迁移链）的列注释必须改写，否则与 `db/init/schema.sql`
-- （新建库路径）的 DB 元数据分叉：两条建库路径给出**互相矛盾**的列说明，而元守卫只查表名、覆盖不到。
-- ⚠️ 已发布迁移不可改（V152 保持原样）；这是**唯一**一处补注释的落点。
COMMENT ON COLUMN users.worker_pages IS
    '工人端页面收窄（issue #6788）：NULL = 未收窄 = 全部页面（默认，零回归）；数组 = 收窄到这几页'
    '（闭词表 = WorkerPages.ALL）。实际下发 = 本列（issue #6828 起企业级页面开关已整层移除 ⇒ 页面集只有这一层）；'
    '🔴 不是权限码：工人 session 的 permissions 恒为 []。';

-- ── 回滚段（可执行；逐句幂等）───────────────────────────────────────────────
-- 形状逐字取自 V141__create_worker_page_configs.sql（含部分唯一索引与表注释），
-- 便于回滚后与 V141 的终态逐项一致。
--
-- CREATE TABLE IF NOT EXISTS worker_page_configs (
--     id VARCHAR(64) PRIMARY KEY,
--     tenant_id BIGINT NOT NULL REFERENCES tenants(id),
--     pages JSONB NOT NULL DEFAULT '[]'::jsonb,
--     status VARCHAR(16) NOT NULL DEFAULT 'active',
--     created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
--     updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
--     deleted INTEGER NOT NULL DEFAULT 0
-- );
-- CREATE UNIQUE INDEX IF NOT EXISTS uk_worker_page_configs_tenant
--     ON worker_page_configs (tenant_id)
--     WHERE deleted = 0;
-- COMMENT ON TABLE worker_page_configs IS
--     '工人端**页面开关**（V141，母单 #5161）。单行/租户，缺行 = 默认全开（WorkerPages，Java 一处）'
--     '—— 不做开租播种。🔴 只承载页面可见性，**不是**权限码：'
--     '工人 session 的 permissions 恒为 []，工人可达面恒为 /api/worker/**。';
