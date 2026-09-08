package com.migao.admin.mapper;

import com.migao.admin.entity.KnowledgeCandidate;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/**
 * 知识提炼候选Mapper接口（LLM WIKI 板块，issue #3051）
 * 标准 CRUD 由 TenantLineInnerInterceptor 自动注入租户过滤。
 */
@Mapper
public interface KnowledgeCandidateMapper extends BaseMapper<KnowledgeCandidate> {
}
