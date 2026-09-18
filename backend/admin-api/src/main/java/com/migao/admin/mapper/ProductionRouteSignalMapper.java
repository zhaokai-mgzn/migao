package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionRouteSignal;
import org.apache.ibatis.annotations.Mapper;

/**
 * 信号 → 路线键映射 Mapper（V60，issue #4308）
 */
@Mapper
public interface ProductionRouteSignalMapper extends BaseMapper<ProductionRouteSignal> {
}
