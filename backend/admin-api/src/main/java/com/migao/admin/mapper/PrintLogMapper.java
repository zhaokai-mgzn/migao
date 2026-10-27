package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.dto.PrintLogSummary;
import com.migao.admin.entity.PrintLog;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Result;
import org.apache.ibatis.annotations.Results;
import org.apache.ibatis.annotations.Select;

import java.util.Collection;
import java.util.List;

/**
 * 打印流水 Mapper（V201，issue #7902）。
 *
 * <p>两条手写 {@code @Select} 都是**只读面**（写面只有 {@link BaseMapper#insert}）——
 * 打印流水是 append-only 的事实记录：没有 update / delete 的入口，也不加 {@code deleted} 列
 * （「登记过」这件事本身不可撤销；打错了是「再打一次」，不是「抹掉历史」）。</p>
 *
 * <p>🔴 两个方法都显式带 {@code tenant_id}：租户插件（{@code TenantLineInnerInterceptor}）会再注入一次
 * 同值条件（与本仓 {@code ProcessingOrderMapper} 的既有写法同口径）—— 冗余但无害，
 * 且让「这段 SQL 单独拿出来看也是租户隔离的」。</p>
 */
@Mapper
public interface PrintLogMapper extends BaseMapper<PrintLog> {

    /**
     * 某张订单的打印流水（详情页时间轴），按时间倒序。
     *
     * @param limit 已由服务层收敛（默认 20 / 封顶 100）；空集合或越界值不会走到这里
     */
    @Select("SELECT * FROM print_logs WHERE tenant_id = #{tenantId} AND order_id = #{orderId} "
            + "ORDER BY created_at DESC LIMIT #{limit}")
    List<PrintLog> selectByOrder(@Param("tenantId") Long tenantId,
                                 @Param("orderId") String orderId,
                                 @Param("limit") int limit);

    /**
     * **批量**打印汇总（订单列表的「是否已打印」）：把 N 次单查压成 1 次。
     *
     * <p>🔴 只聚合 {@code status = 'fired'}：{@code failed} 表示纸**没有**出来，
     * 把它算进「已打印」会让商家以为这张单打过了（重打一次才发现）。
     * 故 `printed_at` / `print_count` / `doc_types` 三个读数都只反映成功发起的那些。</p>
     *
     * <p>⚠️ {@code doc_types} 是 {@code string_agg} 的**原始逗号串**（无序、可能重复）——
     * 去重排序在 {@link PrintLogSummary#printedDocTypes()} 一处做（别让每个调用方各写一遍）。</p>
     *
     * @param orderIds 非空集合（调用方保证；空集合渲染成 {@code IN ()} 是语法错误）
     */
    @Results(id = "printLogSummary", value = {
            @Result(column = "order_id", property = "orderId"),
            @Result(column = "printed_at", property = "printedAt"),
            @Result(column = "print_count", property = "printCount"),
            @Result(column = "doc_types", property = "docTypes")
    })
    @Select("<script>SELECT order_id, MAX(created_at) AS printed_at, COUNT(*) AS print_count, "
            + "string_agg(DISTINCT doc_type, ',') AS doc_types FROM print_logs "
            + "WHERE tenant_id = #{tenantId} AND status = 'fired' AND order_id IN "
            + "<foreach collection='orderIds' item='orderId' open='(' separator=',' close=')'>#{orderId}</foreach> "
            + "GROUP BY order_id</script>")
    List<PrintLogSummary> selectPrintSummary(@Param("tenantId") Long tenantId,
                                             @Param("orderIds") Collection<String> orderIds);
}
