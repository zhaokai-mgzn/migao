package com.migao.admin.mapper;

import com.migao.admin.entity.Session;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.time.OffsetDateTime;
import java.util.Map;

/**
 * 会话 Mapper 接口
 */
@Mapper
public interface SessionMapper extends BaseMapper<Session> {

    /**
     * 看板会话维度聚合（#2886 性能优化：活跃会话数 + AI 会话数一次查询，替代 2 次串行 selectCount）。
     * 租户条件由 TenantLineInnerInterceptor 自动注入。
     */
    @Select("SELECT " +
            "COUNT(*) FILTER (WHERE updated_at >= #{activeThreshold}) AS active_sessions, " +
            "COUNT(*) FILTER (WHERE updated_at >= #{activeThreshold} AND ai_enabled = true) AS ai_sessions " +
            "FROM sessions WHERE deleted = 0")
    Map<String, Object> selectDashboardSessionStats(@Param("activeThreshold") OffsetDateTime activeThreshold);
}
