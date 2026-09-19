package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionOperationPosition;
import org.apache.ibatis.annotations.Mapper;

/**
 * 部位价目 + 适用性矩阵（V71 / V72，issue #4427 + #4432）
 * 对应表：{@code production_operation_positions}。
 */
@Mapper
public interface ProductionOperationPositionMapper extends BaseMapper<ProductionOperationPosition> {
}
