-- V211 / issue #8175（P1）：口径卡冲突标记
--
-- ## 为什么不是「upsert 后写覆盖先写」
-- 同一条口径（同 `scope` + 同 `trigger`）出现**两个不同说法**时，正确做法不是让先来的被后来的
-- 冲掉 —— 冲掉意味着「谁后跑一次蒸馏，谁就改写全企业的行为」，且被冲掉的那条**无痕消失**。
-- 本列的做法是：两条**并存**（各占一行、都是 draft，等人审），并给两条打上**同一个**标记，
-- 审核页据此说「这两条是同一条口径的两种说法，请裁定」。标记 = `sha1(scope|scope_role|trigger)[:16]`，
-- 由落库面（backend/ai-agent-service/app/playbook/ingest.py）计算，**不写默认值**：
-- NULL = 没有冲突；非 NULL = 与同组其它行冲突。
--
-- ## 为什么单独一列而不是「读时现算」
-- 读时现算要求每个消费面都拿得到同租户的全量行（列表/审核/prompt 各算一遍），
-- 而「标记冲突」这件事的消费面是**审核队列**（一次列表查询）—— 现算就是 N+1 或无索引全扫。
-- 一列 + 一个条件索引，代价固定；且它是**可观测的**：审核页看得见，不是一句注释。
--
-- ## 状态机不变
-- 本迁移**不改**任何 CHECK / 既有列：`draft` 仍不进 prompt、退役仍立即生效。

ALTER TABLE playbooks ADD COLUMN IF NOT EXISTS conflict_key VARCHAR(64);

-- 审核页按冲突分组（只索引非 NULL：绝大多数行没有冲突）
CREATE INDEX IF NOT EXISTS idx_playbooks_conflict
    ON playbooks (tenant_id, conflict_key)
    WHERE conflict_key IS NOT NULL;

COMMENT ON COLUMN playbooks.conflict_key IS
    '同一条口径（scope + trigger）的冲突标记（issue #8175 P1）。'
    '非 NULL = 本租户内还有别的行与之同 key 但正解不同 ⇒ 两条并存、待人工裁定；'
    'NULL = 无冲突。由 app/playbook/ingest.py 计算，任何路径都**不改** correct_text。';
