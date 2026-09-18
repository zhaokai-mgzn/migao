package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 工序计件单价版本（issue #4204，P1）
 * 对应表：production_operation_price_versions（V55）。
 *
 * <p>口径（真值源 docs/curtain-production-rules.md §2/§4）：**当前价 = 最新版本行**
 * （按 operation_id 取 created_at 最新的一行），与 {@code production_operations.unit_price}
 * 同事务维护。实例单价 {@code processing_position_operations.unit_price} 仍是**生成时的快照**：
 * 调价只影响新报工，历史报工按当时价，逐笔可追溯。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_operation_price_versions", autoResultMap = true)
public class ProductionOperationPriceVersion {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 工序库行 id（production_operations.id） */
    private String operationId;

    /** 本次变更后的计件单价（元/单位） */
    private BigDecimal unitPrice;

    private OffsetDateTime createdAt;

    private Integer deleted;
}
