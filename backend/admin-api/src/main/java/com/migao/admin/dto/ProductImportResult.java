package com.migao.admin.dto;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

/**
 * 商品导入结果 DTO。
 *
 * <h2>三桶口径（issue #5154「不静默跳过」的机械判据）</h2>
 * 每个**数据行**（不含表头）必须落在下面三桶之一，且恒有
 * {@code total == successCount + failCount + blankRows}：
 * <ul>
 *   <li>{@link #successCount} —— 真的落库了的行；</li>
 *   <li>{@link #failCount} —— 逐行报错的行（{@link #errors} 里必有一条，带行号 + 货号）；</li>
 *   <li>{@link #blankRows} —— 整行留空的行（不计入失败，但**必须报数**）。</li>
 * </ul>
 * 这条恒等式是「静默跳过」的唯一可判定形态：把任意一行 `continue` 掉而不记账，
 * 它就不再成立。改前实现里 {@code if (row == null) continue;} 正是这种静默跳过。
 */
@Data
public class ProductImportResult {

    /** 数据行数（不含表头）。 */
    private int total;

    /** 成功落库的数据行数。 */
    private int successCount;

    /** 失败的数据行数（= {@link #errors} 的条数）。 */
    private int failCount;

    /** 整行留空、既未导入也未报错的数据行数（显式报数 = 不静默）。 */
    private int blankRows;

    /** 新建的商品数（幂等重跑时为 0）。 */
    private int createdProducts;

    /** 命中去重键、**原地更新**的商品数（同一文件重跑时 = 首次新建数）。 */
    private int updatedProducts;

    private List<ErrorDetail> errors;

    public ProductImportResult() {
        this.total = 0;
        this.successCount = 0;
        this.failCount = 0;
        this.blankRows = 0;
        this.createdProducts = 0;
        this.updatedProducts = 0;
        this.errors = new ArrayList<>();
    }

    public static ProductImportResult create() {
        return new ProductImportResult();
    }

    public void addSuccess() {
        this.successCount++;
    }

    public void addBlankRow() {
        this.blankRows++;
    }

    public void addCreatedProduct() {
        this.createdProducts++;
    }

    public void addUpdatedProduct() {
        this.updatedProducts++;
    }

    public void addError(int row, String message) {
        addError(row, null, message);
    }

    /** @param skuCode 该行的货号（可定位：行号 + 货号；为空时前端按行号定位） */
    public void addError(int row, String skuCode, String message) {
        this.failCount++;
        this.errors.add(new ErrorDetail(row, skuCode, message));
    }

    /**
     * 逐行错误 —— 前端按「第 N 行 / 货号 / 原因」三列展示。
     *
     * <p>{@code message} 一律是**可行动**文案（说清违反了哪条口径、当前值、怎么改），
     * 前端**原样展示、不改写**（改写会让「服务端说 1 位小数、页面说格式错误」变成两套口径）。</p>
     */
    @Data
    public static class ErrorDetail {
        /** Excel 里的行号（1-based，含表头 ⇒ 表头是 1，第一条数据是 2）。 */
        private int row;
        private String skuCode;
        private String message;

        public ErrorDetail(int row, String message) {
            this(row, null, message);
        }

        public ErrorDetail(int row, String skuCode, String message) {
            this.row = row;
            this.skuCode = skuCode;
            this.message = message;
        }
    }
}
