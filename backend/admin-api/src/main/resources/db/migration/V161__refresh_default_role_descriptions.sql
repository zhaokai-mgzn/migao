-- 内置岗位**描述**的刷新（issue #7111）
--
-- ## 一句话
--   `roles.description` 是**商家可见面**（岗位权限页逐卡展示、员工弹窗里选岗位时会读到）。
--   它此前是半句话（「负责销售业务」）或**内部标识**（issue 号 / 权限码 / POC 口径），
--   既说不清「这个岗位承担什么职责」，也说不清「默认能用哪些模块」。
--   本迁移把它们统一改成「**职责 + 默认可用模块**」两段式 —— 文案的**唯一声明面**是
--   `rbac/manifest.json` 的 `roles.descriptions`，与 `RegistrationService` 的注册种子
--   **逐值对账**（`rbac/readings.json` 的 `roles.descriptions` 由同一份 `Role.builder()` 块现取）。
--
-- ## 幂等 + **不覆盖自定义文案**（本迁移的安全边界）
--   · 每条 UPDATE 的谓词是 `description IN (<旧默认文案>)` —— 只有**仍是**我们写的那句话的行会被改；
--   · 商家在岗位权限页改过的描述**不在**旧文案表里 ⇒ **一律不动**（迁移不是「把文案推平」的工具）；
--   · 改过的行第二次执行时已不匹配谓词 ⇒ **第二遍每条 0 行**，结果与第一遍相同。
--
-- ## 存量租户（为什么需要一条迁移）
--   新租户走 `RegistrationService` 的种子（本 PR 同批改成新文案）；存量租户的 `roles` 行
--   由 V29 / V32 / V137 / V158 建出、且**没有任何 Java 路径**会改写已有描述 ⇒ 不补这条迁移，
--   「新租户是新文案、老租户还是旧文案」的两份真相会一直并存。
--
-- ## 停止条件（fail-closed）
--   终态对账（文末 `DO` 块）：任何一行仍同时命中「内置岗位码 + 旧默认文案」⇒
--   `RAISE EXCEPTION` 并回滚本迁移（不硬推半完成态）。
--
-- ## 显式事务（同 V97 / V102 / V107 / V108 / V111 / V124 / V136 / V137 / V158 的实测口径）
--   `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` 默认逐条
--   autocommit ⇒ 不显式 `BEGIN/COMMIT` 时中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
--
-- ## 本文件是**生成物**（不是手写真值）
--   由 `rbac/generate_migration.py` 从 `rbac/manifest.json` 渲染（`python3 rbac/generate_migration.py`）
--   ⇒ 手改本文件、或改了清单没重渲染，都会被新鲜度判据判红（`test_rbac_migration_convergence.py`）。
--
-- ## 回滚（**新迁移，不删本文件**）
--   ```sql
--   -- 只会回到「旧默认文案」；商家自定义文案本迁移从未改过 ⇒ 无需回滚
--   UPDATE roles SET description = '<旧默认文案>' WHERE code = '<岗位码>' AND deleted = 0
--     AND description = '<新文案>';   -- 逐岗位重复（回滚是「文案回退」，不涉及授权 / 数据）
--   ```
--
-- ## 边界（照实登记）
--   ① 不改任何 `role_permissions` 行，**零授权 delta**；② 不回填 `users.permissions` 快照；
--   ③ 空描述（NULL / 空串）**不动** —— 留白多半是有意的（本迁移只认「我们写的那句话」）。

BEGIN;

-- ── admin：只改「仍是旧默认文案」的行（自定义描述一律不动）──
UPDATE roles
   SET description = '职责：企业最高管理岗位，负责员工、岗位与权限配置以及企业基础信息维护，统筹商品、客户、订单、生产、仓储与财务各模块的审核与异常处理。默认可用模块：全部模块 —— 经营看板、每日简报、商品管理、在线接待、知识库、售后工单、客户列表、订单列表、财务对账、生产看板、智能派单、计件工资、入库单、库存明细、发货单、余料台账、省料看板、员工管理、岗位权限、企业基础设置。', updated_at = NOW()
 WHERE code = 'admin'
   AND deleted = 0
   AND description IN ('拥有全部管理权限');

-- ── customer_service：只改「仍是旧默认文案」的行（自定义描述一律不动）──
UPDATE roles
   SET description = '职责：在线接待客户咨询与投诉，跟进订单进度，处理售后工单与退款，维护客户档案与知识库内容，并承担成品帘加工执行（建加工单、报工、打任务卡、发货）。默认可用模块：经营看板、每日简报、在线接待、知识库、售后工单、客户列表、订单列表、发货单、入库单、智能派单。', updated_at = NOW()
 WHERE code = 'customer_service'
   AND deleted = 0
   AND description IN ('负责客户服务与咨询');

-- ── finance：只改「仍是旧默认文案」的行（自定义描述一律不动）──
UPDATE roles
   SET description = '职责：登记与核对收支流水，跟踪订单收款与对账差异，核对入库、发货与加工工价的成本口径，并按需执行加工单与报工操作。默认可用模块：经营看板、每日简报、客户列表、订单列表、财务对账、发货单、入库单、智能派单。', updated_at = NOW()
 WHERE code = 'finance'
   AND deleted = 0
   AND description IN ('负责财务对账');

-- ── inspector：只改「仍是旧默认文案」的行（自定义描述一律不动）──
UPDATE roles
   SET description = '职责：负责成品帘质检判定录入（合格、返工、报废），核对计件工价与工序数据，为返工与报废的结算提供依据。默认可用模块：生产看板、计件工资、企业基础设置。', updated_at = NOW()
 WHERE code = 'inspector'
   AND deleted = 0
   AND description IN ('成品帘质检录入（issue #5652：独立质检员，持 production:inspect / production:view）', '成品帘质检录入（issue #5652：独立质检员，持 production:view / production:inspect）');

-- ── knowledge_editor：只改「仍是旧默认文案」的行（自定义描述一律不动）──
UPDATE roles
   SET description = '职责：维护客服知识库，新增、修订与下线知识卡片，按商品资料校对对外答复口径，保证客服答复准确一致。默认可用模块：经营看板、每日简报、知识库、商品管理、库存明细、省料看板。', updated_at = NOW()
 WHERE code = 'knowledge_editor'
   AND deleted = 0
   AND description IN ('知识库编辑（POC 期历史岗位，issue #5699 的 P6 正式定义）');

-- ── operator：只改「仍是旧默认文案」的行（自定义描述一律不动）──
UPDATE roles
   SET description = '职责：统筹日常经营：建单、改单、退款与售后处理，维护客户档案、商品与分类，管理加工项与入库单，登记财务流水，并兼顾在线接待。默认可用模块：经营看板、每日简报、商品管理、在线接待、知识库、售后工单、客户列表、订单列表、财务对账、生产看板、智能派单、计件工资、入库单、库存明细、发货单、余料台账、省料看板、员工管理、企业基础设置。', updated_at = NOW()
 WHERE code = 'operator'
   AND deleted = 0
   AND description IN ('负责日常运营管理');

-- ── product_manager：只改「仍是旧默认文案」的行（自定义描述一律不动）──
UPDATE roles
   SET description = '职责：维护商品资料、分类与上下架，管理加工项与加工费口径，为智能派单、生产看板与库存、省料分析提供准确的商品与工序数据。默认可用模块：经营看板、每日简报、商品管理、生产看板、智能派单、计件工资、库存明细、余料台账、省料看板、企业基础设置。', updated_at = NOW()
 WHERE code = 'product_manager'
   AND deleted = 0
   AND description IN ('商品与加工项管理（POC 期历史岗位，issue #5699 的 P6 正式定义）');

-- ── sales：只改「仍是旧默认文案」的行（自定义描述一律不动）──
UPDATE roles
   SET description = '职责：接待客户并促成下单，负责新建订单、订单跟进与详情核对，跟踪生产与发货进度，维护客户档案。默认可用模块：经营看板、每日简报、商品管理、客户列表、订单列表、智能派单、入库单、库存明细、发货单、省料看板。', updated_at = NOW()
 WHERE code = 'sales'
   AND deleted = 0
   AND description IN ('负责销售业务');

-- ══════════════════════════════════════════════════════════════════════════════
-- 终态对账（仍有行保留旧默认文案 ⇒ 回滚，不硬推）
-- ══════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    stale INTEGER;
BEGIN
    SELECT COUNT(*) INTO stale
      FROM roles r
     WHERE r.deleted = 0
       AND (r.code, r.description) IN (VALUES
        ('admin', '拥有全部管理权限'),
        ('customer_service', '负责客户服务与咨询'),
        ('finance', '负责财务对账'),
        ('inspector', '成品帘质检录入（issue #5652：独立质检员，持 production:inspect / production:view）'),
        ('inspector', '成品帘质检录入（issue #5652：独立质检员，持 production:view / production:inspect）'),
        ('knowledge_editor', '知识库编辑（POC 期历史岗位，issue #5699 的 P6 正式定义）'),
        ('operator', '负责日常运营管理'),
        ('product_manager', '商品与加工项管理（POC 期历史岗位，issue #5699 的 P6 正式定义）'),
        ('sales', '负责销售业务')
       );
    IF stale > 0 THEN
        RAISE EXCEPTION 'V161 终态对账失败：仍有 % 行保留旧默认描述 —— 回滚本迁移', stale;
    END IF;
    RAISE NOTICE 'V161 终态对账通过：8 个内置岗位的描述已刷新';
END $$;

COMMIT;
