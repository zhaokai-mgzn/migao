package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 工艺路线版本账（V60，issue #4308）
 * 对应表：production_routing_versions（沿用 {@link ProductionOperationPriceVersion} 的版本账范式）。
 *
 * <p>路线是**计件工资**（Σ 报工数量 × 工序单价）与**完工判定**（必完工序全绿）的唯一输入
 * ⇒ 改序列必须留痕：追加一行，当前 = 最新版本行。工序实例的 seq/单价是**生成时快照**，
 * 改路线不回溯既有实例与历史报工。</p>
 *
 * <p>{@code operations} 是**变更后**的有序工序名序列；seq 不单独存 —— 它就是数组下标 + 1
 * （写面把序列归一化为 1..N）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_routing_versions", autoResultMap = true)
public class ProductionRoutingVersion {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 路线行 id（production_routings.id） */
    private String routingId;

    /** 冗余存的路线键（路线行被软删/改名后，历史账仍答得出「当时是哪条」） */
    private String curtainType;

    private String craft;

    /** 本次变更后的工序名有序序列（JSONB 数组） */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Object operations;

    /** 工序道数（报表/对账少解析一次 JSON） */
    private Integer operationCount;

    private OffsetDateTime createdAt;

    private Integer deleted;
}
