package com.migao.admin.mapper;

import com.migao.admin.dto.ShipmentListRow;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 发货单**列表**聚合读面（issue #5939）。
 *
 * <p>列表要显示「客户 / 明细行数」，而这两项分别来自 {@code orders} 与明细的聚合 —— 放在 SQL 里
 * 一次算完，好过先查单再逐单查明细（N+1）。这与 {@code InboundOrderQueryMapper} 同族
 * （入库单列表也是「主表 + 聚合子查询 + LIMIT」）。</p>
 *
 * <p>🔴 手写 SQL 是本面唯一不会被类型系统挡住的地方（租户隔离 / 软删 / 上限），因此它的契约由
 * {@code OrderShipmentQueryMapperTest}（文本判据）与
 * {@code ShipmentListQueryRealDbTest}（真库语义）两份判据分别把守。</p>
 */
@Mapper
public interface OrderShipmentQueryMapper {

    /**
     * 本租户的发货单列表（近的在前），带客户名与明细行数。
     *
     * @param keyword 模糊匹配 发货单号 / 订单号 / 客户名；null 或空串 = 不过滤
     * @param limit   上限（调用方给 {@code OrderShipmentService.LIST_LIMIT}）—— 流水型单据不做深分页，
     *                但**绝不无界返回**
     */
    @Select("""
            <script>
            SELECT s.id                        AS id,
                   s.shipment_no               AS shipmentNo,
                   s.order_id                  AS orderId,
                   s.order_no                  AS orderNo,
                   o.customer_name             AS customerName,
                   s.source                    AS source,
                   s.packed_at                 AS packedAt,
                   s.shipped_at                AS shippedAt,
                   s.shipped_by_worker_name    AS shippedByWorkerName,
                   s.tracking_no               AS trackingNo,
                   s.logistics_company         AS logisticsCompany,
                   COALESCE(a.itemCount, 0)    AS itemCount
              FROM order_shipments s
              LEFT JOIN orders o
                     ON o.id = s.order_id
                    AND o.tenant_id = s.tenant_id
                    AND o.deleted = 0
              LEFT JOIN (
                    SELECT shipment_id,
                           COUNT(*) AS itemCount
                      FROM order_shipment_items
                     WHERE tenant_id = #{tenantId}
                       AND deleted = 0
                     GROUP BY shipment_id
                   ) a ON a.shipment_id = s.id
             WHERE s.tenant_id = #{tenantId}
               AND s.deleted = 0
               <if test="keyword != null and keyword != ''">
               AND (s.shipment_no ILIKE '%' || #{keyword} || '%'
                    OR s.order_no ILIKE '%' || #{keyword} || '%'
                    OR o.customer_name ILIKE '%' || #{keyword} || '%')
               </if>
             ORDER BY COALESCE(s.shipped_at, s.packed_at, s.created_at) DESC, s.id DESC
             LIMIT #{limit}
            </script>
            """)
    List<ShipmentListRow> selectListRows(@Param("tenantId") Long tenantId,
                                         @Param("keyword") String keyword,
                                         @Param("limit") int limit);
}
