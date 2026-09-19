package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionPieceworkSettlement;
import org.apache.ibatis.annotations.Mapper;

/**
 * 计件工资结算单 Mapper（V75，issue #4483 = #4347 §二.4）
 */
@Mapper
public interface ProductionPieceworkSettlementMapper extends BaseMapper<ProductionPieceworkSettlement> {
}
