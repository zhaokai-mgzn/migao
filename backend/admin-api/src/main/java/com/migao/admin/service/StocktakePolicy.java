package com.migao.admin.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;

/**
 * 盘点差异的**恒等式与准入**（issue #7373，P1-1 段 2）—— 纯函数，不碰库。
 *
 * <h3>守的三个恒等式</h3>
 * <ol>
 *   <li><b>逐批次</b>：`差异 = 实盘 − 账面`；</li>
 *   <li><b>合计</b>：`Σ账面 − Σ实盘 = Σ差异`（差一分都算错 —— 这条是「盘点结果可信」的唯一凭据）；</li>
 *   <li><b>调整后不为负</b>：任何批次调整后数量 `&gt;= 0`（盘亏不能让库存变成负数）。</li>
 * </ol>
 *
 * <h3>为什么单列一个类</h3>
 * <p>盘点的价值全在「差异算得对、调得对」。这里写错不会报错：少调一个批次、差异符号写反、
 * 把「还没数」当成「数了正好一样」—— 三种都让账面悄悄偏离实物，而**账面看起来依然正常**。</p>
 */
public final class StocktakePolicy {

    private StocktakePolicy() {
    }

    /** 一行盘点结果（账面 / 实盘）。 */
    public record Line(BigDecimal bookQty, BigDecimal countedQty) {

        /** 是否已录实盘（`null` = 还没数，**不是**「数了正好一样」）。 */
        public boolean counted() {
            return countedQty != null;
        }

        /** 差异 = 实盘 − 账面；未录实盘 ⇒ `null`（未判定，不是 0）。 */
        public BigDecimal diff() {
            if (!counted() || bookQty == null) {
                return null;
            }
            return countedQty.subtract(bookQty).setScale(1, RoundingMode.UNNECESSARY);
        }

        /** 是否真有差异（未录实盘不算差异）。 */
        public boolean differs() {
            BigDecimal d = diff();
            return d != null && d.signum() != 0;
        }
    }

    /**
     * **落库后的三列是否自相一致**：`Σ(实盘 − 账面) == Σ存储的差异`。
     *
     * <p>这条判据能抓的形态很具体：有人改了 `counted_qty` 却没同步 `diff_qty`（或两列符号不一致）——
     * 那会让「盘点结果」与「调整依据」分家，而单看任何一列都正常。屯里传进来的必须是
     * **数据库里存的三列**（不是现算的），否则它退化成恒等式（自己减自己永远相等）。</p>
     */
    public static boolean storedDiffsAgreeWithQuantities(List<StoredRow> rows) {
        if (rows == null || rows.isEmpty()) {
            return true;
        }
        BigDecimal computed = BigDecimal.ZERO;
        BigDecimal stored = BigDecimal.ZERO;
        for (StoredRow row : rows) {
            if (row == null || row.countedQty() == null || row.bookQty() == null
                    || row.storedDiff() == null) {
                continue;
            }
            computed = computed.add(row.countedQty().subtract(row.bookQty()));
            stored = stored.add(row.storedDiff());
        }
        return computed.compareTo(stored) == 0;
    }

    /** 落库形态（三列都来自库，不是现算）。 */
    public record StoredRow(BigDecimal bookQty, BigDecimal countedQty, BigDecimal storedDiff) {
    }

    /** 是否所有行都已录实盘（有一条没数就不能完成盘点 —— 否则等于默认它「一样」）。 */
    public static boolean allCounted(List<Line> lines) {
        if (lines == null || lines.isEmpty()) {
            return false;
        }
        for (Line line : lines) {
            if (line == null || !line.counted()) {
                return false;
            }
        }
        return true;
    }

    /** 差异总额（绝对值之和 —— 审批金额按「调多少」算，盘盈盘亏都要有人看过）。 */
    public static BigDecimal totalAbsDiff(List<Line> lines) {
        BigDecimal sum = BigDecimal.ZERO;
        if (lines == null) {
            return sum;
        }
        for (Line line : lines) {
            BigDecimal d = line == null ? null : line.diff();
            if (d != null) {
                sum = sum.add(d.abs());
            }
        }
        return sum;
    }

    /** 调整后数量是否合法（不为负）。 */
    public static boolean adjustable(BigDecimal bookQty, BigDecimal diff) {
        if (bookQty == null || diff == null) {
            return false;
        }
        return bookQty.add(diff).signum() >= 0;
    }
}
