package com.migao.admin.dto;

import lombok.Data;

/**
 * 入库单动作请求（V111，issue #5034）：{@code action: post | cancel}。
 *
 * <p>与加工单（{@code ProcessingOrderUpdateRequest}）同款形态：一个 PATCH 端点承载状态机动作，
 * 不为每个动作各开一个端点。</p>
 */
@Data
public class InboundOrderActionRequest {

    /** post（过账：加库存+生成批次号+算成本）/ cancel（作废，仅草稿） */
    private String action;

    /** 作废原因（cancel 时建议填；已过账不得作废） */
    private String reason;
}
