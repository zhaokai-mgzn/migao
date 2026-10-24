// case_ids: QC-002
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 返工单状态机与闭环一致性（issue #7377，P1-5 段 2）—— issue 判据原文：
 * **「一张售后单的返工闭环状态机唯一（不得出现『已闭环但返工单还在做』）」**。
 *
 * <p>这种不一致不会报错：客户看到「已解决」，车间还在返工，成本也没结算 —— 两套账各说各话。</p>
 */
@DisplayName("返工状态机：四态流转 / 已闭环售后不能再开返工 / 回写只从 processing 推进")
class ReworkStateTest {

    @Test
    @DisplayName("流转：只有 draft 能开工；只有 in_progress 能完成；未完结才能取消")
    void transitionsAreStrict() {
        assertThat(ReworkState.canStart(ReworkState.DRAFT)).isTrue();
        assertThat(ReworkState.canStart(ReworkState.IN_PROGRESS)).isFalse();

        assertThat(ReworkState.canComplete(ReworkState.IN_PROGRESS)).isTrue();
        assertThat(ReworkState.canComplete(ReworkState.DRAFT))
                .as("没开工就完成 = 跳过返工").isFalse();

        assertThat(ReworkState.canCancel(ReworkState.DRAFT)).isTrue();
        assertThat(ReworkState.canCancel(ReworkState.IN_PROGRESS)).isTrue();
        assertThat(ReworkState.canCancel(ReworkState.DONE)).isFalse();
        assertThat(ReworkState.canCancel(ReworkState.CANCELLED)).isFalse();
    }

    @Test
    @DisplayName("🔴 已闭环 / 已驳回的售后单不能再开返工（否则就是「闭环了单子还在做」）")
    void closedTicketsCannotOpenRework() {
        assertThat(ReworkState.canOpenFor("pending")).isTrue();
        assertThat(ReworkState.canOpenFor("processing")).isTrue();
        assertThat(ReworkState.canOpenFor("closed")).isFalse();
        assertThat(ReworkState.canOpenFor("resolved")).isFalse();
        assertThat(ReworkState.canOpenFor("rejected")).isFalse();
        assertThat(ReworkState.canOpenFor(null)).isFalse();
    }

    @Test
    @DisplayName("🔴 完成回写：只把 processing 推进到 resolved，其它状态一律不动")
    void writeBackOnlyFromProcessing() {
        assertThat(ReworkState.writeBackTicketStatus("processing")).isEqualTo("resolved");
        assertThat(ReworkState.writeBackTicketStatus("pending"))
                .as("还没处理完就改成已解决 = 替别人下结论").isNull();
        assertThat(ReworkState.writeBackTicketStatus("closed")).isNull();
        assertThat(ReworkState.writeBackTicketStatus("rejected")).isNull();
    }

    @Test
    @DisplayName("isClosed：done / cancelled 算完结")
    void closedDetection() {
        assertThat(ReworkState.isClosed(ReworkState.DONE)).isTrue();
        assertThat(ReworkState.isClosed(ReworkState.CANCELLED)).isTrue();
        assertThat(ReworkState.isClosed(ReworkState.DRAFT)).isFalse();
        assertThat(ReworkState.isClosed(ReworkState.IN_PROGRESS)).isFalse();
    }
}
