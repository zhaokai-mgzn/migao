package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 智能每日经营简报实体（issue #3468）
 * 对应表：daily_briefings
 *
 * content：LLM 生成的四区块简报（昨日回顾/今日必办/风险预警/优化建议），
 *          每条必办事项含 priority/reason/evidence/link，数字经回填校验；
 * source_snapshot：聚合 SQL 快照（指标 key → value），供校验层对账与证据链回溯；
 * 两者均不含客户 PII（脱敏红线，见 docs/design/daily-briefing-design.md §8）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "daily_briefings", autoResultMap = true)
public class DailyBriefing {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 简报归属日期（业务日期，Asia/Shanghai） */
    private LocalDate bizDate;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private Object content;

    @TableField(typeHandler = JacksonTypeHandler.class)
    private Object sourceSnapshot;

    /**
     * 逐规则接线状态（issue #5955）= ai-agent 引擎 `proactive_status(snapshot)` 的**原样**输出。
     *
     * <p>{@code {rule_id: {rule_id, rule_name, status, reason, missing, gaps, caveats}}}，
     * {@code status ∈ {wired, not_wired, not_enabled, incomplete}}；不变式 {@code reason == null} ⟺
     * {@code wired}。**确定性**计算，生成时从 ai-agent 生成返回体取出后原样落库 ——
     * 🔴 admin-api **不重算**（重算 = 引擎判据的第二份实现，见 {@code V144} 的理由段）。</p>
     *
     * <p>{@code null} = 未采集（本列面世前的存量行）⇒ 卡片面**不渲染**该面板：
     * **未知 ≠ 没问题**，也不许渲染成空壳冒充「已检查」。</p>
     */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Object proactiveStatus;

    /** pending / verified / partial / failed */
    private String verifyStatus;

    private OffsetDateTime generatedAt;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
