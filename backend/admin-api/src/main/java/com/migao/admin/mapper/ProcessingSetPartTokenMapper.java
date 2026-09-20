package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingSetPartToken;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.time.OffsetDateTime;

/**
 * 一部位一码 token Mapper（V92，切片 ⓪ / issue #4698）。
 * 切片 ① 只读（扫码解析的**第一优先**形态：新 token → 套 × 部位）；
 * 切片 ⓪.5（issue #4789）新增**唯一写方** {@link #insertIgnoreConflict} —— 此前全仓零写方
 * ⇒ 新码形态永远不出现（工人扫「部位码」无从谈起）。
 */
@Mapper
public interface ProcessingSetPartTokenMapper extends BaseMapper<ProcessingSetPartToken> {

    /**
     * 插入部位码，撞 `uk_set_part_tokens_part (tenant_id, set_id, order_item_id) WHERE deleted = 0`
     * 则**不插** ⇒ 同一部位重复打印**复用同一 token**（已打印的纸不作废，设计 §2.3）。
     *
     * <p>⚠️ `ON CONFLICT` 目标带**索引谓词**（部分唯一索引；PG 冲突推断要求谓词匹配 —— 本地 PG 16 实测）。</p>
     */
    @Insert("""
            INSERT INTO processing_set_part_tokens
                (id, tenant_id, processing_order_id, set_id, order_item_id, position_kind,
                 token, print_count, created_at, updated_at, deleted)
            VALUES (#{t.id}, #{t.tenantId}, #{t.processingOrderId}, #{t.setId}, #{t.orderItemId},
                    #{t.positionKind}, #{t.token}, 0, #{t.createdAt}, #{t.updatedAt}, #{t.deleted})
            ON CONFLICT (tenant_id, set_id, order_item_id) WHERE deleted = 0 DO NOTHING
            """)
    int insertIgnoreConflict(@Param("t") PartTokenRow t);

    /** 插入用的行（列清单显式，issue #4608 纪律）。 */
    record PartTokenRow(String id, Long tenantId, String processingOrderId, String setId,
                        String orderItemId, String positionKind, String token,
                        OffsetDateTime createdAt, OffsetDateTime updatedAt, Integer deleted) {
    }
}
