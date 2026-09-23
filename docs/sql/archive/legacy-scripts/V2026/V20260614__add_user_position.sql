-- V20260614: 员工表增加岗位字段（纯展示）
-- #328 Role → 岗位：position 不绑定权限，仅作为展示标签
ALTER TABLE users ADD COLUMN IF NOT EXISTS position VARCHAR(64);
