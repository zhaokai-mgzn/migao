package com.aikf.admin.mapper;

import com.aikf.admin.entity.OrderLogistics;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 物流跟踪 Mapper 接口
 */
@Mapper
public interface OrderLogisticsMapper extends BaseMapper<OrderLogistics> {

    /**
     * 根据订单 ID 查询物流记录
     */
    @Select("SELECT * FROM order_logistics WHERE order_id = #{orderId} AND deleted = 0 AND tenant_id = #{tenantId} ORDER BY created_at DESC")
    List<OrderLogistics> selectByOrderId(@Param("orderId") String orderId, @Param("tenantId") Long tenantId);
}
