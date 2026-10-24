package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.StockTransferItem;
import org.apache.ibatis.annotations.Mapper;

/** 调拨明细（issue #7373）。 */
@Mapper
public interface StockTransferItemMapper extends BaseMapper<StockTransferItem> {
}
