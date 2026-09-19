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

    /** 路线行 id = {@code production_route_templates.id}（新结构「一条具名主线」）。
     *  <p>V60 时外键指向**已退役**的 {@code production_routings}；V85（issue #4581）起改指新表
     *  （带 {@code NOT VALID}：存量行可能引用旧表 id，新写入照旧强制）。</p> */
    private String routingId;

    /** 旧模型遗留的路线键一维（部位）：**只为历史行保留**，新模型没有这一维（工艺已降为
     *  {@code production_route_rules} 的触发键）⇒ 写面不传本列，新行恒为 NULL。
     *  <p>V60 时是 {@code NOT NULL}；V85（issue #4581）起放开 —— 旧形状下每行 INSERT 都被 PG 拒。</p> */
    private String curtainType;

    /** 旧模型遗留的路线键另一维（工艺）：同 {@link #curtainType}，只为历史行保留、新行恒为 NULL。 */
    private String craft;

    /** 本次变更后的工序名有序序列（JSONB 数组） */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Object operations;

    /** 工序道数（报表/对账少解析一次 JSON） */
    private Integer operationCount;

    private OffsetDateTime createdAt;

    private Integer deleted;
}
