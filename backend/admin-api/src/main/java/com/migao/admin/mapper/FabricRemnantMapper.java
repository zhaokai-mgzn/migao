package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.FabricRemnant;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.math.BigDecimal;
import java.util.List;
import java.time.OffsetDateTime;

/**
 * 余料台账 Mapper（V122，issue #5146）。
 *
 * <p>写入一律走 {@code RemnantService}（它保证「状态 ↔ 留痕列」自洽、且回收绝不写批次消耗台账）；
 * 本接口只加一条**匹配候选**查询 —— 匹配要的排序（同缸号优先 → 同色优先 → 尺寸最小者优先）
 * 放在 SQL 里而不是 Java 里，是为了「一个查询定序」而不是「查回来再拼一遍顺序」。</p>
 *
 * <p>回收 / 报废两条状态迁移走**条件更新（CAS）**（issue #6960）：与
 * {@code InboundOrderMapper#markPosted} / {@code #markCancelled}（#6928）同款 ——
 * 「读 status 判 {@code available}」与「写」必须压进**同一条语句**。改前两处都是
 * 「先读 status 判 available、再 {@code updateById}（WHERE 仅主键 ⇒ 无谓词）」⇒ 两个并发 recover
 * 都能读到 {@code available} 并各写一次回收额（**重复记回收额**、且无任何 4xx）。
 * 谓词里的列逐一自证在场（{@code fabric_remnants} 的 DDL 见 {@code db/init/schema.sql}）：
 * {@code id} 主键 / {@code tenant_id} / {@code status} / {@code deleted}（本表**有**软删列，已核对）。</p>
 */
@Mapper
public interface FabricRemnantMapper extends BaseMapper<FabricRemnant> {

    /**
     * 匹配候选（**只扫可用池** —— {@code status = 'available'}）。
     *
     * <p>谓词分三层，各有判据：</p>
     * <ol>
     *   <li>{@code status = 'available'} ⇒ <b>客户带走的余料天然不在候选里</b>
     *       （判据 7：它不进池、不参与匹配、不计回收 —— 红证 = 把它混进池则匹配命中）；</li>
     *   <li>{@code length_m >= need} 且 {@code width_m >= need} ⇒ <b>尺寸不足者不出现在候选里</b>
     *       （判据 5「不凭空推荐」的第一道网；第二道在 Java 里用
     *       {@code RemnantItemSize#fits} 复核 —— SQL 与实体两处判据一致，防「查询写宽了」）；</li>
     *   <li>同商品（{@code product_id}）⇒ 不同商品的余料不可能互相替代。</li>
     * </ol>
     *
     * <p>排序（判据 3「同缸号、同色优先，防色差」的落点）：</p>
     * <ol>
     *   <li>{@code 同缸号} 优先（{@code dye_lot} 相等；缸号为空的行永不排前）；</li>
     *   <li>其次 {@code 同色}（{@code sku_code} 相等）；</li>
     *   <li>再按 {@code length_m} **升序** —— 先用掉小块的（best-fit 精神：余料越小越接近废料，
     *       大块留给大件）；平局按 {@code id} 升序保证**确定性**。</li>
     * </ol>
     *
     * <p>⚠️ 排序里的 {@code CASE WHEN} 而不是 {@code (dye_lot = ?) DESC}：PG 的
     * {@code NULL = x} 得 NULL，而 {@code ORDER BY … DESC} 默认 {@code NULLS FIRST}
     * ⇒ 缸号为空的行会被排到最前面（正好把「优先」颠倒）。这是写法上的坑，不是口味问题。</p>
     *
     * <p>硬底线（{@code 同缸号 或 同色}，不同色直接淘汰）**有意放在 Java 里** ——
     * 它是业务判定（防色差的底线）而不是取数范围，放服务层才能被单测逐值判红，
     * 也才能与「返回给用户的淘汰原因」用同一份真值。</p>
     */
    @org.apache.ibatis.annotations.Select(
            "SELECT * FROM fabric_remnants "
                    + "WHERE tenant_id = #{tenantId} AND deleted = 0 AND status = 'available' "
                    + "AND product_id = #{productId} "
                    + "AND length_m >= #{needLengthM} AND width_m >= #{needWidthM} "
                    + "ORDER BY CASE WHEN dye_lot IS NOT NULL AND dye_lot = #{dyeLot} THEN 0 ELSE 1 END, "
                    + "CASE WHEN sku_code IS NOT NULL AND sku_code = #{skuCode} THEN 0 ELSE 1 END, "
                    + "length_m ASC, id ASC")
    java.util.List<FabricRemnant> findMatchCandidates(
            @org.apache.ibatis.annotations.Param("tenantId") Long tenantId,
            @org.apache.ibatis.annotations.Param("productId") String productId,
            @org.apache.ibatis.annotations.Param("dyeLot") String dyeLot,
            @org.apache.ibatis.annotations.Param("skuCode") String skuCode,
            @org.apache.ibatis.annotations.Param("needLengthM") java.math.BigDecimal needLengthM,
            @org.apache.ibatis.annotations.Param("needWidthM") java.math.BigDecimal needWidthM);

    /**
     * 回收权 = DB 原子条件更新（CAS，issue #6960 本单新增）。
     *
     * <p>{@code recovered_*} 五列与状态**同一句**写入：「这块余料被谁用掉、冲减多少」不能与状态迁移
     * 分成两次写（中间态可以读出「已用但回收额为 NULL」，而 DB 的
     * {@code ck_fabric_remnant_lifecycle} 会直接拒绝这种行）。</p>
     *
     * <p>谓词带 {@code status = 'available'}：两个并发 recover 只有先到者命中行
     * （后到者阻塞到先到者提交后按新版本行重估 ⇒ 影响行数 0）⇒ 回收额**恰入账一次**。
     * 谓词带 {@code deleted = 0}：MyBatis-Plus 的 {@code @TableLogic} 只对自动生成的 SQL 生效，
     * 手写 SQL 必须自己带上（软删的余料不得回收）。</p>
     *
     * @return 影响行数：{@code 1} = 本请求抢到回收权；{@code 0} = 已被回收 / 已报废 / 已客户带走 / 行不存在
     */
    @Update("UPDATE fabric_remnants SET status = 'used', used_by_order_no = #{orderNo}, "
            + "used_by_order_item_id = #{orderItemId}, used_by_item_key = #{itemKey}, "
            + "recovered_meters = #{meters}, recovered_unit_cost = #{unitCost}, "
            + "recovered_amount = #{amount}, recovered_at = #{recoveredAt}, recovered_by = #{operator} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'available' AND deleted = 0")
    int markRecovered(@Param("id") Long id,
                      @Param("tenantId") Long tenantId,
                      @Param("orderNo") String orderNo,
                      @Param("orderItemId") String orderItemId,
                      @Param("itemKey") String itemKey,
                      @Param("meters") BigDecimal meters,
                      @Param("unitCost") BigDecimal unitCost,
                      @Param("amount") BigDecimal amount,
                      @Param("recoveredAt") OffsetDateTime recoveredAt,
                      @Param("operator") String operator);

    /**
     * 报废权 = **与 {@link #markRecovered} 同款**的 DB 原子条件更新（CAS，issue #6960 本单新增）。
     *
     * <p>两者争的是**同一份状态迁移权**（同一行的 {@code available} 只能被消耗一次）⇒ 一个写面有 CAS、
     * 另一个没有就**不互斥**（并发「回收 × 报废」会双双 200 而终态只有一个）。报废留痕三列与状态
     * **同一句**写入：{@code ck_fabric_remnant_lifecycle} 要求 {@code status='scrapped'} 时三列非空、
     * 且回收四列必须为 NULL（与回收互斥）。</p>
     *
     * @return 影响行数：{@code 1} = 本请求抢到报废权；{@code 0} = 已被回收 / 已报废 / 已客户带走 / 行不存在
     */
    @Update("UPDATE fabric_remnants SET status = 'scrapped', scrap_reason = #{reason}, "
            + "scrapped_at = #{scrappedAt}, scrapped_by = #{operator} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'available' AND deleted = 0")
    int markScrapped(@Param("id") Long id,
                     @Param("tenantId") Long tenantId,
                     @Param("reason") String reason,
                     @Param("scrappedAt") OffsetDateTime scrappedAt,
                     @Param("operator") String operator);

    /**
     * 余料台账**按状态**聚合（issue #7408）：`RemnantService#summary` 的 SQL 下推面。
     *
     * <p>改前是 {@code selectList(tenant_id = ?)} 把本租户**全部余料行**读进 JVM 再 switch 累加 ——
     * 每次打开余料台账页（列表 + 汇总一次回）都要走一遍，成本随租户历史线性增长。
     * 下推后响应行数 = 状态数（≤4），且 {@code fabric_remnants (tenant_id, status, id)} 这条索引正好可用。</p>
     *
     * <p>口径**逐项不变**：米数求和把 NULL 当 0（{@code SUM} 本来就跳过 NULL）；未知/空状态
     * 由调用方忽略（与改前 {@code default -> {}} 一致）。</p>
     */
    @Select("SELECT status, COUNT(*) AS cnt, "
            + "COALESCE(SUM(length_m), 0) AS meters, "
            + "COALESCE(SUM(recovered_amount), 0) AS recovered_amount "
            + "FROM fabric_remnants "
            + "WHERE tenant_id = #{tenantId} AND deleted = 0 "
            + "GROUP BY status")
    List<RemnantStatusSum> sumByStatus(@Param("tenantId") Long tenantId);

    /** {@link #sumByStatus} 的一行（status 维度）。 */
    @lombok.Data
    class RemnantStatusSum {
        private String status;
        private Long cnt;
        private BigDecimal meters;
        private BigDecimal recoveredAmount;
    }
}
