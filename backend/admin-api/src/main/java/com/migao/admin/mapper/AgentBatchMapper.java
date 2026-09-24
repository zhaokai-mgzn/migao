package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.AgentBatch;
import org.apache.ibatis.annotations.Mapper;

/**
 * 批次 Mapper（issue #5314）。标准 CRUD 由 {@code TenantLineInnerInterceptor}
 * 自动注入租户过滤 ⇒ {@code selectById} 天然看不见别的租户的批次（跨租户 = NOT_FOUND）。
 */
@Mapper
public interface AgentBatchMapper extends BaseMapper<AgentBatch> {
}