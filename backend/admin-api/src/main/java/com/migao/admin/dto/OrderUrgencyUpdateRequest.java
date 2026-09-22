package com.migao.admin.dto;

import lombok.Data;

/**
 * 订单级「加急 / 客户要求到货日」的改单请求（V120，issue #5177）。
 *
 * <h2>为什么是**三态**而不是两个必填字段</h2>
 * 改单与建单不同：用户可能**只想**切换加急、不动到货日，也可能**只想**改到货日。
 * 若两个字段都当「必填 = 覆盖」，那「只改加急」这一次调用就会顺手把到货日抹掉
 * —— 用户没表达过的意图不该被实现（同族纪律：缺省/未传 **不猜**）。
 * ⇒ 每个字段都是「**不传 = 本字段不改**」，只在传了的时候才写。
 *
 * <h2>字段语义（{@code null} 与 {@code ""} 是**两件事**）</h2>
 * <ul>
 *   <li>{@code isUrgent = null} ⇒ **不改**加急标记；{@code true}/{@code false} ⇒ 显式设为该值
 *       （{@code false} 是**真值**：「取消加急」是一次真实意图，不是「没填」）。</li>
 *   <li>{@code requiredDeliveryDate = null} ⇒ **不改**到货日；</li>
 *   <li>{@code requiredDeliveryDate = ""}（空串）⇒ **清空**到货日（回到「未指定」）。
 *       —— 为什么不用 `null` 表达清空：那就与「不改」同形了，两者必须可区分；</li>
 *   <li>{@code requiredDeliveryDate = "YYYY-MM-DD"} ⇒ 设为该日期；**其它形态 ⇒ 显式拒绝**
 *       （不静默回落、不当成清空）。</li>
 * </ul>
 *
 * <p>🔴 本请求**只碰 {@code orders} 自己的两列**：不读写售后工单的 {@code priority}，
 * 不做任何跨表同步（用户裁定「加急不能跟售后工单绑定，得在订单上直接做」）。</p>
 */
@Data
public class OrderUrgencyUpdateRequest {

    /** 加急标记：{@code null} = 不改；{@code true}/{@code false} = 显式设值。 */
    private Boolean isUrgent;

    /**
     * 客户要求到货日：{@code null} = 不改；{@code ""} = 清空（未指定）；
     * {@code YYYY-MM-DD} = 设为该日期；其它 ⇒ 显式拒绝（422）。
     */
    private String requiredDeliveryDate;
}
