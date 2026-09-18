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
 * 加工费组合定价**版本账**（V66，issue #4386）
 * 对应表：processing_fee_combination_versions（与 {@link ProductionRoutingVersion}（#4308）**同构**）
 *
 * <p>加工费单价是**订单金额**的直接输入 ⇒ 改一次价必须留痕，「这个组合昨天什么价」要答得出。
 * 每次**真实变更**追加一行（同值重复提交是幂等空操作 —— 否则账本被无意义的重复行淹没）；
 * 当前价 = 最新版本行。</p>
 *
 * <p>{@code compositionKey} 冗余存：组合行被停用/改名后，历史账仍答得出「当时是哪一组」。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "processing_fee_combination_versions")
public class ProcessingFeeCombinationVersion {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 组合行 id（processing_fee_combinations.id） */
    private String combinationId;

    /** 冗余存的归一化组合键（组合行被停用/改名后，历史账仍答得出「当时是哪一组」） */
    private String compositionKey;

    /** 本次变更后的单价（元/米） */
    private BigDecimal unitPrice;

    /** 本次变更后的状态（active / disabled） */
    private String status;

    private OffsetDateTime createdAt;

    private Integer deleted;
}
