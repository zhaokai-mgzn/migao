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
