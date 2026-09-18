package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionRoutingVersion;
import org.apache.ibatis.annotations.Mapper;

/**
 * 工艺路线版本账 Mapper（V60，issue #4308）
 */
@Mapper
public interface ProductionRoutingVersionMapper extends BaseMapper<ProductionRoutingVersion> {
}
