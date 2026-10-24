package com.migao.admin.service;

/**
 * 审批状态机（issue #7374，P1-2 段 1）—— **纯函数**：四态之间谁可以变成谁。
 *
 * <pre>
 *   pending ──approve──▶ approved ──consume──▶ approved(consumed)
 *      │  └─reject────▶ rejected
 *      └────withdraw───▶ withdrawn
 * </pre>
 *
 * <h3>为什么单独一个类</h3>
 * <p>状态流转判错不会报错：已驳回的审批还能被「通过」、已经用掉的超授信还能再用一次 ——
 * 两种都是**少收一道闸**，而且事后看数据完全正常。把流转规则收成纯函数，才能被逐格判据钉住。</p>
 */
public final class ApprovalState {

    /** 待审。 */
    public static final String PENDING = "pending";
    /** 已通过。 */
    public static final String APPROVED = "approved";
    /** 已驳回。 */
    public static final String REJECTED = "rejected";
    /** 已撤回（申请人自己收回）。 */
    public static final String WITHDRAWN = "withdrawn";

    private ApprovalState() {
    }

    /** 只有待审的能被裁决（通过/驳回）。 */
    public static boolean canDecide(String status) {
        return PENDING.equals(status);
    }

    /** 只有待审的能被撤回（已裁决的不能「撤回」，否则等于绕过裁决留痕）。 */
    public static boolean canWithdraw(String status) {
        return PENDING.equals(status);
    }

    /**
     * 能不能被消费（用来放行某个超阈动作）。
     *
     * <p>三条缺一不可：**已通过**、**没用过**、**未删除**。少任何一条都会让「批一次用多次」成为可能。</p>
     */
    public static boolean canConsume(String status, boolean consumed) {
        return APPROVED.equals(status) && !consumed;
    }

    /** 申请时的初始状态（显式写出来，别让「默认值」变成隐式规则）。 */
    public static String initialStatus() {
        return PENDING;
    }
}
