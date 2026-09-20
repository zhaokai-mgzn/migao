package com.migao.admin.mapper;

import com.migao.admin.entity.OrderLogistics;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.ResultMap;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 物流跟踪 Mapper 接口
 *
 * <p>🔴 手写 {@code @Select} 必须显式绑 autoResultMap（口径见 {@code ProcessingOrderMapper} 类注释）：
 * 否则 {@code tracking_info}（JSONB）以 JSON 字符串落到 {@code Object} 字段上。</p>
 */
@Mapper
public interface OrderLogisticsMapper extends BaseMapper<OrderLogistics> {

    /**
     * 根据订单 ID 查询物流记录
     */
    @ResultMap("mybatis-plus_OrderLogistics")
    @Select("SELECT * FROM order_logistics WHERE order_id = #{orderId} AND deleted = 0 AND tenant_id = #{tenantId} ORDER BY created_at DESC")
    List<OrderLogistics> selectByOrderId(@Param("orderId") String orderId, @Param("tenantId") Long tenantId);
}
