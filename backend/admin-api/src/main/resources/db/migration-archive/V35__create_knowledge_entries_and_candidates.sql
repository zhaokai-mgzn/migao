-- 知识词条表：LLM WIKI 板块核心数据模型（issue #3051，替代 RAG 文档模型成为知识主表）
-- 知识单元从「chunk」升级为「结构化词条」：AI 客服直接读词条回答，检索用结构化过滤 + 关键词，不引入向量库。
CREATE TABLE IF NOT EXISTS knowledge_entries (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    title VARCHAR(255) NOT NULL,
    category VARCHAR(64),
    industry VARCHAR(64) DEFAULT 'curtain',
    source_type VARCHAR(32) NOT NULL,
    source_ref VARCHAR(128),
    question TEXT,
    answer TEXT NOT NULL,
    keywords TEXT,
    apply_products JSONB DEFAULT '[]',
    variables JSONB DEFAULT '{}',
    status VARCHAR(32) DEFAULT 'draft',
    version INTEGER DEFAULT 1,
    review_note TEXT,
    created_by VARCHAR(64),
    reviewed_by VARCHAR(64),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_knowledge_entries_tenant ON knowledge_entries(tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_entries_status ON knowledge_entries(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_entries_category ON knowledge_entries(category);

-- 提炼候选表：AI 提炼（会话/文档/商品）→ 商家待采纳队列
-- 核心不变式：AI 只产生候选，发布权在商家（pending/adopted/edited/rejected）。
CREATE TABLE IF NOT EXISTS knowledge_candidates (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    source_ref VARCHAR(128),
    suggested_title VARCHAR(255) NOT NULL,
    suggested_answer TEXT NOT NULL,
    suggested_category VARCHAR(64),
    suggested_keywords TEXT,
    confidence NUMERIC(4,3),
    evidence TEXT,
    status VARCHAR(32) DEFAULT 'pending',
    status_note TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    reviewed_by VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_candidates_tenant ON knowledge_candidates(tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_candidates_status ON knowledge_candidates(status);
