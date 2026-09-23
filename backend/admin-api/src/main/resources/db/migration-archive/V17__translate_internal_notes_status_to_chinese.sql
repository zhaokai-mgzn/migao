-- V17: 售后工单 internal_notes 状态词英文 → 中文
--
-- 背景：updateTicketStatus 写入 internal_notes 时使用英文枚举
-- （如 "[08-29 11:57] pending → processing: ok"），面向企业客户不可读。
-- 本迁移将存量数据中的状态词替换为中文业务术语。
--
-- 幂等：仅替换 "状态位"（`] pending →` / `→ pending:` 两种固定上下文），
-- 不替换 remark 正文中的单词；重复执行无匹配项，无副作用。

UPDATE after_sales_tickets
SET internal_notes = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(
    internal_notes,
    '] pending →', '] 待处理 →'),
    '→ pending:', '→ 待处理:'),
    '] processing →', '] 处理中 →'),
    '→ processing:', '→ 处理中:'),
    '] resolved →', '] 已解决 →'),
    '→ resolved:', '→ 已解决:'),
    '] rejected →', '] 已拒绝 →'),
    '→ rejected:', '→ 已拒绝:'),
    '] closed →', '] 已关闭 →'),
    '→ closed:', '→ 已关闭:')
WHERE internal_notes IS NOT NULL
  AND (internal_notes LIKE '%pending%' OR internal_notes LIKE '%processing%'
       OR internal_notes LIKE '%resolved%' OR internal_notes LIKE '%rejected%'
       OR internal_notes LIKE '%closed%');
