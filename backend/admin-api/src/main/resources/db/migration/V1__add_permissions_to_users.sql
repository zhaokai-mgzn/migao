-- V1: 给 users 表添加 permissions 字段（存储菜单权限码 JSON 数组）
ALTER TABLE users ADD COLUMN IF NOT EXISTS permissions TEXT;
