-- 最小前置库：只建 V79/V88 触及的 3 张配置表 + tenants（DDL 逐字取自 docs/sql/schema.sql @f511c0fa0）
DROP TABLE IF EXISTS production_operation_positions CASCADE;
DROP TABLE IF EXISTS production_route_templates CASCADE;
DROP TABLE IF EXISTS production_operations CASCADE;
DROP TABLE IF EXISTS tenants CASCADE;
CREATE TABLE tenants (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    code VARCHAR(64) UNIQUE NOT NULL,
    industry VARCHAR(64),
    status VARCHAR(32) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS production_operations (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(64) NOT NULL,
    group_name VARCHAR(16) NOT NULL DEFAULT '其他',
    position VARCHAR(16),
    unit VARCHAR(16) NOT NULL DEFAULT '米',
    unit_price NUMERIC(10,2) NOT NULL DEFAULT 0,
    is_must_finish BOOLEAN NOT NULL DEFAULT FALSE,
    is_start_marker BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INT NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_operations_tenant_name
    ON production_operations (tenant_id, name) WHERE deleted = 0;
ALTER TABLE production_operations ADD COLUMN IF NOT EXISTS scope VARCHAR(16) NOT NULL DEFAULT 'position';
ALTER TABLE production_operations ADD COLUMN IF NOT EXISTS source VARCHAR(16);
ALTER TABLE production_operations ADD COLUMN IF NOT EXISTS position VARCHAR(16);
CREATE TABLE IF NOT EXISTS production_operation_positions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    logical_name VARCHAR(64) NOT NULL,
    position VARCHAR(16) NOT NULL,
    unit_price NUMERIC(10,2),
    applicable BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_operation_positions_tenant_name_position
    ON production_operation_positions (tenant_id, logical_name, position) WHERE deleted = 0;
ALTER TABLE production_operation_positions ADD COLUMN IF NOT EXISTS source VARCHAR(16);
CREATE TABLE IF NOT EXISTS production_route_templates (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    positions JSONB NOT NULL DEFAULT '[]'::jsonb,
    mainline JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_route_templates_tenant_name
    ON production_route_templates (tenant_id, name) WHERE deleted = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_route_templates_tenant_default
    ON production_route_templates (tenant_id) WHERE is_default AND deleted = 0;

-- 两个租户（含 1 号）：V79 的「按租户循环」需要 tenants 里有行
INSERT INTO tenants (name, code) VALUES ('米高自营', 'T1'), ('二号商家', 'T2');
