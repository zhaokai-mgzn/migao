package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.time.OffsetDateTime;

/**
 * 决策采纳记录（issue #8260）—— 对应表 {@code briefing_actions}。
 *
 * <p>它要回答的问题只有一句：<b>「AI 建议了什么 → 人做了什么」能不能证明？</b>
 * 复盘（#8253）只给了历史原文，说不出后半句；这张表补的就是后半句。</p>
 *
 * <p><b>只记 hash，不记原文</b>：{@code itemKey} = 条目标题的 SHA-256 前 16 位。
 * 简报 {@code content} 里是字符串数组、没有稳定 id；按标题取 hash 既不依赖顺序，
 * 也不会因 LLM 换个说法被当成同一条（换个说法本来就是另一条建议）。
 * 不存标题原文 = 与 {@code daily_briefings} 同一条 PII 红线，也不让本表变成简报的副本。</p>
 *
 * <p><b>记录 ≠ 采纳</b>：{@code opened_agent} 只表示「点开问了」，
 * <b>不表示</b>「照着做了」。报表文案必须区分，不许把它说成「采纳率」。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("briefing_actions")
public class BriefingAction {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 简报归属日期（业务日期，Asia/Shanghai）—— 与 daily_briefings.biz_date 同口径 */
    private LocalDate bizDate;

    /** todo / risk / suggestion —— 与简报 content 的三个数组同名，不另造一套词汇 */
    private String itemKind;

    /** 条目标题的 sha256 前 16 位（稳定、不含原文） */
    private String itemKey;

    /** 动作白名单见 {@code BriefingActionService.ACTIONS} */
    private String action;

    /** 谁点的（用户 id，不含姓名 / 手机号） */
    private String actorId;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;
}
