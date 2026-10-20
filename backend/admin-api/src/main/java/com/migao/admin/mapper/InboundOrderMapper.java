package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.InboundOrder;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;

/**
 * InboundOrder Mapper（V111，issue #5034；V117 / issue #5148 追加过账原子闸）
 */
@Mapper
public interface InboundOrderMapper extends BaseMapper<InboundOrder> {

    /**
     * 按名称**精确匹配**本租户的供应商档案 id（issue #7369 段 2，用户 2026-10-20 裁定 A 口径）。
     *
     * <p>返回<b>全部</b>匹配（不在这里判唯一）：同名多家 = 歧义 ⇒ 调用方必须留 NULL，
     * 「猜一家」正是本口径要避免的。⚠️ 手写 SQL **不走** {@code TenantLineInnerInterceptor}
     * ⇒ `tenant_id` 必须自己写（漏写 = 跨租户串档）。</p>
     */
    @Select("SELECT id FROM suppliers "
            + "WHERE tenant_id = #{tenantId} AND deleted = FALSE AND btrim(name) = btrim(#{name})")
    List<String> selectSupplierIdsByExactName(@Param("tenantId") Long tenantId, @Param("name") String name);

    /**
     * 显式指定的供应商档案是否属于本租户（返回 status；空 = 不存在或跨租户）。
     *
     * <p>跨租户与不存在**同一个结果**（都当「不存在」处理，不泄露对方的存在性）。</p>
     */
    @Select("SELECT status FROM suppliers "
            + "WHERE tenant_id = #{tenantId} AND id = #{supplierId} AND deleted = FALSE")
    String selectSupplierStatusInTenant(@Param("tenantId") Long tenantId,
                                       @Param("supplierId") String supplierId);

    /**
     * 「待指派」清单：有供应商**文本**但没有档案**引用**的入库单，按文本名分组（issue #7369 段 2）。
     *
     * <p>这是 A 口径的**人工出口**：精确匹配不上的行不许猜，也不许丢 —— 列出来让人建档或指派。</p>
     */
    @Select("SELECT btrim(supplier) AS supplier_name, count(*) AS order_count, "
            + "       max(inbound_date) AS last_inbound_date "
            + "FROM inbound_orders "
            + "WHERE tenant_id = #{tenantId} AND deleted = 0 AND supplier_id IS NULL "
            + "  AND supplier IS NOT NULL AND btrim(supplier) <> '' "
            + "GROUP BY btrim(supplier) ORDER BY count(*) DESC, btrim(supplier) LIMIT 200")
    List<Map<String, Object>> selectUnassignedSupplierNames(@Param("tenantId") Long tenantId);

    /**
     * 过账的**原子闸**：条件更新（CAS）—— 只有当前仍是 {@code draft} 才置 {@code posted}。
     *
     * <p>为什么不用「先读 status 判 draft，再 {@code updateById} 写」：读与写之间有窗口，
     * 双击 / 并发会让两个请求**都**通过判断 ⇒ 各自加一遍库存（库存加两次、台账两条）。
     * 条件更新的「判断」与「写入」是**同一条语句**，PostgreSQL 对命中行加行锁并持有到事务结束
     * ⇒ 并发的第二个请求要么阻塞到前者提交、要么看到 0 行受影响。</p>
     *
     * <p>{@code posted_at} / {@code posted_by} 与状态**同一句**写入：库存是资金级数据，
     * 「谁在何时把它改成已过账」不能与状态迁移分成两次写（中间态无法追责）。</p>
     *
     * <p>谓词带 {@code deleted = 0}：MyBatis-Plus 的 {@code @TableLogic} 只对自动生成的 SQL 生效，
     * 手写 SQL 必须自己带上（软删的单不得过账）。</p>
     *
     * @return 影响行数：{@code 1} = 本请求抢到过账权；{@code 0} = 已被过账 / 已作废 / 单不存在
     */
    @Update("UPDATE inbound_orders SET status = 'posted', posted_at = #{postedAt}, posted_by = #{operator}, "
            + "updated_at = NOW() WHERE id = #{id} AND tenant_id = #{tenantId} "
            + "AND status = 'draft' AND deleted = 0")
    int markPosted(@Param("id") String id,
                   @Param("tenantId") Long tenantId,
                   @Param("operator") String operator,
                   @Param("postedAt") OffsetDateTime postedAt);

    /**
     * 作废的**原子闸**：条件更新（CAS）—— 只有当前仍是 {@code draft} 才置 {@code cancelled}。
     *
     * <p><b>为什么必须与 {@link #markPosted} 同款</b>（issue #6928）：{@code InboundOrderService#post}
     * 与 {@code #cancel} 争的是**同一份状态迁移权**。改前 {@code #cancel} 走「先读 status 判 draft、
     * 再 {@code updateById}（WHERE 仅主键 ⇒ 无谓词）」：读-判-写之间的窗口里 {@code #post} 的 CAS
     * 可以抢到过账权并提交（库存 +N 米、{@code stock_ledger_entries} 恰 1 行），随后 {@code #cancel}
     * 的无谓词写把该单**覆写**成 {@code cancelled} ⇒ 同一张单两个请求都回 200、终态却是
     * {@code cancelled}，而库存与入库台账**静默留在库里**（账实不符且无任何 4xx）。
     * 一个写面有 CAS、另一个没有 ⇒ 两者**不互斥**；把判断与写入压进**同一条语句**才互斥。</p>
     *
     * <p>{@code cancelled_at} / {@code cancelled_by} / {@code cancelled_reason} 与状态**同一句**写入：
     * 「谁在何时为什么作废」不能与状态迁移分成两次写（中间态无法追责）。</p>
     *
     * <p>谓词带 {@code deleted = 0}：MyBatis-Plus 的 {@code @TableLogic} 只对自动生成的 SQL 生效，
     * 手写 SQL 必须自己带上（软删的单不得作废）。</p>
     *
     * @return 影响行数：{@code 1} = 本请求抢到作废权；{@code 0} = 已被过账 / 已作废 / 单不存在
     */
    @Update("UPDATE inbound_orders SET status = 'cancelled', cancelled_at = #{cancelledAt}, "
            + "cancelled_by = #{operator}, cancelled_reason = #{reason}, updated_at = NOW() "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'draft' AND deleted = 0")
    int markCancelled(@Param("id") String id,
                      @Param("tenantId") Long tenantId,
                      @Param("operator") String operator,
                      @Param("reason") String reason,
                      @Param("cancelledAt") OffsetDateTime cancelledAt);
}
