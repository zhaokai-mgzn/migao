package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.DailyBriefing;
import org.apache.ibatis.annotations.Mapper;

/**
 * 智能每日经营简报 Mapper（issue #3468）
 * 租户隔离由 TenantLineInnerInterceptor 自动注入；RLS 策略兜底。
 */
@Mapper
public interface DailyBriefingMapper extends BaseMapper<DailyBriefing> {
}
