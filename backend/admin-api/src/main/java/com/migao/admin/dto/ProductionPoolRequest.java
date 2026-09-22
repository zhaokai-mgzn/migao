package com.migao.admin.dto;

import lombok.Data;

import java.util.List;

/**
 * 待派池的成批预览 / 成批派单请求（issue #5169 = 阶段 2b-1）。
 *
 * <p>{@code batches} / {@code assignmentRule} 与
 * {@link ProcessingOrderGenerateRequest} **逐字同义**（同一个 {@code BatchAssignment} 类型、
 * 同一个归一化函数）—— 池化多出来的只有 {@link #pooled} 一个开关，其余口径不另立一份。</p>
 */
@Data
public class ProductionPoolRequest {

    /** 订单 ID 或订单号列表（服务端解析），**顺序 = 返回结果的顺序**（与逐单派一致）。 */
    private List<String> orderIds;

    /** 逐面料行指定批次（缺省 / 空列表 ⇒ 不指派；语义同 {@link ProcessingOrderGenerateRequest#getBatches()}）。 */
    private List<ProcessingOrderGenerateRequest.BatchAssignment> batches;

    /**
     * 批次指派规则（{@code fifo} / {@code best_fit}；缺省 = 不传 ⇒ 未指定批次的行**不补位**）。
     *
     * <p>语义与 {@link ProcessingOrderGenerateRequest#getAssignmentRule()} 逐字相同，
     * 含「非法值 ⇒ 整批拒绝，不静默回落」（#5167）。<b>池化**不改**这条</b>：
     * 池级求解只改「哪些块可以并排」，不改「从哪一批裁」的规则与 fail-closed 面。</p>
     */
    private String assignmentRule;

    /**
     * 🔴 <b>池化开关 —— 缺省关</b>（issue #5169 判据 1：不启用池化 ⇒ 行为与今天逐值相同）。
     *
     * <p>{@code null} / {@code false} ⇒ **逐单派**：每张单各自求解、各自扣账，与今天逐值相同
     * （含错误文案与结果顺序）。只有显式传 {@code true} 才走**跨订单成组**的池级求解。</p>
     *
     * <p>开关的缺省值只有一处（{@code ProcessingOrderService.POOLED_DEFAULT_ENABLED}）——
     * 在 DTO 上再写一个 {@code false} 字面量就是第二份会漂的缺省值。</p>
     */
    private Boolean pooled;
}
