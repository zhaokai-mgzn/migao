package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.WarehouseLocation;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * 仓位（V196，issue #7750）。
 *
 * <p>全部手写 SQL 都标 {@code @InterceptorIgnore(tenantLine = "true")}：它们<b>自己写了</b>
 * {@code tenant_id}，再让全局租户插件二次注入会改出错误 SQL（{@code INSERT … ON CONFLICT}
 * 与 {@code NOT EXISTS} 子查询都不是插件能安全改写的形态）。与 {@code ProductSkuMapper#deductStock}
 * 的既有写法同源。</p>
 *
 * <p>唯一一条手写 SQL 是**分配用的「最小空闲位」查询**：手写 SQL **不走**
 * {@code TenantLineInnerInterceptor} ⇒ {@code tenant_id} 必须自己写（漏写 = 跨租户串位），
 * 谓词里的 {@code deleted = 0} 同理（{@code @TableLogic} 只管自动生成的 SQL）。</p>
 */
@Mapper
public interface WarehouseLocationMapper extends BaseMapper<WarehouseLocation> {

    /**
     * 本仓内**空闲**的最小仓位号（空闲 = 没有任何 {@code in_stock} 成品占着它）。
     *
     * <p>「空闲」以 {@code finished_goods_stock} 的在库行为准，而不是仓库位表上的一个标志列：
     * 标志列就是第二份真相，发货/撤销没跟着改就永久占位。</p>
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT l.* FROM warehouse_locations l "
            + "WHERE l.tenant_id = #{tenantId} AND l.warehouse_id = #{warehouseId} "
            + "  AND l.status = 'active' AND l.deleted = 0 "
            + "  AND NOT EXISTS (SELECT 1 FROM finished_goods_stock s "
            + "                   WHERE s.tenant_id = l.tenant_id AND s.bin_code = l.bin_code "
            + "                     AND s.status = 'in_stock' AND s.deleted = 0) "
            + "ORDER BY l.bin_code LIMIT 1")
    WarehouseLocation selectFirstFreeBin(@Param("tenantId") Long tenantId,
                                         @Param("warehouseId") Long warehouseId);

    /**
     * **原子占号**：插入一个仓位；同号已存在（并发建了同一个号）⇒ 0 行、**不抛异常**。
     *
     * <p>为什么不用「先查后插」：唯一索引冲突会让 PG 当前事务进入 aborted 态
     * （后续任何查询都失败）⇒ 捕获 {@code DuplicateKeyException} 后再重试在同事务内是**非法**的。
     * {@code ON CONFLICT DO NOTHING} 把冲突变成「0 行受影响」，事务继续可用。</p>
     */
    @InterceptorIgnore(tenantLine = "true")
    @Insert("INSERT INTO warehouse_locations "
            + "(tenant_id, warehouse_id, zone_code, zone_name, bin_code, status, deleted) "
            + "VALUES (#{tenantId}, #{warehouseId}, #{zoneCode}, #{zoneName}, #{binCode}, 'active', 0) "
            + "ON CONFLICT DO NOTHING")
    int claimBin(@Param("tenantId") Long tenantId,
                 @Param("warehouseId") Long warehouseId,
                 @Param("zoneCode") String zoneCode,
                 @Param("zoneName") String zoneName,
                 @Param("binCode") String binCode);

    /** 按仓位号取本租户的仓位行（占号后回读真实 id）。 */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT * FROM warehouse_locations "
            + "WHERE tenant_id = #{tenantId} AND bin_code = #{binCode} AND deleted = 0")
    WarehouseLocation selectByBinCode(@Param("tenantId") Long tenantId, @Param("binCode") String binCode);

    /** 本仓本区域的仓位行数（新增号的起点；并发撞号由唯一索引 + 调用方重试兜住）。 */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT count(*) FROM warehouse_locations "
            + "WHERE tenant_id = #{tenantId} AND warehouse_id = #{warehouseId} "
            + "  AND zone_code = #{zoneCode} AND deleted = 0")
    int countBinsInZone(@Param("tenantId") Long tenantId,
                        @Param("warehouseId") Long warehouseId,
                        @Param("zoneCode") String zoneCode);
}
