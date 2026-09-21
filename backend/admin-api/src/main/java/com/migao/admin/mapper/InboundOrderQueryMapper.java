package com.migao.admin.mapper;

import com.migao.admin.dto.InboundOrderLine;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 入库单列表聚合读面（V111，issue #5034）。
 *
 * <p>列表页要显示「几行 / 共几件」，而这两个数是明细的**聚合**。放在 SQL 里一次算完，
 * 好过先查单再逐单查明细（N+1）。</p>
 */
@Mapper
public interface InboundOrderQueryMapper {

    /**
     * 按租户 + 可选条件查入库单（含行数/总量聚合），按入库日期倒序、同日内按单号倒序。
     *
     * @param keyword 模糊匹配 入库单号 / 供应商 / 供应商送货单号；null 或空串 = 不过滤
     * @param status  精确匹配状态；null 或空串 = 不过滤
     */
    @Select("""
            <script>
            SELECT o.id                        AS id,
                   o.inbound_no                AS inboundNo,
                   o.supplier                  AS supplier,
                   o.supplier_doc_no           AS supplierDocNo,
                   o.warehouse                 AS warehouse,
                   o.inbound_date              AS inboundDate,
                   o.status                    AS status,
                   o.total_amount              AS totalAmount,
                   o.remark                    AS remark,
                   o.posted_at                 AS postedAt,
                   o.posted_by                 AS postedBy,
                   o.created_at                AS createdAt,
                   COALESCE(a.item_count, 0)   AS itemCount,
                   COALESCE(a.total_qty, 0)    AS totalQuantity
              FROM inbound_orders o
              LEFT JOIN (
                    SELECT inbound_order_id,
                           COUNT(*)      AS item_count,
                           SUM(quantity) AS total_qty
                      FROM inbound_order_items
                     WHERE deleted = 0
                     GROUP BY inbound_order_id
                   ) a ON a.inbound_order_id = o.id
             WHERE o.tenant_id = #{tenantId}
               AND o.deleted = 0
               <if test="status != null and status != ''">
               AND o.status = #{status}
               </if>
               <if test="keyword != null and keyword != ''">
               AND (o.inbound_no ILIKE '%' || #{keyword} || '%'
                    OR o.supplier ILIKE '%' || #{keyword} || '%'
                    OR o.supplier_doc_no ILIKE '%' || #{keyword} || '%')
               </if>
             ORDER BY o.inbound_date DESC, o.inbound_no DESC
             LIMIT #{limit}
            </script>
            """)
    List<InboundOrderLine> selectOrderLines(@Param("tenantId") Long tenantId,
                                            @Param("keyword") String keyword,
                                            @Param("status") String status,
                                            @Param("limit") int limit);
}
