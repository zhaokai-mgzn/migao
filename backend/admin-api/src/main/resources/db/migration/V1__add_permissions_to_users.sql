-- V1: 给 users 表添加 permissions 和 position 字段
ALTER TABLE users ADD COLUMN IF NOT EXISTS permissions TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS position VARCHAR(64);
