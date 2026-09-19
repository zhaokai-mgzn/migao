package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionPieceworkSettlementLine;
import org.apache.ibatis.annotations.Mapper;

/**
 * 计件工资结算明细 Mapper（V75，issue #4483）—— 逐笔可追溯（真值源 §4）
 */
@Mapper
public interface ProductionPieceworkSettlementLineMapper
        extends BaseMapper<ProductionPieceworkSettlementLine> {
}
