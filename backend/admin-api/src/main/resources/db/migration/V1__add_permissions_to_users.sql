-- V1: 给 users 表添加 position 和 permissions 字段
ALTER TABLE users ADD COLUMN IF NOT EXISTS position VARCHAR(50);
ALTER TABLE users ADD COLUMN IF NOT EXISTS permissions TEXT;
