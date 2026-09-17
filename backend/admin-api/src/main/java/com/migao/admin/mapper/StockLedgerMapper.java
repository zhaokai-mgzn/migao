package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.StockLedger;
import org.apache.ibatis.annotations.Mapper;

/**
 * 库存流水/台账 Mapper（V53，issue #4055）：SKU 级库存变更事实账
 */
@Mapper
public interface StockLedgerMapper extends BaseMapper<StockLedger> {
}