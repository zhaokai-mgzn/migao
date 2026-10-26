package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.OutboundOrder;
import org.apache.ibatis.annotations.Mapper;

/**
 * 出库单（V196，issue #7750）：只继承 BaseMapper。
 *
 * <p>单号唯一由 {@code uk_outbound_orders_no} 兜住（取号走服务层的「候选 + exists」循环，
 * 与入库单 {@code nextFreeInboundNo} 同口径）；状态只有 {@code posted} 一个取值（DB CHECK），
 * 没有需要原子迁移的状态机 ⇒ 不需要手写 CAS SQL。</p>
 */
@Mapper
public interface OutboundOrderMapper extends BaseMapper<OutboundOrder> {
}
