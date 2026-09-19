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
 * 具名工艺路线模板（V71，issue #4427 = 母单 #4423 P1/3；P2 / issue #4432 起有消费者）。
 * 对应表：{@code production_route_templates}。
 *
 * <p><b>与 {@link ProductionRouting}（旧 {@code production_routings}）的区别</b>：
 * 旧模型用 {@code (curtain_type, craft)} 当路线键 ⇒ 9 条「展开快照」，商家改一道工序要改 8 遍；
 * 新模型路线 = <b>一条具名主线</b>（{@code positions} 说明它适用哪些帘种）+ 规则表的变体规则。
 * <b>工艺不再参与选哪条路线</b>（它只触发 {@code production_route_rules}）。</p>
 *
 * <p><b>{@code mainline} 只存主线</b>（逻辑工序名，与 {@code OPERATION_LOGICAL_NAMES} 值域一致）：
 * 工艺变体（韩褶/打孔/穿杆/四爪钩）与特殊选项的增删由规则表决定，不展开进本列 ——
 * 这正是「9 条展开路线 → 1 条主线」的收敛点。「工艺槽位」不落库。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_route_templates", autoResultMap = true)
public class ProductionRouteTemplate {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 路线总名（用户可命名，如「窗帘工序路线（默认）」）；同租户活跃路线不得重名（M3：只改总名） */
    private String name;

    /** 默认路线标记（M4）：回落链的终点；每租户活跃路线中**恰好一条**（部分唯一索引保证 ≤1） */
    private Boolean isDefault;

    /** 适用帘种集合（JSONB 数组，取值域同 {@code production_operation_positions.position}） */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Object positions;

    /** 主线有序工序名（JSONB 数组，**逻辑工序名**） */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Object mainline;

    private String status;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
