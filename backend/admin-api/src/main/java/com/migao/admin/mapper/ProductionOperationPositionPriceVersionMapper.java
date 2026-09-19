package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionOperationPositionPriceVersion;
import org.apache.ibatis.annotations.Mapper;

/**
 * 部位价目矩阵格的计件单价版本账（V86，issue #4587）
 * 对应表：{@code production_operation_position_price_versions}。
 */
@Mapper
public interface ProductionOperationPositionPriceVersionMapper
        extends BaseMapper<ProductionOperationPositionPriceVersion> {
}
