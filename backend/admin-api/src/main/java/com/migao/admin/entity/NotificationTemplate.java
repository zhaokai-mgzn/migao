package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 通知模板实体类
 * 对应表：notification_templates
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("notification_templates")
public class NotificationTemplate {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String name;

    /**
     * 标题模板（issue #7524，可空）。
     *
     * <p>改前标题恒等于 {@link #name}（如「新订单通知」）⇒ 铃铛里看不到单号，必须点开才知道是哪一单。
     * 本列支持变量（如「入库单 {{inboundNo}} 已过账」）；为空时回落到 {@code name}（老模板零改动）。</p>
     */
    private String titleTemplate;

    /** ticket_assigned / ticket_status_changed / refund_success / shipment / etc. */
    private String type;

    /** wechat / sms / email / internal */
    private String channel;

    private String templateContent;

    /** 可用变量列表（JSONB） */
    private String variables;

    /** active / inactive */
    private String status;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;
}
