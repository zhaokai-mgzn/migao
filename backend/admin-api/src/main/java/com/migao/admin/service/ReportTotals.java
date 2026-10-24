package com.migao.admin.service;

import java.math.BigDecimal;
import java.util.List;

/**
 * 报表的**合计与小计复算**（issue #7376，P1-4 段 1）—— 纯函数：合计 = 明细之和，且**空数据 ≠ 0**。
 *
 * <h3>为什么单独一个类</h3>
 * <p>报表最容易被信任、也最容易被做错：老板看到「合计 12,000」不会去逐行加。两类错都静默：</p>
 * <ol>
 *   <li><b>合计与明细对不上</b>（漏一行、按分页算了合计）—— 没人发现，决策按错数走；</li>
 *   <li><b>「没有数据」被画成 0</b> —— 那会被读成「这个月毛利是 0」而不是「还没跑数」，
 *       两者结论完全相反（一个要追责、一个要重算）。</li>
 * </ol>
 *
 * <h3>约定</h3>
 * <p>金额一律 {@code BigDecimal}，空集时返回 {@code null} 而不是 {@code ZERO}：
 * 「没有数据」与「合计为零」是两件事，调用方必须显式处理前者。</p>
 */
public final class ReportTotals {

    /**
     * 合计（空集 ⇒ {@code null}）。
     *
     * @param values 明细值（可含 null，视为缺值跳过 —— 报表里「未知」不参与求和，也不当 0）
     */
    public static BigDecimal sum(List<BigDecimal> values) {
        if (values == null || values.isEmpty()) {
            return null;
        }
        BigDecimal total = BigDecimal.ZERO;
        boolean any = false;
        for (BigDecimal value : values) {
            if (value == null) {
                continue;
            }
            total = total.add(value);
            any = true;
        }
        return any ? total : null;
    }

    /**
     * 复算校验：合计是否等于明细之和（判据用；不满足就是算错了）。
     *
     * @param reportedTotal 报表里给出的合计
     * @param details       明细值
     */
    public static boolean totalsMatchDetails(BigDecimal reportedTotal, List<BigDecimal> details) {
        BigDecimal computed = sum(details);
        if (computed == null) {
            return reportedTotal == null;
        }
        return reportedTotal != null && reportedTotal.compareTo(computed) == 0;
    }

    /**
     * 数据是否在场（判据用）：**空明细 ⇒ false**。
     *
     * <p>这个布尔值就是「空数据 ≠ 0」的载体：值为 0 但有明细 ⇒ {@code true}；没有明细 ⇒ {@code false}。
     * 报表里必须把两者分开展示（「本月毛利 0 元」 vs 「本月还没有已完工的订单」）。</p>
     */
    public static boolean hasData(List<?> rows) {
        return rows != null && !rows.isEmpty();
    }
}
