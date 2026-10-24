package com.migao.admin.service;

/**
 * 返工单状态机与**闭环一致性**（issue #7377，P1-5 段 2）—— 纯函数。
 *
 * <pre>
 *   draft ──start──▶ in_progress ──complete──▶ done
 *     │                    └────cancel────────▶ cancelled
 *     └────────cancel──────┘
 * </pre>
 *
 * <h3>要治的形态（issue 判据原文）</h3>
 * <p><b>「一张售后单的返工闭环状态机唯一（不得出现『已闭环但返工单还在做』）」</b>——
 * 售后单已经关闭，返工单却还在生产中：客户看到「已解决」，车间还在返工，质量成本也没结算。
 * 这种不一致不会报错，只会让两套账各说各话。</p>
 *
 * <h3>怎么保证唯一</h3>
 * <ol>
 *   <li><b>同一售后单同时只有一个未完结返工单</b>（数据库部分唯一索引兜住）；</li>
 *   <li><b>已闭环的售后单不能再开返工</b>（{@link #canOpenFor}）；</li>
 *   <li><b>完成时才回写售后状态，且只从 `processing` 推进到 `resolved`</b>
 *       （{@link #writeBackTicketStatus}）—— 不覆盖 pending/closed/rejected。</li>
 * </ol>
 */
public final class ReworkState {

    public static final String DRAFT = "draft";
    public static final String IN_PROGRESS = "in_progress";
    public static final String DONE = "done";
    public static final String CANCELLED = "cancelled";

    /** 售后单可开返工的状态（已闭环/已驳回 ⇒ 不许开）。 */
    private static final java.util.Set<String> TICKET_CLOSED = java.util.Set.of("closed", "resolved", "rejected");

    private ReworkState() {
    }

    /** 只有 draft 能开始。 */
    public static boolean canStart(String status) {
        return DRAFT.equals(status);
    }

    /** 只有 in_progress 能完成（draft 还没开工就完成 = 跳过返工）。 */
    public static boolean canComplete(String status) {
        return IN_PROGRESS.equals(status);
    }

    /** 未完结（draft / in_progress）才能取消。 */
    public static boolean canCancel(String status) {
        return DRAFT.equals(status) || IN_PROGRESS.equals(status);
    }

    /**
     * 这张售后单现在能不能开返工。
     *
     * @param ticketStatus 售后单状态（pending / processing / resolved / rejected / closed）
     */
    public static boolean canOpenFor(String ticketStatus) {
        return ticketStatus != null && !TICKET_CLOSED.contains(ticketStatus);
    }

    /**
     * 返工完成时售后状态应变成什么。
     *
     * @return 新状态；{@code null} = **不改**（当前状态不是 processing，回写会覆盖别人的结论）
     */
    public static String writeBackTicketStatus(String ticketStatus) {
        return "processing".equals(ticketStatus) ? "resolved" : null;
    }

    /** 是否已完结（done / cancelled）。 */
    public static boolean isClosed(String status) {
        return DONE.equals(status) || CANCELLED.equals(status);
    }
}
