package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.InboundLabel;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;

/**
 * 入库标签 Mapper（issue #5052 <b>P2</b>，V134）—— 短码解析 / 打印计数 / 撤销的**唯一写面**。
 *
 * <h3>🔴 两条与 {@code ProcessingSetPartTokenMapper} 的异同（#5052 边界：「照其范式、不复用其表」）</h3>
 * <ul>
 *   <li><b>同</b>：跨租户短码解析走 {@link InterceptorIgnore}（{@code /i/{短码}} 是**公开入口**，
 *       没有租户上下文 ⇒ 多租户拦截器会抛 {@code Tenant context not initialized}）；
 *       短码全局唯一由部分唯一索引兜底；计数用 SQL 内自增（不是读出来 +1 再写回）。</li>
 *   <li><b>异</b>：<b>另一张表</b>。{@code /s/}（报工短链）与 {@code /i/}（入库标签）是两个码空间，
 *       混用会把「扫标签」变成「进报工页」⇒ 本 Mapper 只读写 {@code inbound_labels}，
 *       一行都不碰 {@code processing_set_part_tokens}（判据 = {@code InboundLabelSurfaceGuardTest}）。</li>
 * </ul>
 *
 * <h3>租户判据为什么不只靠拦截器</h3>
 * <p>解析（{@link #selectByCode}）必须跨租户（公开入口无上下文），而工人面的读 / 打 / 撤销
 * 必须**只**命中本租户 ⇒ 这半边由 ① 服务层的显式比对（不一致 ⇒ <b>404</b>，不是 403：
 * 避免存在性泄露）与 ② 这里 {@code AND tenant_id = #{tenantId}} 的 DB 谓词**两层**承担
 * —— 少一层都不会让状态码变化，但两层都在才叫「结构上不可越租户」。</p>
 */
@Mapper
public interface InboundLabelMapper extends BaseMapper<InboundLabel> {

    /** 显式列清单（issue #4608 纪律：不用 {@code SELECT *}）。 */
    String COLUMNS = "id, tenant_id, inbound_order_id, inbound_item_id, short_code, revoked_code, "
            + "print_count, created_by, revoked_at, revoked_by, created_at, updated_at, deleted";

    /**
     * 按**印刷码**取标签行（跨租户；活码与留档码都命中）。
     *
     * <p>不带 {@code short_code IS NOT NULL} 过滤：撤销 ⇒ 短码置 NULL（§7.3）⇒ 调用方必须能
     * 分辨「码不存在」（404）与「这张纸已作废」（410）；静默回落成 404 就是把撤销说成「没这个码」。</p>
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT " + COLUMNS + " FROM inbound_labels "
            + "WHERE (short_code = #{code} OR revoked_code = #{code}) AND deleted = 0")
    InboundLabel selectByCode(@Param("code") String code);

    /** 取某明细行的标签（一行至多一张：{@code uk_inbound_labels_item}）。 */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT " + COLUMNS + " FROM inbound_labels "
            + "WHERE tenant_id = #{tenantId} AND inbound_item_id = #{itemId} AND deleted = 0")
    InboundLabel selectByItem(@Param("tenantId") Long tenantId, @Param("itemId") Long itemId);

    /**
     * 插标签行，撞 {@code uk_inbound_labels_item (tenant_id, inbound_item_id) WHERE deleted = 0}
     * 则**不插** ⇒ 同一明细行重复请求**复用同一张纸 / 同一短码**（已打印的纸不作废）。
     *
     * <p>⚠️ {@code ON CONFLICT} 目标带**索引谓词**（部分唯一索引；PG 冲突推断要求谓词匹配 ——
     * 与 {@code ProcessingSetPartTokenMapper.insertIgnoreConflict} 同款）。</p>
     */
    @Insert("INSERT INTO inbound_labels (id, tenant_id, inbound_order_id, inbound_item_id, short_code, "
            + "print_count, created_by, created_at, updated_at, deleted) "
            + "VALUES (#{l.id}, #{l.tenantId}, #{l.inboundOrderId}, #{l.inboundItemId}, #{l.shortCode}, "
            + "0, #{l.createdBy}, #{l.createdAt}, #{l.updatedAt}, 0) "
            + "ON CONFLICT (tenant_id, inbound_item_id) WHERE deleted = 0 DO NOTHING")
    int insertIgnoreConflict(@Param("l") InboundLabel label);

    /**
     * 打印计数**原子自增**（§7.3 逐字口径：{@code COALESCE(print_count,0)+1}）。
     *
     * <p>SQL 内自增而不是「读出来 +1 再写回」：后者在并发下会丢计数（两个人同时打印
     * 从 3 各读到 3、各写回 4 ⇒ 实际打了两次而计数只 +1）。计数是**打印留痕的唯一来源**，
     * 丢了就等于「这次打印没发生」。</p>
     *
     * <p>🔴 {@code AND short_code IS NOT NULL} 是**第二道闸**：撤销后的标签在 DB 层就不再计数
     * （服务层在自增前已判 410 并拒；这一条让「并发撤销 vs 正在打印」的竞态也落在安全侧
     * —— 那种情况下自增影响 0 行，服务层据此 404，绝不回一个没落库的计数）。</p>
     *
     * @return 受影响行数（0 = 该行不存在 / 不属于本租户 / 已软删 / **已撤销**）
     */
    @InterceptorIgnore(tenantLine = "true")
    @Update("UPDATE inbound_labels SET print_count = COALESCE(print_count, 0) + 1, updated_at = NOW() "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 AND short_code IS NOT NULL")
    int incrementPrintCount(@Param("id") String id, @Param("tenantId") Long tenantId);

    /** 回读计数（**只能**在 {@link #incrementPrintCount} 之后调用：它就是「第几次」的那一格）。 */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT print_count FROM inbound_labels WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0")
    Integer selectPrintCount(@Param("id") String id, @Param("tenantId") Long tenantId);

    /**
     * 撤销：{@code short_code} 置 NULL + 原码留档 {@code revoked_code}（§7.3「撤销 ⇒ 短码置 NULL ⇒ 扫码 410」）。
     *
     * <p>🔴 三条红线（逐条落在 SQL 上）：① 只置这两列 + 撤销位 ⇒ **不碰** {@code print_count}
     * （打印历史是事实，不因作废而消失）；② {@code AND short_code IS NOT NULL} ⇒ 已撤销的行
     * **一字不动**（重复撤销不会把留档码冲掉）；③ {@code tenant_id} 谓词 ⇒ 不可越租户撤销。</p>
     *
     * @return 受影响行数（0 = 不存在 / 非本租户 / 已撤销 / 已软删）
     */
    @InterceptorIgnore(tenantLine = "true")
    @Update("UPDATE inbound_labels SET short_code = NULL, revoked_code = short_code, "
            + "revoked_at = #{revokedAt}, revoked_by = #{revokedBy}, updated_at = NOW() "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 AND short_code IS NOT NULL")
    int revoke(@Param("id") String id, @Param("tenantId") Long tenantId,
               @Param("revokedAt") OffsetDateTime revokedAt, @Param("revokedBy") String revokedBy);
}
