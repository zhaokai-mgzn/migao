package com.migao.admin.dto.agent;

import com.migao.admin.entity.ScheduledTask;
import lombok.Builder;
import lombok.Data;

import java.time.OffsetDateTime;
import java.util.Map;

/**
 * 定时任务（用户「预约」）的**读面视图**（issue #6486 包 1）。
 *
 * <p>与 {@code AgentScheduledTaskRequest} 分工：本类只管<b>出去</b>的形状（供米宝工具消费），
 * 请求类只管<b>进来</b>的形状。两者不共用一个类 —— 请求里有 {@code dedupKey} 这类
 * 「只进不出」的字段，共用会让调用方以为响应里也有。</p>
 */
public final class AgentScheduledTaskViews {

    private AgentScheduledTaskViews() {
    }

    /** 一条待办的读面形状（三件套逐字透出，调用方据此渲染「为什么推 / 影响面 / 去哪处置」）。 */
    @Data
    @Builder
    public static class Task {

        private String id;
        private String taskType;
        private OffsetDateTime fireAt;
        /** 为什么推给你。 */
        private String criterion;
        /** 影响面（几条 / 多少钱）。 */
        private Map<String, Object> impact;
        /** 一键处置入口文案。 */
        private String actionLabel;
        /** 一键处置入口地址。 */
        private String actionUrl;
        /** user（米宝委托）/ system（规则派生）。 */
        private String source;
        /** pending / fired / cancelled / failed / dismissed。 */
        private String status;
        private OffsetDateTime firedAt;
        private OffsetDateTime createdAt;

        public static Task from(ScheduledTask t) {
            if (t == null) {
                return null;
            }
            return Task.builder()
                    .id(t.getId())
                    .taskType(t.getTaskType())
                    .fireAt(t.getFireAt())
                    .criterion(t.getCriterion())
                    .impact(t.getImpact())
                    .actionLabel(t.getActionLabel())
                    .actionUrl(t.getActionUrl())
                    .source(t.getSource())
                    .status(t.getStatus())
                    .firedAt(t.getFiredAt())
                    .createdAt(t.getCreatedAt())
                    .build();
        }
    }
}
