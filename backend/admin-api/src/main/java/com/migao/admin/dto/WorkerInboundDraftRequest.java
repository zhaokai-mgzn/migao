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
 *   <li><b>没有 {@code source} / {@code importRunId}</b> —— 来源由服务端固定为
 *       {@code purchase}（V117 的 {@code ck_inbound_orders_source} 只认 purchase / opening；
 *       工人拍照收货**语义上就是采购收货**）⇒ 工人**结构上**传不出第三取值，
 *       不需要一条迁移去放行新值；</li>
 *   <li><b>没有 {@code operator} / {@code tenantId}</b> —— 身份只来自工人 session
 *       （{@code X-Worker-Session-Id}），租户来自 {@code TenantContext}；body 里的同名字段
 *       **连读取代码都没有**（同 {@code WorkerProductionController} 的既有纪律）。</li>
 * </ul>
 *
 * <p>数量准入（{@code > 0} 且最多 1 位小数）不在本类，也**不**在工人侧另写一份：口径本体
 * 全仓唯一一处 = {@code InboundOrderService.requireItemNumbers}（#5063 / #5153）。</p>
 */
@Data
public class WorkerInboundDraftRequest {

    /** 商品 ID（必填；识别零命中时由工人从**既有**商品里选，系统不自动建品） */
    private String productId;

    /** SKU ID（必填；库存权威是 SKU 级，issue #4038） */
    private Long skuId;

    /** 入库数量（米）：{@code > 0} 且最多 1 位小数（#5063 的 0.1 米粒度；超 1 位小数显式拒绝、不静默取整） */
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

    /** 每卷米数（可空，仅记录/打印卷标） */
    private BigDecimal rollLengthM;

    /** 备注（可空） */
    private String remark;
}
