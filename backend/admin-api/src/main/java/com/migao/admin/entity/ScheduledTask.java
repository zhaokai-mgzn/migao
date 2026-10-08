package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;
import java.util.Map;

/**
 * 定时任务（用户「预约」）—— 对应表 {@code scheduled_tasks}（V149，issue #6486 包 1）。
 *
 * <p><b>它回答什么</b>：本租户有哪些「到点要提醒」的待办、各自到点没有。</p>
 *
 * <p><b>与 {@code notifications} 的分工（别读混）</b>：本表是<b>待触发计划</b>（尚未发生，可取消）；
 * {@code notifications} 是<b>投递记录</b>（已发出的既成事实，不可撤回）。投递动作把前者变成后者。</p>
 *
 * <p>🔴 <b>三件套字段（{@code criterion} / {@code actionLabel} / {@code actionUrl}）在库里是 NOT NULL</b>
 * —— 这是把主动引擎「无处置入口不发」前移为「建单期不建」。本实体照实映射，不在 Java 侧放松。</p>
 */
@Data
@Builder(toBuilder = true)
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "scheduled_tasks", autoResultMap = true)
public class ScheduledTask {

    /** 任务类型（可配置，不写死行业语义）。 */
    public static final String SOURCE_USER = "user";
    public static final String SOURCE_SYSTEM = "system";

    /** 状态机取值。只有 {@link #STATUS_PENDING} 会被扫描器投递。 */
    public static final String STATUS_PENDING = "pending";
    public static final String STATUS_FIRED = "fired";
    public static final String STATUS_CANCELLED = "cancelled";
    public static final String STATUS_FAILED = "failed";
    public static final String STATUS_DISMISSED = "dismissed";

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String taskType;

    /** employee / customer / order；为空 = 无特定主体。 */
    private String subjectType;

    private String subjectId;

    /** 触发时刻。 */
    private OffsetDateTime fireAt;

    /** 为什么推给你（三件套之一，NOT NULL）。 */
    private String criterion;

    /** 影响面（几条 / 多少钱）；待办类可为空对象（三件套之二）。 */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> impact;

    /** 一键处置入口文案（三件套之三，NOT NULL）。 */
    private String actionLabel;

    /** 一键处置入口地址（三件套之三，NOT NULL）。 */
    private String actionUrl;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> payload;

    /** user（黄金策委托）/ system（规则派生）。 */
    private String source;

    /** pending / fired / cancelled / failed / dismissed。 */
    private String status;

    private String dedupKey;

    private OffsetDateTime firedAt;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
