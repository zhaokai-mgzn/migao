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
 * 部位价目矩阵格的**计件单价**版本（issue #4587 ② = 母单 #4586 包A）
 * 对应表：{@code production_operation_position_price_versions}（V86）。
 *
 * <p><b>一行 = 一次真的变了的单价变更</b>（同价重复提交是幂等空操作，不记账）。挂载点是
 * {@code production_operation_positions.id}（矩阵格）—— 与 V55 的工序价账同范式，
 * 唯一差别是 {@code unitPrice} <b>可空</b>。</p>
 *
 * <p><b>{@code unitPrice = NULL} 的两种来路</b>（账本如实记 NULL，<b>不填 0</b>）：
 * ① 商家显式改回「<b>未定价</b>」；② 把该格设为「<b>明确不做</b>」⇒ 价被强制清空。
 * {@code 0} 是第三种语义（定价为 0 元），三态不得混。</p>
 *
 * <p><b>两本账不混</b>：本表记的是<b>付工人</b>的计件单价（报工工资 = 数量 × 计件单价）；
 * <b>对客</b>定价不在工序项 —— 基础加工费 = 加工项组合费用（元/米），特殊选项 =
 * {@code production_route_rules.customer_unit_price}（元/套，V77）。</p>
 *
 * <p>本类与 {@code ProductionOperationPositionCommandService} **从不读**那一列（上面只是文档里
 * 对照说明）—— 该纪律由 {@code tests/unit_ci_workflows/test_option_fee_seed.py} 的「两套账不互读」
 * 判据守着，它**只看代码**（扫描前做 Java 词法级去注释）⇒ 文档里写清列名是安全的
 * （issue #4595 修准了该判据；此前是裸子串扫描，会误判注释里的提及）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_operation_position_price_versions", autoResultMap = true)
public class ProductionOperationPositionPriceVersion {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 矩阵格 id（{@code production_operation_positions.id}） */
    private String positionRowId;

    /** 本次变更后的计件单价（元/单位）；{@code NULL} = 未定价 / 明确不做（**≠ 0 元**） */
    private BigDecimal unitPrice;

    private OffsetDateTime createdAt;

    private Integer deleted;
}
