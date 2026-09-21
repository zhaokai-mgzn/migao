package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.InboundOrderItem;
import org.apache.ibatis.annotations.Mapper;

/**
 * InboundOrderItem Mapper（V111，issue #5034）
 */
@Mapper
public interface InboundOrderItemMapper extends BaseMapper<InboundOrderItem> {
}
