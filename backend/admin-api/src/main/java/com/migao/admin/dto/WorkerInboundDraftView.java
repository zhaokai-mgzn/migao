package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Data;

import java.math.BigDecimal;
import java.util.List;

/**
 * 工人视角的入库单视图（issue #5052 P1）—— 建草稿与过账**共用同一个响应形状**。
 *
 * <p><b>为什么两个端点共用一个形状</b>：① 工人页面拿到的永远是同一套字段（不用记两种）；
 * ② 过账的幂等回放（{@code ClientRequestIdService.replay}）要按**一个确定的类型**反序列化快照 ——
 * 同一形状 + 端点标识进 {@code client_request_keys.endpoint} 做诊断，不必为「回放」再造第二个 DTO。</p>
 *
 * <p>{@link #source} 恒为 {@code purchase}（V117 的 {@code ck_inbound_orders_source} 只认
 * purchase / opening；工人拍照收货语义上就是采购收货）—— 工人面的请求体**没有** source 字段
 * ⇒ 这是**结构保证**，不是运行时校验。它作为响应字段回读，是为了让「来源不会被工人改掉」
 * 这件事在接口上**可见**。</p>
 *
 * <p>{@link #replayed} 由幂等实现（{@code ClientRequestIdService.replayedMarker}）在回放时置 true：
 * 不区分「首次执行」与「同键回放」时，一次手机重试会被读成「又入了一次库」。</p>
 */
@Data
@JsonInclude(JsonInclude.Include.NON_NULL)
public class WorkerInboundDraftView {

    /** 草稿 ID（入库单 UUID，过账时原样回传） */
    private String draftId;

    /** 入库单号 {@code RK-yyyyMMdd-NNNN} */
    private String inboundNo;

    /** {@code draft} / {@code posted} / {@code cancelled}（复用 {@code InboundOrder} 的既有取值） */
    private String status;

    /** 单据来源：本包恒 {@code purchase}（工人面结构上不可指定，见类注释） */
    private String source;

    /** true ⇒ 还需工人确认才能过账（草稿态恒 true；过账后 false） */
    private Boolean needsConfirmation;

    /** 明细行（一个 SKU 行 = 一个批次，裁定 1 / V111） */
    private List<Line> items;

    /** 同幂等键回放（true = 本次没有新落库；不区分首执与回放 = 观察性缺陷） */
    private Boolean replayed;

    /** 明细行（工人面只展示工人要核对的那几格） */
    @Data
    public static class Line {

        private Long skuId;

        /** 货号快照 */
        private String skuCode;

        /** 入库数量（米） */
        private BigDecimal quantity;

        /** 系统批次号 {@code PC-yyyyMMdd-NNNN}：草稿态为 null（过账才生成，V111 裁定） */
        private String batchNo;

        /**
         * 入库标签短码（issue #5052 P2）：**草稿态为 null**，过账后每行一个（8 位 Crockford Base32）。
         *
         * <p>P3 用它拼 {@code https://<稳定域名>/i/<短码>} 渲染 50×30mm 标签；
         * 域名由前端单一配置给（服务端不硬编码域名）。</p>
         */
        private String shortCode;

        /** 该标签**已打印次数**（服务端计数，重打同样计数；草稿态为 null）。 */
        private Integer printCount;
    }
}
