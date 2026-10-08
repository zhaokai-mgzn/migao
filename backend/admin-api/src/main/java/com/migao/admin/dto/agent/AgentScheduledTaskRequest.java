package com.migao.admin.dto.agent;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.time.OffsetDateTime;
import java.util.Map;

/**
 * 创建一条定时任务（待办）的请求（issue #6486 包 1）。
 *
 * <p>🔴 <b>三件套必填且 {@code @NotBlank}</b>（{@code criterion} / {@code actionLabel} / {@code actionUrl}）
 * —— 这是主动引擎「**没有处置入口的不发**」在建单期的落点：字段级校验先拦一道，
 * 库里对应的列还是 {@code NOT NULL}（双保险，见 V149 迁移）。</p>
 *
 * <p><b>收件人不在本请求里</b>：由 controller 从认证上下文取（= 「给自己设提醒」）。
 * 这样 body 伪造不了收件人 —— 与 {@code AgentBatchController} 的
 * 「身份一律取自认证上下文，body 伪造不了」同款。</p>
 */
@Data
public class AgentScheduledTaskRequest {

    /** 任务类型（可配置，不写死行业语义）。 */
    @NotBlank(message = "任务类型不能为空")
    private String taskType;

    /** 触发时刻。 */
    @NotNull(message = "触发时刻不能为空")
    private OffsetDateTime fireAt;

    /** 为什么推给你（三件套之一）。 */
    @NotBlank(message = "判据（criterion）不能为空 —— 无判据的提醒等于制造焦虑")
    private String criterion;

    /** 一键处置入口文案（三件套之三）。 */
    @NotBlank(message = "处置入口文案（actionLabel）不能为空 —— 没有处置入口的提醒不发")
    private String actionLabel;

    /** 一键处置入口地址（三件套之三）。 */
    @NotBlank(message = "处置入口地址（actionUrl）不能为空 —— 没有处置入口的提醒不发")
    private String actionUrl;

    /** 影响面（可选；缺省落空对象）。 */
    private Map<String, Object> impact;

    /** 附加上下文（可选）。 */
    private Map<String, Object> payload;

    /** 关联主体类型（可选）：customer / order … */
    private String subjectType;

    /** 关联主体 ID（可选）。 */
    private String subjectId;

    /**
     * 幂等键（可选）：为空时由服务端按「收件人 + 类型 + 触发时刻」派生。
     * 同一租户同一键**只建一条**（见 {@code uk_scheduled_tasks_tenant_dedup}）。
     */
    private String dedupKey;
}
