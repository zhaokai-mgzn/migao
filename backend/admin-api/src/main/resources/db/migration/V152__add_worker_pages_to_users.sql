-- 工人档案级**工人端菜单权限**（issue #6788）—— `users.worker_pages`
--
-- ## 一句话
-- 在既有**企业级**页面开关（`worker_page_configs`，V141 / 母单 #5161）之下再加一层
-- **逐人收窄**：这位工人只看自己岗位相关的那几页（用户 2026-10-13 逐字
-- 「工人档案上也应该设置 h5 工人端的菜单权限，这样让不同岗位的工人只关注他自己有权限的功能了」）。
--
-- ## 三态（NULL 是**语义**，不是"没填"）
--   · NULL      = **未收窄** ⇒ **跟随企业设置**（= 该企业开的全部页）。**存量行与新建工人的默认值**
--                 （用户 2026-10-13 选定「默认『跟随企业设置』（=全开，零回归）」）⇒ 本迁移**不回填**任何行。
--   · `[]`      = 显式「一页都不给」（合法配置，不是错误）。
--   · `[...]`   = 收窄到这几页（闭词表见 `com.migao.admin.worker.WorkerPages.ALL`）。
--
-- ## 实际下发 = 企业页 ∩ 个人收窄（`WorkerPages.effectiveFor`）
-- 企业关掉的页，逐人勾了也**不**出现 ⇒ 企业级仍是天花板；两层各自可单独回退。
--
-- ## 🔴 红线（与 V141 逐字一致，别读错）
-- 这里存的是**页面可见性**，**不是**权限码 —— 所以它**不**写进 `users.permissions`
-- （RBAC 权限快照，见 `RBAC.md`），而是**另开一列**，物理上分开。
-- 工人 session 的 `permissions` **恒为 []**，工人可达面恒为 `/api/worker/**`，
-- `/api/admin/**` 对 `worker` 一律 403（`SecurityConfig.ADMIN_API_REJECTED_ROLES`）。
-- ⇒ **不得**让本列参与任何授权判定：藏起菜单 **≠** 挡住接口。
--
-- ## 为什么是 users 上的一列（而不是新表）
-- 工人档案就是 `users` 里 `role=worker` 的行（V98）、逐人配置是"整份替换"的一个小数组（4 个固定页），
-- 且读侧与档案同一次查询就能拿到（`WorkerProfileController` 不必多一次 join）——
-- 同族先例：`worker_page_configs.pages` 用 JSONB 而非子表。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `ADD COLUMN IF NOT EXISTS` / `COMMENT ON` ⇒ 第二遍净效果相同。
ALTER TABLE users ADD COLUMN IF NOT EXISTS worker_pages JSONB;

COMMENT ON COLUMN users.worker_pages IS
    '工人档案级工人端页面收窄（issue #6788；用户 2026-10-13 裁定）。三态：NULL = 未收窄 = 跟随企业设置'
    '（存量/新建默认，本迁移不回填）；[] = 显式一页都不给；[...] = 收窄到这几页（闭词表 = WorkerPages.ALL）。'
    '实际下发 = 企业页（worker_page_configs）∩ 本列 ⇒ 企业级仍是天花板。'
    '🔴 只承载页面可见性，不是权限码：不得参与授权判定，也不得写进 users.permissions'
    '（工人 permissions 恒为 []，可达面恒为 /api/worker/**）。';
