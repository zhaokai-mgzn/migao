package com.migao.admin.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 事件携带的**结构化业务信息**（issue #7524）。
 *
 * <p>背景：改前 {@code triggerByEvent} 只把模板渲染成 {@code title + content} 两段文本
 * ⇒ 铃铛点不进单据、通知中心只能按已读态筛、同一事件重放会重复落库。</p>
 *
 * <p>本类只承载「与模板无关、由触发现场决定」的字段；模板变量仍走
 * {@code Map<String, String>}（既有契约不变，老调用方零改动）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class NotificationEvent {

    /** 业务对象类型：order / after_sales / inbound_order */
    private String bizType;

    /** 业务对象 ID（主键） */
    private String bizId;

    /** 业务对象单号（展示用；模板标题里也可用同名变量，此处是**不渲染**的原值） */
    private String bizNo;

    /** 前端落地页（含 query），空 = 不可跳转 */
    private String targetPath;

    /** info（默认）/ warn / urgent */
    private String severity;

    /** 业务发生时间；空 = 取当前时间 */
    private OffsetDateTime occurredAt;
}
