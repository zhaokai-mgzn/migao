-- 决策采纳记录（issue #8260）—— `briefing_actions`
--
-- ## 一句话
-- 复盘（#8253）只留下了「AI 说过什么」，说不出「人做了什么」。本表补后半句：
-- 一条建议被点开过没有、被谁点的、什么时候点的。
--
-- ## 为什么 item_key 是「标题的 sha256 前 16 位」而不是标题原文 / 下标
--   · 存原文 ⇒ 等于把 `daily_briefings.content` 抄一份：内容冗余 + PII 面扩大
--     （红线同 `daily_briefings`：简报正文不进日志、不进事件表的可读列）。
--   · 存下标 ⇒ 简报每次重排都会变，同一条会被记成两条。
--   · 换个说法就是**另一条**建议 —— 这不是「丢匹配」，是语义上本来就该分开。
--
-- ## 为什么 UNIQUE 在 (tenant_id, biz_date, item_kind, item_key) 上
-- 同一条目反复点「问黄金策」只应留一行（幂等）；否则「31 个问题你处理了 47 次」这种读数会自己长出来。
-- 服务层走「先查后写」（避免 PG 25P02 aborted 事务），本约束是**兜底**不是常规路径。
--
-- ## 三态与口径
--   · `action` 目前只有 `opened_agent`（点开问了）。**记录 ≠ 采纳**：不表示人照着做了。
--     `done` / `ignored` 不在本单（需要 UI 上的「已处理 / 忽略」按钮，属产品决策）。
--   · `actor_id` 只存用户 id，不存姓名 / 手机号。
--
-- ## bootstrap 终态同步（同 V99/V108/V127/V133/V170/V193/V195 纪律）
-- 新建库路径**不跑历史迁移链** ⇒ `backend/admin-api/src/main/resources/db/init/schema.sql`
-- 已同步本文件终态（表 + 索引 + 注释）。只改一处 ⇒ 新建库缺表。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V196__rollback_briefing_actions.sql（本单只登记，不落码）
-- -- DROP TABLE IF EXISTS briefing_actions;
-- ```

CREATE TABLE IF NOT EXISTS briefing_actions (
    id         VARCHAR(32)  PRIMARY KEY,
    tenant_id  BIGINT       NOT NULL,
    biz_date   DATE         NOT NULL,
    item_kind  VARCHAR(16)  NOT NULL,
    item_key   VARCHAR(16)  NOT NULL,
    action     VARCHAR(32)  NOT NULL,
    actor_id   VARCHAR(64),
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uk_briefing_actions_item UNIQUE (tenant_id, biz_date, item_kind, item_key)
);

COMMENT ON TABLE  briefing_actions            IS '决策采纳记录（issue #8260）：AI 建议了什么 → 人做了什么';
COMMENT ON COLUMN briefing_actions.biz_date   IS '简报归属业务日期（Asia/Shanghai），与 daily_briefings.biz_date 同口径';
COMMENT ON COLUMN briefing_actions.item_kind  IS 'todo / risk / suggestion（与简报 content 三个数组同名）';
COMMENT ON COLUMN briefing_actions.item_key   IS '条目标题 sha256 前 16 位：稳定、不含原文、不随重排漂移';
COMMENT ON COLUMN briefing_actions.action     IS '动作白名单；目前只有 opened_agent（点开问了）。记录 ≠ 采纳';
COMMENT ON COLUMN briefing_actions.actor_id   IS '操作人用户 id（不含姓名 / 手机号）';

-- 复盘查询按「租户 + 日期区间倒序」扫；UNIQUE 已覆盖 tenant_id 前缀，这里补日期维度
CREATE INDEX IF NOT EXISTS idx_briefing_actions_tenant_date
    ON briefing_actions (tenant_id, biz_date DESC);
