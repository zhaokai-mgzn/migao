package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingSetPartToken;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.time.OffsetDateTime;

/**
 * 一部位一码 token Mapper（V92，切片 ⓪ / issue #4698）。
 * 切片 ① 只读（扫码解析的**第一优先**形态：新 token → 套 × 部位）；
 * 切片 ⓪.5（issue #4789）新增**唯一写方** {@link #insertIgnoreConflict} —— 此前全仓零写方
 * ⇒ 新码形态永远不出现（工人扫「部位码」无从谈起）。
 * 稳定短链切片（issue #4802 / V99）新增 `short_code` 写列 + **跨租户**短码查询
 * {@link #selectByShortCode}（`/s/{短码}` 是公开入口，无租户上下文）。
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
}
