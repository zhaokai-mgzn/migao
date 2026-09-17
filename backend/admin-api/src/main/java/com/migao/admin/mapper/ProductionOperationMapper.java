package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionOperation;
import org.apache.ibatis.annotations.Mapper;

/**
 * 生产工序库 Mapper（V49，issue #3995）
 */
@Mapper
public interface ProductionOperationMapper extends BaseMapper<ProductionOperation> {
}
