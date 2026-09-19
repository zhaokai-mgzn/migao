package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionCraft;
import org.apache.ibatis.annotations.Mapper;

/**
 * 工艺词表 + 商户级默认工艺（V72，issue #4432）
 * 对应表：{@code production_crafts}。
 */
@Mapper
public interface ProductionCraftMapper extends BaseMapper<ProductionCraft> {
}
