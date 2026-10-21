package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.Stocktake;
import org.apache.ibatis.annotations.Mapper;

/** 盘点单（issue #7373 段 2）。 */
@Mapper
public interface StocktakeMapper extends BaseMapper<Stocktake> {
}
