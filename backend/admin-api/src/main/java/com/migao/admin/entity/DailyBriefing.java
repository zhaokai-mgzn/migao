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
