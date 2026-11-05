package com.migao.admin.waybill;

import java.util.List;

/**
 * 轨迹查询结果（issue #8698；口径文档 §3-1「取号是主线，轨迹是副产品」）。
 *
 * <p>P0 没有任何 Java 侧轨迹实现（既有轨迹在
 * {@code backend/ai-agent-service/app/tools/logistics_track.py}，走阿里云市场 API）⇒
 * 今天调用必抛 {@link WaybillUnsupportedException}，本记录只定义**未来 provider 的返回形状**，
 * 不冒充「查过了没轨迹」。</p>
 *
 * @param trackingNo  运单号
 * @param carrierCode 承运商 code
 * @param segments    轨迹段（按时间正序；空列表 = 确实查过但没有轨迹）
 */
public record WaybillTrackResult(String trackingNo, String carrierCode, List<String> segments) {
}
