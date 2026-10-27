package com.migao.admin.dto;

import com.migao.admin.entity.PrintLog;
import lombok.Builder;
import lombok.Data;

import java.time.OffsetDateTime;

/**
 * 打印流水的一行（issue #7902）—— 订单详情页「打印流水」区读它：**谁 / 什么时候 / 打了哪种单据 / 几张**。
 *
 * <p>键名与落库列同名（camelCase），消费方（admin-web）按这些键渲染；
 * 快照字段（{@code orderNo} / {@code orderStatus} / {@code docTitle} / {@code operatorName}）
 * 是**打印当时**的值，不是现值 —— 单作废、人改名之后这一行仍然说得清。</p>
 *
 * <p>{@code userAgent} **不下发**（审计用，不是上屏信息；也避免把设备指纹铺到页面上）。</p>
 */
@Data
@Builder
public class PrintLogView {

    private String id;

    private String orderId;

    /** 订单号快照。 */
    private String orderNo;

    /** 单据类型：sales / processing / quotation / labels。 */
    private String docType;

    /** 打印当时的纸面名（加工单 / 面料单 / 水洗唛 / 销售单 / 报价单）。 */
    private String docTitle;

    private String processingOrderId;

    /** 加工单号快照（加工单 / 水洗唛那两张才有）。 */
    private String processingOrderNo;

    /** 纸型 id（a4 / continuous-241x140 / label-50x119）。 */
    private String mediaId;

    /** 这次出纸几张。 */
    private Integer sheets;

    /** browser 系统打印 / ble 蓝牙直连。 */
    private String channel;

    /** 一次联合打印的批号。 */
    private String batchId;

    /** 这一批里的第几条（0 起）。 */
    private Integer batchIndex;

    /** 这一批共几条。 */
    private Integer batchSize;

    /** 打印当时的订单状态快照（分清首打与发货后补打）。 */
    private String orderStatus;

    /** fired 已发起到打印 / failed 失败。 */
    private String status;

    private String failReason;

    private String operatorId;

    /** 姓名快照（改名/离职后历史仍可读）。 */
    private String operatorName;

    /** 来源 IP（审计面；网关后面可能是代理地址，见 {@code PrintLogService} 的说明）。 */
    private String clientIp;

    /** 发起打印的时刻（服务端时间）。 */
    private OffsetDateTime createdAt;

    /** 实体 → 读面（逐键搬运，不反射：加一个字段忘了搬 ⇒ 前端拿到 null 而没人知道）。 */
    public static PrintLogView from(PrintLog row) {
        return PrintLogView.builder()
                .id(row.getId())
                .orderId(row.getOrderId())
                .orderNo(row.getOrderNo())
                .docType(row.getDocType())
                .docTitle(row.getDocTitle())
                .processingOrderId(row.getProcessingOrderId())
                .processingOrderNo(row.getProcessingOrderNo())
                .mediaId(row.getMediaId())
                .sheets(row.getSheets())
                .channel(row.getChannel())
                .batchId(row.getBatchId())
                .batchIndex(row.getBatchIndex())
                .batchSize(row.getBatchSize())
                .orderStatus(row.getOrderStatus())
                .status(row.getStatus())
                .failReason(row.getFailReason())
                .operatorId(row.getOperatorId())
                .operatorName(row.getOperatorName())
                .clientIp(row.getClientIp())
                .createdAt(row.getCreatedAt())
                .build();
    }
}
