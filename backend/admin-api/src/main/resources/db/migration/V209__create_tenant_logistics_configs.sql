-- V209 / issue #8698：物流取号（电子面单）**租户级配置**表
--
-- ## 一句话
-- 一家店一行，只存一件事实：**发货默认走哪家承运商**（`carrier_code`）。
-- 缺行 / `carrier_code IS NULL` ⇒ **全 manual**（今天的手填单号能力）。
--
-- ## 为什么必须是表（不能塞进 tenants 的某个 JSONB）
-- `carrier_code` 是**可写、可读、要按租户唯一**的配置项，且写面有白名单校验
-- （只能是承运商注册表里登记过的 code 或 `manual`）。塞进 `tenants.auth_config` 之类的
-- 通用 JSONB 会把它变成「谁都能写、谁都不校验」的字段 —— 写错一个 code 就落到
-- 「配了却永远手动」，而没有任何东西会红。
--
-- ## 为什么不做开租播种
-- 与 `craft_calc_configs` / `cutting_height_configs` 同一口径：**缺行 = 用默认值**，
-- 默认值唯一来源在 Java（`CarrierCatalogue.MANUAL_CODE`）。库里再种一份 =
-- 第二份会漂的默认值（商家换默认承运商时两处不一致，且没有任何判据看得见）。
--
-- ## 凭据面（口径 `docs/logistics-waybill-api-research.md` §3-4）
-- 本表**不含任何承运商密钥列**：P0 不接第三方；P1 接入时凭据只进服务端、按租户存，
-- 且**不得**出现在任何下发给浏览器的响应里（判据
-- `tests/unit_ci_workflows/test_waybill_no_carrier_secrets.py` 对前端产物做静态 grep）。

CREATE TABLE IF NOT EXISTS tenant_logistics_configs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    carrier_code VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);

-- 租户级**单行**（部分唯一索引：软删行不占位）
CREATE UNIQUE INDEX IF NOT EXISTS uk_tenant_logistics_configs_tenant
    ON tenant_logistics_configs (tenant_id)
    WHERE deleted = 0;

COMMENT ON TABLE tenant_logistics_configs IS
    '物流取号**租户级配置**（V209，issue #8698 P0）。单行/租户，**缺行 = 全 manual**'
    '（不做开租播种；默认值唯一来源 = CarrierCatalogue.MANUAL_CODE）。'
    '只存承运商选择，不存任何凭据（凭据面口径见 docs/logistics-waybill-api-research.md §3-4）。';

COMMENT ON COLUMN tenant_logistics_configs.carrier_code IS
    '承运商 code（CarrierCatalogue 的登记行，如 sf/zto/sja；manual = 手填）。'
    'NULL/缺行 ⇒ 全 manual。写面白名单 = 注册表现取（未登记 ⇒ 422，不静默落库）。';
