-- 为缺少 updated_at 字段的表补充该字段（大数据分析需要统一的更新时间戳）

-- 1. user_roles
ALTER TABLE user_roles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
UPDATE user_roles SET updated_at = created_at WHERE updated_at IS NULL;
COMMENT ON COLUMN user_roles.updated_at IS '更新时间（大数据分析补充字段）';

-- 2. user_identities
ALTER TABLE user_identities ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
UPDATE user_identities SET updated_at = created_at WHERE updated_at IS NULL;
COMMENT ON COLUMN user_identities.updated_at IS '更新时间（大数据分析补充字段）';

-- 3. rag_chunks
ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
UPDATE rag_chunks SET updated_at = created_at WHERE updated_at IS NULL;
COMMENT ON COLUMN rag_chunks.updated_at IS '更新时间（大数据分析补充字段）';

-- 4. session_messages
ALTER TABLE session_messages ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
UPDATE session_messages SET updated_at = created_at WHERE updated_at IS NULL;
COMMENT ON COLUMN session_messages.updated_at IS '更新时间（大数据分析补充字段）';

-- 5. ticket_timeline
ALTER TABLE ticket_timeline ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
UPDATE ticket_timeline SET updated_at = created_at WHERE updated_at IS NULL;
COMMENT ON COLUMN ticket_timeline.updated_at IS '更新时间（大数据分析补充字段）';

-- 6. ticket_notes
ALTER TABLE ticket_notes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
UPDATE ticket_notes SET updated_at = created_at WHERE updated_at IS NULL;
COMMENT ON COLUMN ticket_notes.updated_at IS '更新时间（大数据分析补充字段）';

-- 7. audit_logs
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
UPDATE audit_logs SET updated_at = created_at WHERE updated_at IS NULL;
COMMENT ON COLUMN audit_logs.updated_at IS '更新时间（大数据分析补充字段）';

-- 8. order_items
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
UPDATE order_items SET updated_at = created_at WHERE updated_at IS NULL;
COMMENT ON COLUMN order_items.updated_at IS '更新时间（大数据分析补充字段）';

-- 9. customer_segment_members（使用 added_at 回填）
ALTER TABLE customer_segment_members ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
UPDATE customer_segment_members SET updated_at = added_at WHERE updated_at IS NULL;
COMMENT ON COLUMN customer_segment_members.updated_at IS '更新时间（大数据分析补充字段）';
