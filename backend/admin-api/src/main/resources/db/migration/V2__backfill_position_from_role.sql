-- V2: 将已有用户的 position 从 role 字段回填
-- 如果 position 为空或 NULL，则用 role 值填充
UPDATE users SET position = role WHERE position IS NULL OR position = '';
