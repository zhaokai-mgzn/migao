package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;

/**
 * 工人端**批次库存修正**请求（issue #8104）。
 *
 * <p>形态 = 工人在手机上选中一个批次、填实盘米数、选原因，然后一次提交。
 * 服务端把它改写成一次**按批次盘点**（复用 {@code BatchStocktakeService#stocktake} 这个
 * 唯一写面：批次分录 + SKU 库存同一事务对齐），因此这里**没有** {@code delta} / {@code adjustment}
 * 这类「服务端替调用方算差异」的字段 —— 差异只由「实盘米数 − 当刻余量」算出（唯一算法）。</p>
 *
 * <h3>两条纪律</h3>
 * <ul>
 *   <li>🔴 <b>字段集 = 能力集</b>：只有批次 / 实盘米数 / 原因 / 备注 / 幂等键 ——
 *       <b>没有</b> {@code workerId} / {@code workerName} / {@code tenantId}
 *       （身份由 {@code X-Worker-Session-Id} 解、租户由会话上下文定）；结构上不存在 = 想冒名的人改前端也没用。</li>
 *   <li><b>键形 = camelCase</b>：与工人端其它<b>写面</b>同口径（{@code WorkerShipmentController} 的
 *       {@code trackingNo} / {@code logisticsType}）。工人端<b>读面</b>才是 snake_case
 *       （且用 {@code Map} 拼，见 {@code WorkerBatchStockService}）—— 全仓**唯一**的冻结键手段是
 *       {@code @JsonProperty}，工人读面刻意不走它（类级守卫
 *       {@code tests/unit_ci_workflows/test_read_face_json_key_guard.py}）。</li>
 * </ul>
 *
 * <p>🔴 {@code clientRequestId} 是**幂等键**（由端侧生成、重试复用）：同一次提交的网络重试 /
 * 连点必须带同一个值；换一个新值就是**新的一次修正**（幂等只覆盖重复请求，不覆盖两次真实修正）。
 * 服务端把它拼成盘点运行标识 {@code wc-<clientRequestId>}，于是唯一索引
 * {@code uk_batch_consumption_stocktake} 在库层兜住「第二遍」。</p>
 */
@Data
public class WorkerBatchCorrectionRequest {

    /** 批次主键（来自 {@code GET /api/worker/batch-stock/batches} 的行；不接受批次号字符串 —— 两个批次同号时没法判） */
    private Long batchId;

    /** 实盘米数（米，最多 1 位小数；负数 / 超精度 ⇒ 显式拒绝，服务端不做静默取整） */
    private BigDecimal actualMeters;

    /** 修正原因（闭词表：{@code WorkerBatchStockService.REASONS} 的 code；未知值 ⇒ 422 并列可选值） */
    private String reason;

    /** 备注（可选，≤60 字；只进台账 note，不参与判定） */
    private String note;

    /**
     * 幂等键（端侧生成，≤48 字符，仅字母 / 数字 / 连字符）。
     *
     * <p>拼成 {@code wc-<clientRequestId>} 后仍 ≤64（列宽 {@code VARCHAR(64)}）⇒ 超长在这里就拒，
     * 不让它变成一个「写库时才炸」的 500。</p>
     */
    private String clientRequestId;
}
