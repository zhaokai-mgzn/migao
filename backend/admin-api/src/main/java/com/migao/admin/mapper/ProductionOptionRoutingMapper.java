package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionOptionRouting;
import org.apache.ibatis.annotations.Mapper;

/**
 * 特殊选项 → 条件工序 Mapper（V59，issue #4230）
 */
@Mapper
public interface ProductionOptionRoutingMapper extends BaseMapper<ProductionOptionRouting> {
}
