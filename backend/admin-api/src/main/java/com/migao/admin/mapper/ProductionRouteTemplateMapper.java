package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionRouteTemplate;
import org.apache.ibatis.annotations.Mapper;

/**
 * 具名工艺路线模板（V71 / V72，issue #4427 + #4432）
 * 对应表：{@code production_route_templates}。
 */
@Mapper
public interface ProductionRouteTemplateMapper extends BaseMapper<ProductionRouteTemplate> {
}
