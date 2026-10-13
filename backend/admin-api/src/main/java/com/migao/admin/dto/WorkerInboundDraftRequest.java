package com.migao.admin.dto;

import lombok.Data;

import java.math.BigDecimal;

/**
 * 工人建入库单草稿请求（issue #5052 P1，设计 §5.2）。
 *
 * <p>一个入库单行 = 一个 SKU（裁定 1）⇒ 工人面**一次只建一行**；多行仍走商家侧
 * {@code POST /api/admin/inbound-orders}（本包不复制那条面的能力）。</p>
 *
 * <h3>🔴 结构上不可表达的三件事（设计 §5.3 硬约束 1）</h3>
 * <ul>
 *   <li><b>没有 {@code adjustment} / {@code delta} / {@code setStock}</b> —— 只表达「这一次收货收了多少米」，
 *       不存在「把库存改成 N」或「任意增减」的键；</li>
 *   <li><b>没有 {@code source} / {@code importRunId}</b> —— 来源由**服务端强制**为
 *       {@code photo}（issue #6812，V153 已放宽 {@code ck_inbound_orders_source}）；
 *       请求体里写 {@code source} 也**读不到**，且商家面那条 {@code normalizeSource} 仍只认
 *       purchase / opening ⇒ 客户端无法把一张单自称成「数量 = 卷数」的口径；</li>
 *   <li><b>没有 {@code operator} / {@code tenantId}</b> —— 身份只来自工人 session
 *       （{@code X-Worker-Session-Id}），租户来自 {@code TenantContext}；body 里的同名字段
 *       **连读取代码都没有**（同 {@code WorkerProductionController} 的既有纪律）。</li>
 * </ul>
 *
 * <p>数量准入不在本类，也**不**在工人侧另写一份：口径本体全仓唯一一处 =
 * {@code InboundOrderService.requireItemNumbers}（#5063 / #5153）＋ photo 单的
 * 卷数 / 卷长 / 米数三条判据（{@code requireRollCount} / {@code requireRollLength} /
 * {@code metersFor}，issue #6812）。</p>
 */
@Data
public class WorkerInboundDraftRequest {

    /** 商品 ID（必填；识别零命中时由工人从**既有**商品里选，系统不自动建品） */
    private String productId;

    /** SKU ID（必填；库存权威是 SKU 级，issue #4038） */
    private Long skuId;

    /**
     * **卷数**（issue #6812；工人端默认 1）：必须是**正整数**。
     *
     * <p>工人拍的是**一卷布** ⇒ 这一格记「几卷」；识别到的米数落在 {@link #rollLengthM}。
     * 入库米数 = 本值 × {@link #rollLengthM}（由 {@code InboundOrderService.metersFor} 一处换算，
     * 驱动库存 / 批次 / 台账 / 成本）。</p>
     */
    private BigDecimal quantity;

    /** 入库单价（可空；给了必须 {@code > 0} —— 不记单价请留空） */
    private BigDecimal unitCost;

    /** 供应商缸号（可空，外部事实） */
    private String dyeLot;

    /** 供应商（可空） */
    private String supplier;

    /** 送货单号（可空，外部事实）—— 入库标签第 5 行字段面（设计 §6 裁定记录） */
    private String supplierDocNo;

    /** 仓库/仓位（可空） */
    private String warehouse;

    /**
     * **每卷米数（卷长）**：photo 单**必填**（{@code > 0} 且最多 2 位小数 —— 列是
     * {@code roll_length_m NUMERIC(8,2)}），识别到的米数就填这里（issue #6812）。
     *
     * <p>入库米数 = {@code quantity} × 本值，且必须落在 0.1 米粒度上（否则显式拒绝）。</p>
     */
    private BigDecimal rollLengthM;

    /** 备注（可空） */
    private String remark;
}
