package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.migao.admin.dto.OutboundOrderView;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 出库单列表聚合读面（V196，issue #7750）—— 与入库单列表读面同形。
 *
 * <p>列表要显示「几行 / 共多少」，放在 SQL 里一次算完（不做先查单再逐单查明细的 N+1）。
 * ⚠️ 手写 SQL **不走** {@code TenantLineInnerInterceptor} ⇒ {@code tenant_id} 在单头与明细
 * 两侧都自己写（漏写 = 跨租户串单）。</p>
 */
@Mapper
public interface OutboundOrderQueryMapper {

    /**
     * 按租户 + 可选条件查出库单（含行数/总量聚合），按出库日期倒序、同日按单号倒序。
     *
     * @param keyword 模糊匹配 出库单号 / 仓库 / 关联订单号；null 或空串 = 不过滤
     * @param bizCategory 精确匹配业务类别（fabric / finished）；null 或空串 = 不过滤
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("""
            <script>
            SELECT o.id                        AS id,
                   o.outbound_no                AS outboundNo,
                   o.biz_category               AS bizCategory,
                   o.source                     AS source,
                   o.warehouse_id               AS warehouseId,
                   o.warehouse                  AS warehouse,
                   o.outbound_date              AS outboundDate,
                   o.status                     AS status,
                   o.total_amount               AS totalAmount,
                   o.order_id                   AS orderId,
                   o.order_no                   AS orderNo,
                   o.remark                     AS remark,
                   o.posted_at                  AS postedAt,
                   o.posted_by                  AS postedBy,
                   o.created_at                 AS createdAt,
                   COALESCE(a.item_count, 0)    AS itemCount,
                   COALESCE(a.total_qty, 0)     AS totalQuantity
              FROM outbound_orders o
              LEFT JOIN (
                    SELECT outbound_order_id,
                           COUNT(*)      AS item_count,
                           SUM(quantity) AS total_qty
                      FROM outbound_order_items
                     WHERE tenant_id = #{tenantId} AND deleted = 0
                     GROUP BY outbound_order_id
                   ) a ON a.outbound_order_id = o.id
             WHERE o.tenant_id = #{tenantId}
               AND o.deleted = 0
               <if test="bizCategory != null and bizCategory != ''">
               AND o.biz_category = #{bizCategory}
               </if>
               <if test="keyword != null and keyword != ''">
               AND (o.outbound_no ILIKE '%' || #{keyword} || '%'
                    OR o.warehouse ILIKE '%' || #{keyword} || '%'
                    OR o.order_no ILIKE '%' || #{keyword} || '%')
               </if>
             ORDER BY o.outbound_date DESC, o.outbound_no DESC
             LIMIT #{limit}
            </script>
            """)
    List<OutboundOrderView> selectOrderLines(@Param("tenantId") Long tenantId,
                                             @Param("keyword") String keyword,
                                             @Param("bizCategory") String bizCategory,
                                             @Param("limit") int limit);
}
