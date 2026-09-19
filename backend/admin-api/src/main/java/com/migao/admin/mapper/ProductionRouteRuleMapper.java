package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionRouteRule;
import org.apache.ibatis.annotations.Mapper;

/**
 * 工艺路线规则表（V71 / V72，issue #4427 + #4432）
 * 对应表：{@code production_route_rules}。
 */
@Mapper
public interface ProductionRouteRuleMapper extends BaseMapper<ProductionRouteRule> {
}
