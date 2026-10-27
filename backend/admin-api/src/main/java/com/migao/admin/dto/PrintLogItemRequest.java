package com.migao.admin.dto;

import lombok.Data;

/**
 * 一条打印记录（issue #7902）：客户端在**发起打印时**递交的那部分事实。
 *
 * <p>字段口径与落库列一一对应（见 {@code entity/PrintLog}）；空值语义：</p>
 * <ul>
 *   <li>{@code sheets} 缺省 = 1（不是 0，也不是「按需」）；</li>
 *   <li>{@code channel} 缺省 = {@code browser}；{@code status} 缺省 = {@code fired}；</li>
 *   <li>{@code docTitle} / {@code mediaId} / {@code processingOrderId} / {@code failReason} 可空 ——
 *       缺了不猜（尤其是 {@code failReason}：失败但没说原因 ≠ 编一个原因）。</li>
 * </ul>
 */
@Data
public class PrintLogItemRequest {

    /** 单据类型（封闭集合 sales / processing / quotation / labels；服务端白名单校验）。 */
    private String docType;

    /** 打印当时的纸面名（「加工单」/「面料单」/「水洗唛」/「销售单」/「报价单」），≤ 32 字符。 */
    private String docTitle;

    /** 加工单 / 洗水唛所属的加工单（可空；服务端据此补 {@code processingOrderNo} 快照）。 */
    private String processingOrderId;

    /** 纸型 id（a4 / continuous-241x140 / label-50x119），≤ 32 字符。 */
    private String mediaId;

    /** 这次出纸几张（1~999；缺省 1）。 */
    private Integer sheets;

    /** 打印通道（browser / ble；缺省 browser）。 */
    private String channel;

    /** 打印结果（fired / failed；缺省 fired）。 */
    private String status;

    /** 失败原因（status=failed 时建议填写；≤ 255 字符）。 */
    private String failReason;
}
