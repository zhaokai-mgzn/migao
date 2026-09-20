package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingSetPartToken;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;

/**
 * 一部位一码 token Mapper（V92，切片 ⓪ / issue #4698）。
 * 切片 ① 只读（扫码解析的**第一优先**形态：新 token → 套 × 部位）；
 * 切片 ⓪.5（issue #4789）新增**唯一写方** {@link #insertIgnoreConflict} —— 此前全仓零写方
 * ⇒ 新码形态永远不出现（工人扫「部位码」无从谈起）。
 * 稳定短链切片（issue #4802 / V99）新增 `short_code` 写列 + **跨租户**短码查询
 * {@link #selectByShortCode}（`/s/{短码}` 是公开入口，无租户上下文）。
 * 撤销 / 重新发码（issue #4946 增补）新增两个写方：{@link #revokeTokensByOrder}
 * （与加工单级 `qr_token` **同事务**作废印刷品载体）+ {@link #fillMissingToken}
 * （撤销后只补 `token IS NULL` 的行 ⇒ 数据层可恢复）。
 */
@Mapper
public interface ProcessingSetPartTokenMapper extends BaseMapper<ProcessingSetPartToken> {

    /**
     * 插入部位码，撞 `uk_set_part_tokens_part (tenant_id, set_id, order_item_id) WHERE deleted = 0`
     * 则**不插** ⇒ 同一部位重复打印**复用同一 token**（已打印的纸不作废，设计 §2.3）。
     *
     * <p>⚠️ `ON CONFLICT` 目标带**索引谓词**（部分唯一索引；PG 冲突推断要求谓词匹配 —— 本地 PG 16 实测）。</p>
     *
     * <p>{@code short_code}（V99 / issue #4802）与 {@code token} **同一次插入**写入 ⇒
     * 「同一行的两种表示」；冲突时不插 ⇒ 重复实例化**复用同一短码**（幂等，不换码）。</p>
     */
    @Insert("""
            INSERT INTO processing_set_part_tokens
                (id, tenant_id, processing_order_id, set_id, order_item_id, position_kind,
                 token, short_code, print_count, created_at, updated_at, deleted)
            VALUES (#{t.id}, #{t.tenantId}, #{t.processingOrderId}, #{t.setId}, #{t.orderItemId},
                    #{t.positionKind}, #{t.token}, #{t.shortCode}, 0,
                    #{t.createdAt}, #{t.updatedAt}, #{t.deleted})
            ON CONFLICT (tenant_id, set_id, order_item_id) WHERE deleted = 0 DO NOTHING
            """)
    int insertIgnoreConflict(@Param("t") PartTokenRow t);

    /**
     * 给**已存在**的码行补短码（存量单补码，issue #4865）：**只补 {@code short_code IS NULL} 的行**。
     *
     * <p><b>为什么需要它</b>：{@link #insertIgnoreConflict} 走 {@code ON CONFLICT DO NOTHING}
     * ⇒ 行已存在时**整行不碰**（这是「已打印的纸不作废」的实现）—— 但 V99 的注释预告了另一形态：
     * 「本次之前已写入的 token 行保持 NULL」（有 token、无短码）。那种行既不会被插入、
     * 也不会被 DO NOTHING 修好 ⇒ 必须有一条**只补该列**的路径，否则「要印的行必须有 short_code」不成立。</p>
     *
     * <p>🔴 三条红线（逐条落在 SQL 上）：① {@code AND short_code IS NULL} ⇒ **已有短码的行一字不动**；
     * ② 只写 {@code short_code} + {@code updated_at} ⇒ **不碰 token**（码不换）**不碰任何单价/计件列**（不追溯）；
     * ③ {@code deleted = 0} ⇒ 不动软删行。</p>
     *
     * @return 受影响行数（0 = 该行不存在 / 已有短码 / 已软删 ⇒ 调用方无需重试）
     */
    @Update("""
            UPDATE processing_set_part_tokens
               SET short_code = #{shortCode}, updated_at = #{updatedAt}
             WHERE tenant_id = #{tenantId} AND set_id = #{setId} AND order_item_id = #{orderItemId}
               AND deleted = 0 AND short_code IS NULL
            """)
    int fillMissingShortCode(@Param("tenantId") Long tenantId, @Param("setId") String setId,
                             @Param("orderItemId") String orderItemId,
                             @Param("shortCode") String shortCode,
                             @Param("updatedAt") OffsetDateTime updatedAt);

    /**
     * 按短码取承载行（稳定短链 {@code GET /s/{shortCode}} 的唯一读面，issue #4802 / V99）。
     *
     * <p>🔴 {@code @InterceptorIgnore(tenantLine = "true")} 是**必须的**（不是优化）：
     * `/s/{短码}` 是公开入口（无 JWT / 无工人 session）⇒ `TenantContext` 为空 ⇒
     * 多租户拦截器会抛 `Tenant context not initialized` ⇒ 短链恒 500。
     * 短码本身**全局唯一**（部分唯一索引 `uk_set_part_tokens_short_code`）⇒ 跨租户查询最多命中一行，
     * 租户由短码解出（设计 C12）。同款手法见 `UserMapper` 的跨租户手机号查询。</p>
     *
     * <p>**不带** `token IS NOT NULL` 过滤：撤销 = 置 NULL（设计 §1.3.1）⇒ 调用方要能区分
     * 「短码不存在」（404）与「这张纸已作废」（410），静默回落成 404 会把撤销说成「没这个码」。</p>
     *
     * @param shortCode 归一化后的短码（8 位 Crockford Base32）
     * @return 命中行；未知 ⇒ {@code null}
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("""
            SELECT id, tenant_id, processing_order_id, set_id, order_item_id, position_kind,
                   token, short_code, deleted
            FROM processing_set_part_tokens
            WHERE short_code = #{shortCode} AND deleted = 0
            """)
    ProcessingSetPartToken selectByShortCode(@Param("shortCode") String shortCode);

    /** 插入用的行（列清单显式，issue #4608 纪律）。 */
    record PartTokenRow(String id, Long tenantId, String processingOrderId, String setId,
                        String orderItemId, String positionKind, String token, String shortCode,
                        OffsetDateTime createdAt, OffsetDateTime updatedAt, Integer deleted) {
    }

    /**
     * 撤销某加工单的**全部部位码**（issue #4946 增补）：置 {@code token = NULL}。
     *
     * <p><b>为什么必须与 {@code processing_orders.qr_token} 一起撤销</b>：印刷品承载的已经是
     * **一部位一码**（本表）—— 只撤销加工单级 {@code qr_token} ⇒ 界面说「已打印的旧码立即失效」
     * 而每个部位码仍然可用，**这是一句假话**（正是本仓最忌讳的形态）。故两者在**同一个事务**里作废。</p>
     *
     * <p>🔴 三条红线：① 只置 {@code token}（+ {@code updated_at}）⇒ <b>不碰 {@code short_code}</b>
     * —— 短码是「哪一张纸」，留着它这张纸仍可辨识，且 {@code GET /s/{短码}} 见 token 为空 ⇒
     * **410 Gone**（设计 §1.3.1 逐字）；② 语义与既有 {@code ProcessingOrderMapper.revokeQrToken}
     * 逐字同款：**撤销 = 这张纸作废，不换新 token**；③ {@code deleted = 0} ⇒ 不动软删行。</p>
     *
     * @return 受影响行数（该单没有部位码 / 全部已撤销 ⇒ 0，调用方无需重试）
     */
    @Update("""
            UPDATE processing_set_part_tokens
               SET token = NULL, updated_at = #{updatedAt}
             WHERE processing_order_id = #{processingOrderId} AND tenant_id = #{tenantId}
               AND deleted = 0
            """)
    int revokeTokensByOrder(@Param("processingOrderId") String processingOrderId,
                            @Param("tenantId") Long tenantId,
                            @Param("updatedAt") OffsetDateTime updatedAt);

    /**
     * 给**已撤销**（{@code token IS NULL}）的码行重新发码（issue #4946 增补）。
     *
     * <p><b>为什么需要它</b>：{@link #insertIgnoreConflict} 走 {@code ON CONFLICT DO NOTHING}
     * ⇒ 被 {@link #revokeTokensByOrder} 置空过的行**永远拿不回 token**（既不会被插入、也不会被修好）
     * ⇒ 撤销一次，这张单再也印不出码。语义与 {@code ProductionService.ensureQrToken} **逐字同款**：
     * 复用已有 token，**只在缺失时**生成新的。</p>
     *
     * <p>🔴 三条红线（逐条落在 SQL 上）：① {@code AND token IS NULL} ⇒ 已有 token 的行**一字不动**
     * （已打印的纸不作废）；② 只写 {@code token} + {@code updated_at} ⇒ <b>不碰 {@code short_code}</b>
     * （短码是「哪一张纸」，换它会让人觉得换了张纸）、也不碰任何单价/计件列；③ {@code deleted = 0}。</p>
     *
     * @return 受影响行数（0 = 该行不存在 / 已有 token / 已软删 ⇒ 调用方无需重试）
     */
    @Update("""
            UPDATE processing_set_part_tokens
               SET token = #{token}, updated_at = #{updatedAt}
             WHERE tenant_id = #{tenantId} AND set_id = #{setId} AND order_item_id = #{orderItemId}
               AND deleted = 0 AND token IS NULL
            """)
    int fillMissingToken(@Param("tenantId") Long tenantId, @Param("setId") String setId,
                         @Param("orderItemId") String orderItemId, @Param("token") String token,
                         @Param("updatedAt") OffsetDateTime updatedAt);
}
