-- 工人端**页面开关**（V141，母单 #5161 —— 工人端页面/菜单权限的部分交付）
--
-- ## 一句话
-- 商家可按**租户**勾选工人端 H5 / 车间一体机上**出现哪些页面**；载体 = 单行/租户的 JSONB 列。
--
-- ## 红线（本表的语义边界，别读错）
-- 这里存的是**页面可见性**，**不是**权限码。工人 session 的 `permissions` **恒为 []**
-- （`WorkerSessionService` 只签发 role=worker），工人可达面恒为 `/api/worker/**`，
-- `/api/admin/**` 对 worker 一律 403（`SecurityConfig.ADMIN_API_REJECTED_ROLES`）。
-- ⇒ **不得**把工人页面码写进 `users.permissions`，也不得让本表参与任何授权判定。
--
-- ## 为什么是 JSONB 而不是子表 / 为什么不逐人
-- 页面集合是**整份替换**的配置（PUT 全量替换），项数是 4 个固定页面 ⇒ 子表只带来 join 与「半份配置」。
-- 逐人覆盖是下一期（本表**只做租户级**；届时另加一列/一表，而不是把这个人维塞进 pages 里）。
--
-- ## 缺行 = 用默认值（**不做开租播种**）
-- 默认集合（全部页面）只在 Java **一处**（`com.migao.admin.worker.WorkerPages`）；
-- 库里再种一份 = 第二份会漂的默认值（同族先例：`cutting_height_configs` / `craft_calc_configs`）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `CREATE TABLE IF NOT EXISTS` / `CREATE UNIQUE INDEX IF NOT EXISTS` ⇒ 第二遍净效果相同。
CREATE TABLE IF NOT EXISTS worker_page_configs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    pages JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_worker_page_configs_tenant
    ON worker_page_configs (tenant_id)
    WHERE deleted = 0;
