package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.StockTransfer;
import org.apache.ibatis.annotations.Mapper;

/** 调拨单（issue #7373）。 */
@Mapper
public interface StockTransferMapper extends BaseMapper<StockTransfer> {
}
