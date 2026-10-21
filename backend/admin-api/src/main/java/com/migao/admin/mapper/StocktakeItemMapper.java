package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.StocktakeItem;
import org.apache.ibatis.annotations.Mapper;

/** 盘点明细（issue #7373 段 2）。 */
@Mapper
public interface StocktakeItemMapper extends BaseMapper<StocktakeItem> {
}
