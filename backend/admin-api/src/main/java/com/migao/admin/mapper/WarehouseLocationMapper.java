package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.WarehouseLocation;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

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
     * 本仓内**水位最低且未满**的 active 仓位（V198 / issue #7791）。
     *
     * <p>水位 = 在库件数 / capacity；按比值升序、仓位号升序取第一个。
     * 「在库件数」只从 {@code finished_goods_stock} 的在库行派生 —— 仓位表上没有占用/计数字段
     * （第二份真相：发货/撤销漏改一次就永久占位）。</p>
     *
     * <p>🔴 {@code FOR UPDATE OF l} 是并发容量的**闸门**：调用方（{@code InboundOrderService}
     * 的过账事务）在同一事务内拿到行锁后才 insert，另一并发过账会在此阻塞并在提交后**重判**
     * {@code count < capacity} ⇒ 不会把同一个仓位塞过容量。本查询必须在**事务内**调用
     * （自动提交下锁立即释放，闸门失效）。</p>
     */
    @InterceptorIgnore(tenantLine = "true")
    @Options(useCache = false, flushCache = Options.FlushCachePolicy.TRUE)
    @Select("SELECT l.* FROM warehouse_locations l "
            + "WHERE l.tenant_id = #{tenantId} AND l.warehouse_id = #{warehouseId} "
            + "  AND l.status = 'active' AND l.deleted = 0 "
            + "  AND (SELECT count(*) FROM finished_goods_stock s "
            + "        WHERE s.tenant_id = l.tenant_id AND s.bin_code = l.bin_code "
            + "          AND s.status = 'in_stock' AND s.deleted = 0) < l.capacity "
            + "ORDER BY (SELECT count(*) FROM finished_goods_stock s "
            + "          WHERE s.tenant_id = l.tenant_id AND s.bin_code = l.bin_code "
            + "            AND s.status = 'in_stock' AND s.deleted = 0)::numeric / l.capacity ASC, "
            + "         l.bin_code ASC "
            + "LIMIT 1 FOR UPDATE OF l")
    WarehouseLocation selectBestBinForAllocation(@Param("tenantId") Long tenantId,
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
            + "(tenant_id, warehouse_id, zone_code, zone_name, bin_code, status, capacity, deleted) "
            + "VALUES (#{tenantId}, #{warehouseId}, #{zoneCode}, #{zoneName}, #{binCode}, 'active', #{capacity}, 0) "
            + "ON CONFLICT DO NOTHING")
    int claimBin(@Param("tenantId") Long tenantId,
                 @Param("warehouseId") Long warehouseId,
                 @Param("zoneCode") String zoneCode,
                 @Param("zoneName") String zoneName,
                 @Param("binCode") String binCode,
                 @Param("capacity") Integer capacity);

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

    /** 本区域现有容量（取本区任一仓位行的值；无仓位 ⇒ null）。区域容量由服务层统一同步。 */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT capacity FROM warehouse_locations "
            + "WHERE tenant_id = #{tenantId} AND warehouse_id = #{warehouseId} "
            + "  AND zone_code = #{zoneCode} AND deleted = 0 ORDER BY id LIMIT 1")
    Integer selectZoneCapacity(@Param("tenantId") Long tenantId,
                               @Param("warehouseId") Long warehouseId,
                               @Param("zoneCode") String zoneCode);

    /** 把本区域所有仓位的容量改成同一个值（issue #7791 的「容量按区域统一」）。 */
    @InterceptorIgnore(tenantLine = "true")
    @Update("UPDATE warehouse_locations SET capacity = #{capacity}, updated_at = NOW() "
            + "WHERE tenant_id = #{tenantId} AND warehouse_id = #{warehouseId} "
            + "  AND zone_code = #{zoneCode} AND deleted = 0")
    int updateCapacityByZone(@Param("tenantId") Long tenantId,
                             @Param("warehouseId") Long warehouseId,
                             @Param("zoneCode") String zoneCode,
                             @Param("capacity") Integer capacity);
}
