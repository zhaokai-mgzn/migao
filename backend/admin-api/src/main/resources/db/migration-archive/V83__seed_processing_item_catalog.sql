-- 加工项目录按 ERP 附件重建（用户裁定 2026-09-19，issue #4565 的跟随单）
--
-- ## 用户裁定（原文）
-- 「**加工项以及加工项费用的数据没有根据这个附件重建，现在立刻重建**」
-- （附件 = 壁达软件「窗帘货号资料」页的**加工费 91 项列表**截图；逐条实证见
--   `docs/design/processing-fee-and-option-pricing.md` §1）
-- 随后二选一裁定：**先只重建「加工项目录」（特征/单项），组合价目等 ERP 导出后再做**。
--
-- ## 本迁移**只做目录**（明确不做的事，防误读）
--   ✅ `processing_categories`（「加工费」一类）+ `processing_items`（16 项）**按租户**种进库
--   ❌ **不种任何组合价目**（`processing_fee_combinations` 仍是 V77 的 92 行合成集、
--      全部 `status='disabled'`）—— 用户裁定「组合价目等导出后再做」
--   ❌ **不给 `processing_items.unit_price` 落任何价**：本目录的单价一律 **0**
--      （R10：下单页不展示加工项单价；**价只在「加工费组合」上存在**，逐项显示单价必然误导）
--
-- ## 目录内容 = ERP 附件里的**特征词表**（16 项，逐字）
--   工艺项（5，带 `craft_hint` 声明 ⇒ 路线键的工艺维受控来源，V78）：
--     `打孔`→打孔 · `韩折`→**韩褶** · `韩定+S钩`→**韩褶** · `穿杆`→穿杆 · `平幔`→平幔
--     ⚠️ **名字保持 ERP 逐字写法**（`韩折`），工艺值用 MIGAO 枚举写法（`韩褶`）——
--        两者**故意不同**：名字是**计价组合键**（必须与 ERP 91 项逐字一致，错一个字取不到价），
--        工艺是**路线键**（必须与 `production_route_templates` 的 craft 逐字一致）。
--   手选特征/单项（8）：`定型` `花边` `扣环` `接高` `拼接` `双眼皮` `缎带` `换货`
--   自动推导特征（3）：`超高` `超宽` `倒幅` —— **必须存在于目录**（商家配「加工费组合」时要能选到，
--     组合名就是 `韩折+超高+定型` 这种形态），但**下单页的手选控件必须把它们滤掉**
--     （判据 8：自动识别特征出现手选项 ⇒ 红；推导逻辑在 `frontend/admin-web/src/lib/craft-auto-features.ts`）。
--
-- ## 为什么**没有** `四爪钩`（如实登记的取舍）
--   真值源 `docs/curtain-production-rules.md` §8 冻结：「**四爪钩 / 四叉钩**是**加工项（配件）**，
--   不是打褶方式」，其归属由 issue **#4365 阶段 2**（变体规则机制推广到任意触发键 + `穿钩-*` 工序）
--   解决。本迁移**不发明**它的目录行与路线行为（发明 = 把错误结构化）。
--   代价（如实登记）：下单页的「工艺」选择器随本单退场 ⇒ 新单**暂时无法把「四爪钩」标记出来**；
--   存量单不受影响（`order_items.craft='四爪钩'` 照旧派生，其 3 条 `craft` 规则**保持 active**，
--   不得停用 —— 停用会让存量单重放时丢掉 上车布/定型/复烫 的处理）。
--
-- ## 幂等 + 不覆盖商家数据（MigrationRunner 要求所有 SQL 可重复执行）
--   **双保险**（两段 INSERT 各自都有；单靠任一都不够）：
--   ① `NOT EXISTS` 按**业务键** `(tenant_id, name)` 去重（`processing_items` **没有**该唯一索引）
--      ⇒ 已存在同名项（含商家自建/改过的行）**整行跳过**，不 UPDATE、不覆盖；
--   ② `ON CONFLICT (id) DO NOTHING`（V79 同款）—— 本迁移的 id 是**按槽位**派生的
--      （`pi-v83-<tenantId>-<seq>`）⇒ 商家**改名**或**软删**某项后重跑时，`NOT EXISTS` 会判定
--      「该插」，而槽位 id 仍被那行占着 ⇒ **PK 冲突 ⇒ 整份迁移回滚**（真库实测，见下）。
--      ② 把这种情形收敛成**无操作**（语义：**种子只种一次，不复活商家改名/软删过的行**）。
--
-- ## 🔴 真库实测发现的两处缺陷（本文件已修，如实登记 —— 静态守卫全绿而真库整份回滚）
--   ① **`JOIN (VALUES …) AS v(…)` 缺 `ON` 子句** ⇒ PostgreSQL 语法错误 ⇒ 整份迁移回滚 +
--      `schema_migrations` 不写 ⇒ **每次启动重跑报 ERROR、目录永不落库**（#4514 / V74 同族）。
--      仓库既有合法范式 = V79 的 `ON TRUE`（本文件已补）。
--   ② 上面 ② 那条 PK 冲突（改名 / 软删后重跑）。
--   ⚠️ **为什么 CI 没拦住**：`tests/unit_ci_workflows/` 的迁移守卫**只做文本解析、从不执行 SQL**
--      （`test_processing_catalog_seed.py` / references / idempotency / version 四守卫 30 passed，
--      而本文件在真库上直接语法错）。本次新增一条**可红**的针对性判据（`ON TRUE` 与
--      `ON CONFLICT (id) DO NOTHING` 的存在性），但它仍是文本层 —— **「静态守卫不执行 SQL」
--      这一族缺陷未在本单根治**，按 #4514 登记。
--
-- ## 迁移不可变（issue #4235）
--   本文件发布后**不得再改**（改已应用迁移会被按**文件名**整份 skip ⇒ CI 全绿、功能静默缺失）。
--   新增迁移须同 PR 跑 `python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger` 登记指纹。
--
-- ## 与测试资产 / 真值源的收敛（防第二份口径漂移）
--   本文件的 `(name, craft_hint)` 集合与 `tests/e2e/fixtures/processing-list.json`（L2 特征词典，
--   生成器 `tests/unit_ci_workflows/synthetic_processing_fee_data.py`）**逐条同源**；
--   守卫 = `tests/unit_ci_workflows/test_processing_catalog_seed.py`（按内容发现本迁移并比对集合）。
--
-- ## 与 `docs/sql/schema.sql` 的收敛
--   该文件是**全新库的一次性 bootstrap**（该路径**不跑迁移链**）⇒ 同款终态必须同步写进该文件，
--   否则 bootstrap 建库后下单页拿不到加工项目录（形态见 #3270）。
--
-- ## 回滚 SQL（保留于注释；按需手工执行）
-- ```sql
-- DELETE FROM processing_items   WHERE id LIKE 'pi-v83-%';
-- DELETE FROM processing_categories WHERE id LIKE 'pc-v83-%';
-- ```

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 分类「加工费」（按租户；ERP 里这一组的「货号规格」列就是「加工费」）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 统一用**按租户**的 id（`pc-v83-<tenantId>-fee`）：本分类是**新建**的，1 号租户没有历史行要保号，
-- 故不需要 V79 那种「1 号租户字面量 + 其余循环」两段式（那是为保留既有固定 id 才需要的）。
INSERT INTO processing_categories (id, tenant_id, name, sort_order, status)
SELECT 'pc-v83-' || t.id || '-fee', t.id, '加工费', 10, 'active'
  FROM tenants t
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM processing_categories e
        WHERE e.tenant_id = t.id AND e.name = '加工费' AND e.deleted = 0)
ON CONFLICT (id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 加工项目录 16 项（按租户）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- `unit_price` 一律 **0**：价只在「加工费组合」上（R10），目录里的 0 = **无价**（不是"0 元"）。
-- `pricing_method='per_meter'` + `unit='米'`：ERP 里这 91 项的单位逐行都是「米」。
-- `craft_hint` 逐项显式（NULL = 该特征不声明工艺 ⇒ 路线键的工艺维按缺维处理，不猜）。
INSERT INTO processing_items
    (id, tenant_id, name, category_id, pricing_method, unit_price, unit,
     description, craft_hint, status)
SELECT 'pi-v83-' || t.id || '-' || v.seq,
       t.id,
       v.name,
       'pc-v83-' || t.id || '-fee',
       'per_meter',
       0,
       '米',
       v.description,
       v.craft_hint,
       'active'
  FROM tenants t
  JOIN (VALUES
      -- 工艺项（5）：名字 = ERP 逐字；craft_hint = MIGAO 工艺枚举逐字
      ('01'::text, '打孔'::text,      '打孔'::varchar(16), 'ERP 加工费项（工艺声明：打孔）'::text),
      ('02'::text, '韩折'::text,      '韩褶'::varchar(16), 'ERP 加工费项（工艺声明：韩褶；名字按 ERP 写「韩折」）'::text),
      ('03'::text, '韩定+S钩'::text,  '韩褶'::varchar(16), 'ERP 加工费项（工艺声明：韩褶）'::text),
      ('04'::text, '穿杆'::text,      '穿杆'::varchar(16), 'ERP 加工费项（工艺声明：穿杆）'::text),
      ('05'::text, '平幔'::text,      '平幔'::varchar(16), 'ERP 加工费项（工艺声明：平幔）'::text),
      -- 手选特征 / 单项（8）
      ('06'::text, '定型'::text,      NULL::varchar(16),   'ERP 加工费特征（手选；不再由「工艺规格」录入）'::text),
      ('07'::text, '花边'::text,      NULL::varchar(16),   'ERP 加工费特征（手选）'::text),
      ('08'::text, '扣环'::text,      NULL::varchar(16),   'ERP 加工费特征（手选）'::text),
      ('09'::text, '接高'::text,      NULL::varchar(16),   'ERP 加工费特征（手选）'::text),
      ('10'::text, '拼接'::text,      NULL::varchar(16),   'ERP 加工费特征（手选）'::text),
      ('11'::text, '双眼皮'::text,    NULL::varchar(16),   'ERP 加工费特征（手选）'::text),
      ('12'::text, '缎带'::text,      NULL::varchar(16),   'ERP 加工费单项（独立一行，不成组合）'::text),
      ('13'::text, '换货'::text,      NULL::varchar(16),   'ERP 加工费单项'::text),
      -- 自动推导特征（3）：必须在目录里（配组合用），但**下单页手选控件必须滤掉**
      ('14'::text, '超高'::text,      NULL::varchar(16),   '自动推导特征（成品高+卷边 > 门幅）—— 不得手选'::text),
      ('15'::text, '超宽'::text,      NULL::varchar(16),   '自动推导特征（成品宽+卷边 > 门幅）—— 不得手选'::text),
      ('16'::text, '倒幅'::text,      NULL::varchar(16),   '自动推导特征（加工类型=定宽买高）—— 不得手选'::text)
  ) AS v(seq, name, craft_hint, description)
   ON TRUE
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM processing_items e
        WHERE e.tenant_id = t.id AND e.name = v.name AND e.deleted = 0)
ON CONFLICT (id) DO NOTHING;
