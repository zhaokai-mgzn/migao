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
 *
 * <p>类别维（V196 / issue #7794）：{@code inbound_orders.biz_category} 是「原料仓入库 /
 * 成品仓入库」两个视图的**唯一分界** ⇒ 列表必须能按它精确过滤、也要把它带出给页面。</p>
 */
@Mapper
public interface InboundOrderQueryMapper {

    /**
     * 按租户 + 可选条件查入库单（含行数/总量/套数聚合），按入库日期倒序、同日内按单号倒序。
     *
     * @param keyword 模糊匹配 入库单号 / 供应商 / 供应商送货单号；null 或空串 = 不过滤
     * @param status  精确匹配状态；null 或空串 = 不过滤
     * @param bizCategory 精确匹配业务类别（fabric 原料仓 / finished 成品仓，V196）；
     *                    null 或空串 = 不过滤（向后兼容：既有调用点与站内信深链行为不变）
     * @param warehouseId 精确匹配仓库主数据引用（issue #7807：列表按仓查单）；
     *                    null = 全部仓库（既有调用点与站内信深链行为不变）
     */
    @Select("""
            <script>
            SELECT o.id                        AS id,
                   o.inbound_no                AS inboundNo,
                   o.biz_category              AS bizCategory,
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
                   COALESCE(a.total_qty, 0)    AS totalQuantity,
                   COALESCE(a.set_count, 0)    AS setCount,
                   a.batch_nos                 AS batchNos
              FROM inbound_orders o
              LEFT JOIN (
                    SELECT inbound_order_id,
                           COUNT(*)      AS item_count,
                           SUM(quantity) AS total_qty,
                           COUNT(DISTINCT COALESCE(set_id, '#' || id)) AS set_count,
                           string_agg(batch_no, ',' ORDER BY batch_no) AS batch_nos
                      FROM inbound_order_items
                     WHERE deleted = 0
                     GROUP BY inbound_order_id
                   ) a ON a.inbound_order_id = o.id
             WHERE o.tenant_id = #{tenantId}
               AND o.deleted = 0
               <if test="bizCategory != null and bizCategory != ''">
               AND o.biz_category = #{bizCategory}
               </if>
               <if test="warehouseId != null">
               AND o.warehouse_id = #{warehouseId}
               </if>
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
                                            @Param("bizCategory") String bizCategory,
                                            @Param("warehouseId") Long warehouseId,
                                            @Param("limit") int limit);
}
