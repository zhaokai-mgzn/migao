package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionOptionFactor;
import org.apache.ibatis.annotations.Mapper;

/**
 * 特殊选项 → 计件系数 Mapper（V59，issue #4230）
 */
@Mapper
public interface ProductionOptionFactorMapper extends BaseMapper<ProductionOptionFactor> {
}
