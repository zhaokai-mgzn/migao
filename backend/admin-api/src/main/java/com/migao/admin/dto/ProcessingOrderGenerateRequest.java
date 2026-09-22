package com.migao.admin.dto;

import lombok.Data;

import java.util.List;

/**
 * 生成加工单请求（issue #3340；派工指定批次 = V116 / issue #5145 阶段 1）。
 */
@Data
public class ProcessingOrderGenerateRequest {

    /** 订单 ID 或订单号列表（服务端解析） */
    private List<String> orderIds;

    /**
     * 派工指定批次（V116，issue #5145 阶段 1）：**逐面料行**指定「这行从哪一批裁」。
     *
     * <p>缺省 / 空列表 ⇒ **不指派**：不扣批次、不产生台账行，行为与今天逐字相同
     * （本阶段的定义特征是「只记录、不改指派行为」，见 {@code ProcessingOrderService#generate}）。</p>
     */
    private List<BatchAssignment> batches;

    /**
     * 批次指派规则（issue #5167）：{@code fifo}（**缺省**，入库日期早者优先）/ {@code best_fit}
     * （余量最接近需求者优先 —— 让批次被用尽）。
     *
     * <p>🔴 <b>缺省 = 今天的形态，一字不改</b>：不传它时，未指定 {@code batchNo} 的行仍然**显式拒绝**
     * （记录期的定义特征是「只记录、不改指派行为」⇒ 基线可比，见 {@code StockBatchConsumptionService}）。
     * 传了它（不论哪个值）才把「系统建议值」升级为「直接采用」：
     * 只对**没有**指定 {@code batchNo} 的行按该规则补位 —— 显式指定的行永远优先（人工最终选择 &gt; 规则）。</p>
     *
     * <p>未知取值 ⇒ <b>整批显式拒绝</b>（400，即使本次所有行都显式指定了批次）—— 静默回落 fifo =
     * 「商家以为开了 best-fit 却没开」，而账面上看不出没开。</p>
     */
    private String assignmentRule;

    /** 一行的批次指派（人工最终选择 —— 系统给候选 + 建议值，文员可改） */
    @Data
    public static class BatchAssignment {

        /** 订单 ID 或订单号（与 {@link #orderIds} 同形态；必须在本次生成范围内，否则显式拒绝） */
        private String orderId;

        /** 订单明细行 id（= 加工单快照行的 `itemId`） */
        private String itemId;

        /** 指定批次号 PC-yyyyMMdd-NNNN（服务端校验：同租户 / 同商品同 SKU / 余量足够） */
        private String batchNo;
    }
}
