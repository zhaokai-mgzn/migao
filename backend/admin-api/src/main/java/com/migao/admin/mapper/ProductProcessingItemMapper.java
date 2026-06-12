package com.migao.admin.mapper;

import com.migao.admin.entity.ProductProcessingItem;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/**
 * 商品-加工项关联 Mapper 接口
 */
@Mapper
public interface ProductProcessingItemMapper extends BaseMapper<ProductProcessingItem> {
}
