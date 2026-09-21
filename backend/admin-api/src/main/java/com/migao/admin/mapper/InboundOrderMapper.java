package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.InboundOrder;
import org.apache.ibatis.annotations.Mapper;

/**
 * InboundOrder Mapper（V111，issue #5034）
 */
@Mapper
public interface InboundOrderMapper extends BaseMapper<InboundOrder> {
}
