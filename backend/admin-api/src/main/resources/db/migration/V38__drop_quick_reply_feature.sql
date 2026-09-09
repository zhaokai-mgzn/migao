-- 快捷回复功能完全下线（issue #3081：已被知识卡片/知识库替代，前端/后端/Agent 全栈移除）
-- 清理顺序（外键约束）：
--   ① 删除角色-权限关联（role_permissions.permission_id → permissions.id）
--   ② 删除权限记录（permissions.code = 'agent:quickreply'）
--   ③ 删除业务表 quick_reply_templates（历史数据随功能下线删除，无迁移需求）
DELETE FROM role_permissions
WHERE permission_id IN (SELECT id FROM permissions WHERE code = 'agent:quickreply');

DELETE FROM permissions WHERE code = 'agent:quickreply';

DROP TABLE IF EXISTS quick_reply_templates;
