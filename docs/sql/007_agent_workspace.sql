-- ============================================================
-- 007_agent_workspace.sql - 客服工作台功能数据库迁移
-- 说明: 新增人工客服会话、会话消息、快捷回复模板 3 张表
-- 依赖: 需先执行 001_init.sql（tenants, agent_employees, sessions）
-- ============================================================

-- ============================================================
-- 1. agent_sessions: 客服工作台人工客服会话表
-- 用途: 记录C端消费者在小程序AI智能客服转人工后的会话，
--       由企业内部客服人员在客服工作台中处理，包含排队、分配、服务全流程
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_sessions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    customer_id VARCHAR(64),  -- 客户ID
    employee_id VARCHAR(64) REFERENCES agent_employees(id),  -- 分配的客服员工
    ai_session_id VARCHAR(64) REFERENCES sessions(id),  -- 关联C端消费者在小程序AI智能客服中的原始会话
    status VARCHAR(32) DEFAULT 'waiting',  -- waiting / active / ended / transferred
    priority INTEGER DEFAULT 0,  -- 优先级
    reason TEXT,  -- 转人工原因
    queue_position INTEGER,  -- 排队位置
    started_at TIMESTAMP WITH TIME ZONE,  -- 开始服务时间
    ended_at TIMESTAMP WITH TIME ZONE,  -- 结束时间
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_agent_sessions_tenant ON agent_sessions(tenant_id);
CREATE INDEX idx_agent_sessions_employee ON agent_sessions(employee_id);
CREATE INDEX idx_agent_sessions_status ON agent_sessions(status);
CREATE INDEX idx_agent_sessions_customer ON agent_sessions(customer_id);
CREATE INDEX idx_agent_sessions_ai_session ON agent_sessions(ai_session_id);

-- ============================================================
-- 2. agent_messages: 人工会话消息表
-- 用途: 存储人工客服会话中的所有消息，支持客户/客服/系统多角色
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_messages (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    session_id VARCHAR(64) NOT NULL REFERENCES agent_sessions(id),  -- 关联会话
    sender_type VARCHAR(32) NOT NULL,  -- customer / agent / system
    sender_id VARCHAR(64),  -- 发送者ID
    content_type VARCHAR(32) DEFAULT 'text',  -- text / image / file / system
    content TEXT NOT NULL,  -- 消息内容
    is_internal BOOLEAN DEFAULT false,  -- 是否内部备注
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_agent_messages_session ON agent_messages(session_id, created_at);
CREATE INDEX idx_agent_messages_tenant ON agent_messages(tenant_id);

-- ============================================================
-- 3. quick_reply_templates: 快捷回复模板表
-- 用途: 客服常用话术模板，支持分类管理和快捷键触发
-- ============================================================
CREATE TABLE IF NOT EXISTS quick_reply_templates (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    category VARCHAR(64) NOT NULL,  -- 分类
    title VARCHAR(128) NOT NULL,  -- 标题
    content TEXT NOT NULL,  -- 模板内容
    shortcut VARCHAR(32),  -- 快捷键
    usage_count INTEGER DEFAULT 0,  -- 使用次数
    is_public BOOLEAN DEFAULT true,  -- 是否公开（全员可见）
    created_by VARCHAR(64),  -- 创建者
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX idx_quick_reply_templates_tenant_category ON quick_reply_templates(tenant_id, category);
CREATE INDEX idx_quick_reply_templates_is_public ON quick_reply_templates(is_public);

-- ============================================================
-- RLS 策略（多租户隔离）
-- ============================================================

-- agent_sessions RLS
ALTER TABLE agent_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_agent_sessions ON agent_sessions
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- agent_messages RLS
ALTER TABLE agent_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_agent_messages ON agent_messages
    USING (tenant_id::text = current_setting('app.current_tenant_id'));

-- quick_reply_templates RLS
ALTER TABLE quick_reply_templates ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_quick_reply_templates ON quick_reply_templates
    USING (tenant_id::text = current_setting('app.current_tenant_id'));
