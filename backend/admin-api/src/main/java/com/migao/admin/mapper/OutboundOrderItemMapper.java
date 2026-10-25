package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.OutboundOrderItem;
import org.apache.ibatis.annotations.Mapper;

/** 出库单明细（V196，issue #7750）：只继承 BaseMapper（按单查明细走 LambdaQueryWrapper）。 */
@Mapper
public interface OutboundOrderItemMapper extends BaseMapper<OutboundOrderItem> {
}
