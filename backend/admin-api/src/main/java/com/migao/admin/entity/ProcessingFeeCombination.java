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

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 加工费组合定价（V66，issue #4386，P1）
 * 对应表：processing_fee_combinations
 *
 * <p><b>口径（用户裁定 2026-09-19）</b>：「不是每个加工项收取一个费用，而且通常是组合」
 * 「选配完的一个商品**只会收取一种加工费**，然后根据米算出这个商品的加工费」
 * ⇒ 一行 = 一组选配特征（{@code 韩褶+打孔+定型}）→ **一个**加工费单价（元/米）。
 * 下单侧 = 按选配结果匹配组合 → 取价 → × 加工费米数 → **一个数**。</p>
 *
 * <p><b>{@code compositionKey} 是归一化后的选配特征集合</b>（确定性、与书写顺序无关，
 * 见 {@code ProcessingFeeCombinationCommandService#compositionKey}）——
 * 它是**取价的匹配键**，也是唯一键 {@code (tenant_id, composition_key) WHERE deleted = 0} 的一半。
 * 若按书写顺序存，同一笔钱会建出两行，取价取决于扫描顺序（不可复现的定价）。</p>
 *
 * <p><b>不是「穷举幂集」</b>：n 个特征有 2ⁿ 个子集，本表只维护**实际会卖**的组合；
 * 没维护到的组合由 {@code GET /production/processing-fee-gaps} 暴露为缺口（同 #4308 的处置）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "processing_fee_combinations", autoResultMap = true)
public class ProcessingFeeCombination {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 归一化后的选配特征集合（`+` 连接，如 `韩褶+打孔+定型`）—— 取价的匹配键 */
    private String compositionKey;

    /** 归一化后的特征名有序列表（与 composition_key 同源，展示用；不单独维护第二份口径） */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Object items;

    /** 加工费单价（**元/米**）：组合价 × 加工费米数 = 该商品这一个数 */
    private BigDecimal unitPrice;

    /** active / disabled（停用 = 保留行，不物理删：要能回答「昨天这个组合什么价」） */
    private String status;

    private Integer sortOrder;

    /** provenance 口径（与 {@code production_operations.source} 同词表）：实证 / 推算 / 占位待确认；NULL = 未知 */
    private String source;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
