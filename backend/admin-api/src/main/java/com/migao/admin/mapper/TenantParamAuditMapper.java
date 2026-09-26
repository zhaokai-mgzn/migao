package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.TenantParamAudit;
import org.apache.ibatis.annotations.Mapper;

/**
 * 企业参数变更留痕（V131，issue #5131 P6）。对应表：{@code tenant_param_audit}。
 *
 * <p>本单**只有写面**（{@code insert}）—— 读面（「这个参数被谁改过」的展示）属增量 2 的参数中心，
 * 届时按 {@code (tenant_id, param_domain, param_key, created_at DESC)} 这条既有索引查，
 * <b>不要</b>在这里提前加没人调用的查询方法（最少代码阶梯：先理解再爬梯）。</p>
 *
 * <p>⚠️ 本表的 {@code insert} 由 {@link com.migao.admin.service.TenantParamAuditService} 调用，
 * 且**恒在 try/catch 内**（口径 B = best-effort，用户 2026-09-26 裁定）：本 mapper 抛异常
 * **不得**让配置保存失败。</p>
 */
@Mapper
public interface TenantParamAuditMapper extends BaseMapper<TenantParamAudit> {
}
