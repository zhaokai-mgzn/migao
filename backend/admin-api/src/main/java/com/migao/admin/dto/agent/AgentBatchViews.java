package com.migao.admin.dto.agent;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 批量更新的**响应视图**（issue #5314 冻结契约；字段名与 Agent 侧逐字对齐）。
 *
 * <pre>
 * 创建   → {batchId, itemCount, status:"preview"}
 * 执行   → {batchId, status, results:[{resourceId, success, error?}]}
 * 撤销   → {batchId, status, results:[...]}
 * 查询   → 进度 / 结果 / 可撤销性（revertible + 逐条 before → after）
 * </pre>
 *
 * <p>三类视图同放一处（本仓 {@code SavingMetricViews} / {@code ProductionPoolViews} 同款）：
 * 它们是同一份契约的三个面，分开放必然漂移。{@code NON_NULL} ⇒ 「成功项不带 {@code error} 键」
 * 是契约的一部分，不是省略号。</p>
 */
public final class AgentBatchViews {

    private AgentBatchViews() {
    }

    /** 批次视图（四个端点共用：用不到的字段为 null ⇒ 不出现在 JSON 里）。 */
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class Batch {

        private String batchId;

        private String batchType;

        /** preview / executing / done / partial / reverted / revert_partial */
        private String status;

        private Integer itemCount;

        private Integer successCount;

        private Integer failCount;

        /** 可撤销性（仅查询端点回填）：状态为 done / partial 时为 true。 */
        private Boolean revertible;

        private String createdBy;

        private OffsetDateTime createdAt;

        private OffsetDateTime executedAt;

        private OffsetDateTime revertedAt;

        /** 逐条明细（仅查询端点回填）：before → after 与逐条 status / error。 */
        private List<Item> items;

        /** 逐条结果（仅执行 / 撤销端点回填）。 */
        private List<Result> results;
    }

    /** 逐条明细（查询端点）—— 撤销依据可核对。 */
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class Item {

        private String resourceId;

        private String field;

        private String oldValue;

        private String newValue;

        private String status;

        private String error;
    }

    /**
     * 逐条结果（执行 / 撤销端点）。
     *
     * <p>{@code success} = 「本条已按预期处置」：撤销时对**执行阶段就失败过**的条目
     * （{@code status=skipped}）同样为 true —— 它本来就没生效、没有东西要还原，
     * 具体形态看明细 {@code status}，不靠这一个布尔承载两种语义。</p>
     */
    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class Result {

        private String resourceId;

        private boolean success;

        private String error;
    }
}