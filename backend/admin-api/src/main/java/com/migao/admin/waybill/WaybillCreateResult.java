package com.migao.admin.waybill;

/**
 * 取号结果（issue #8698）。
 *
 * <p>⚠️ **只含运单信息，不含订单状态** —— 取号成功 ≠ 发货：订单仍「待发货」，
 * 由人点「确认发货」走既有 {@code ship} 端点（口径文档 §3-2，本单硬约束「现有 ship 端点一行不改」）。
 * 结果里刻意没有 {@code status} 字段：有它就会被"顺手"拿来当发货依据。</p>
 *
 * @param trackingNo  运单号
 * @param carrierCode 承运商 code
 * @param carrierName 承运商显示名
 */
public record WaybillCreateResult(String trackingNo, String carrierCode, String carrierName) {
}
