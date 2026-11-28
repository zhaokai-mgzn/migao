-- V219__backfill_tenant_bot_name_to_smart_service.sql
--
-- 背景（issue #9308，用户 2026-11-28 逐字「C 端也不叫米宝了…直接叫智能客服」）：
-- 「米宝」是**退役品牌名**，不应再出现在任何顾客可见面。C 端顾客拿到的客服名来自
-- `tenant_ai_configs.bot_name`，而这一列里已经物化的 '米宝' 是**行里的值**、不是默认值。
--
-- ## 为什么只改代码默认值不够（现取依据）
--   · `backend/ai-agent-service/app/agents/agents/xiaobu.py` 的 `DEFAULT_BOT_NAME = "智能客服"`
--     已经改好（issue #9304 / main f9103e365），但 `get_xiaobu_greeting()` 的取值是
--     `bot_name = data.get("botName") or DEFAULT_BOT_NAME` —— **租户配置优先于新默认值**；
--   · 而表里的 '米宝' 是 **V213**（当年「元元 → 米宝」改名）**物化**进去的：
--     它的 `UPDATE … WHERE bot_name = '元元'` 把存量行写成了 '米宝' ⇒ 不改表，存量商户的
--     顾客今天就仍会收到「您好！我是米宝…」。
--
-- ## 口径：只改**逐字等于** '米宝' 的行
--   · 用逐字相等（`bot_name = '米宝'`）而**不是** `LIKE '%米宝%'`：'米宝' 是**旧默认值**，
--     而商户**自定义**过的名字里可能含这两个字（如「米宝小助手」）—— 模糊匹配会把商户自己的
--     名字一起改掉，那是商户数据、不是品牌位；
--   · 其它任何值（自定义名 / 空 / NULL）一个字都不动；
--   · 判据（会红）：`tests/unit_ci_workflows/test_v219_bot_name_backfill.py` 造了
--     '米宝' / '小美' / '米宝小助手' / NULL 四行，只许第一行变。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · 带**旧值谓词** ⇒ 第二遍匹配 0 行，结果与第一遍逐值相同；
--   · 只 `UPDATE`，不 `INSERT` / 不 `DELETE` ⇒ 无新增行、无删除行；
--   · 不动列定义 / 不动列默认值（`ALTER TABLE` 一律没有，见下面「边界」）。
--
-- ## 可观测性（怎么确认它真的做了事）
--   · psql 执行本文件时逐语句打印命令标签：**首次 `UPDATE k`**（k = 存量命中行数）、
--     **再次 `UPDATE 0`**（= 已回填过、幂等闸生效）—— 本仓判据直接读这两行真库读数；
--   · ⚠️ `MigrationRunner` 走 `jdbc.execute(整份文件)`，只记「✅ 迁移完成」、**不回显行数**
--     ⇒ 线上要看命中行数就用 psql 复跑一次（幂等，第二次必为 `UPDATE 0`）。
--
-- ## 停止条件（fail-closed）
--   `tenant_ai_configs` 里不再有 `bot_name = '米宝'` 的行。
--
-- ## 回滚 SQL（登记，不落码 —— 本仓迁移无 down 机制）
--   UPDATE tenant_ai_configs SET bot_name = '米宝' WHERE bot_name = '智能客服';
--   ⚠️ 回滚**必然覆盖**「回填之后、又被商户自己改成『智能客服』」的行（两者在库里不可区分）
--     ⇒ 只在确认无商户自定义改动时执行。
--
-- ## 边界（照实登记，本迁移不做）
--   · **列默认值仍是 '米宝'**（V213 的 `ALTER COLUMN bot_name SET DEFAULT '米宝'`）：本迁移
--     按派单口径**不碰列定义 / 默认值**（那是另一件事）⇒ 新建租户配置若**没显式给** botName，
--     落库仍会是 '米宝'。缺口照实登记在此，重启条件 = 有单处理「列默认值」时同批改；
--   · `greeting_template` / `channel_configs` 里商户**自己写的**「米宝」属商户数据，不回填
--     （与 V213 的登记同口径）；
--   · 前端兜底名（未配置时展示什么）不在 DB 面，归前端单 #9306。

BEGIN;

-- 租户客服名：旧默认值 '米宝' → '智能客服'（逐字相等；商户自定义名不动）
UPDATE tenant_ai_configs
   SET bot_name   = '智能客服',
       updated_at = NOW()
 WHERE bot_name = '米宝';

COMMIT;
