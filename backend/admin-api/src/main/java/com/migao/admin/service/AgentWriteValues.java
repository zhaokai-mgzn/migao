package com.migao.admin.service;

import java.math.BigDecimal;

/**
 * Agent 写路径的「改前值 × DB 当前值」核对 —— <b>全仓唯一实现</b>（issue #5317）。
 *
 * <h2>为什么必须只有一个实现</h2>
 * 同一语义（"调用方声明的改前值是否等于 DB 真值"）在两处各写一份 ⇒ 必然漂移：
 * 批次严、单条松，而<b>下一个读代码的人会以为单条也是严的</b>（{@code migao-dev-flow} §17.3
 * 「同一真值两处投影」）。故 #5314 的批次核对与 #5317 的单条改价核对**共用本类**，
 * 由 {@code AgentWriteValuesTest} 的 L0 静态不变式钉住「只有一处定义 + 两处调用点都引它」。
 *
 * <h2>口径（照抄 #5314，不另立第二套）</h2>
 * <ul>
 *   <li>价格字段：{@code BigDecimal.compareTo} —— <b>按值</b>核对，{@code 10.0} 与 {@code 10.00}
 *       是同一个价（不比字符串写法）；</li>
 *   <li>非价格字段（{@code status}）：字面比对（大小写敏感，与既有批次口径一致）；</li>
 *   <li>任一侧缺失或非法数字 ⇒ {@code false}（<b>fail-closed</b>：不给"没法比对"放行）。</li>
 * </ul>
 */
public final class AgentWriteValues {

    /** 商品级基础价（批次 field 与单条改价共用同一个字段词）。 */
    public static final String FIELD_BASE_PRICE = "basePrice";

    /** 上下架状态。 */
    public static final String FIELD_STATUS = "status";

    private AgentWriteValues() {
    }

    /**
     * 调用方声明的改前值 × DB 当前值：按值核对。
     *
     * @param field   字段词（{@link #FIELD_BASE_PRICE} / {@link #FIELD_STATUS}）
     * @param given   调用方声明的改前值（可为 null ⇒ 视为不可核对）
     * @param current DB 当前值（可为 null ⇒ 视为不可核对）
     * @return true = 两者等价（放行）；false = 不符或不可核对（拒绝）
     */
    public static boolean sameValue(String field, String given, String current) {
        if (given == null || current == null) {
            return false;   // 无处可比 ⇒ fail-closed（不得为「没法比」放行）
        }
        if (FIELD_BASE_PRICE.equals(field)) {
            try {
                return new BigDecimal(given).compareTo(new BigDecimal(current)) == 0;
            } catch (NumberFormatException e) {
                return false;
            }
        }
        return given.trim().equals(current);
    }
}