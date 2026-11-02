package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.BriefingAction;
import org.apache.ibatis.annotations.Mapper;

/**
 * 决策采纳记录 Mapper（issue #8260）。
 * 租户隔离由 TenantLineInnerInterceptor 自动注入；RLS 策略兜底（同 DailyBriefingMapper）。
 */
@Mapper
public interface BriefingActionMapper extends BaseMapper<BriefingAction> {
}
