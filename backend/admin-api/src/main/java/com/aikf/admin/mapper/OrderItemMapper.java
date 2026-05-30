package com.aikf.admin.mapper;

import com.aikf.admin.entity.OrderItem;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 订单明细 Mapper 接口
 */
@Mapper
public interface OrderItemMapper extends BaseMapper<OrderItem> {

    /**
     * 根据订单 ID 查询订单明细列表
     */
    @Select("SELECT * FROM order_items WHERE order_id = #{orderId} AND tenant_id = #{tenantId} AND deleted = 0")
    List<OrderItem> selectByOrderId(@Param("orderId") String orderId, @Param("tenantId") Long tenantId);
}
