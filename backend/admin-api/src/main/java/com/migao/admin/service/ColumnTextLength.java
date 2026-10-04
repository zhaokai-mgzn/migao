package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;

/**
 * 文本列长度准入（issue #6302）—— {@code varchar(n)} 入参的**单一**准入点（fail-closed）。
 *
 * <h2>为什么需要这个类</h2>
 * 库里的短文本列是 {@code varchar(n)}（{@code products.sku_code} = {@code varchar(30)}、
 * {@code product_skus.sku_code} = {@code varchar(50)}、{@code product_skus.door_width} =
 * {@code varchar(20)}、{@code product_colors.color_name} = {@code varchar(30)}…），而 PG 对**超长**
 * 写入**不截断、不四舍五入，直接报错**：
 * <pre>
 * ERROR: value too long for type character varying(30)
 *   @ com.migao.admin.mapper.ProductMapper.insert
 * </pre>
 * 缺了应用层准入 ⇒ 调用方传 31 个字符的货号时接口返
 * {@code {"success":false,"error":{"code":"INTERNAL_ERROR","message":"服务器内部错误"}}}（HTTP 500）——
 * 用户**无法自救**：他不知道哪一列、多长、该改什么，只看到「服务器内部错误」。
 *
 * <h2>既有范式（本类照抄 MoneyScale 的形态，不另立框架）</h2>
 * 本仓对「库列装得下装不下」的一贯口径是 fail-closed、**判在写之前的入口**、**显式拒绝而非静默截断**：
 * <ul>
 *   <li>{@link MoneyScale#requireTwoDecimalsOrNull}（金额小数位：超 2 位 ⇒ 422）；</li>
 *   <li>{@link StockQuantity#requireOneDecimal}（库存精度：超 1 位小数 ⇒ 拒绝）；</li>
 *   <li>{@code InboundOrderService#requireItemNumbers} —— 注释逐字「显式拒绝、不静默取整」。</li>
 * </ul>
 * 数量 / 金额面已有准入，**字符串长度面此前是空的**（本类补齐）。截断**不是**可接受的替代：静默丢弃
 * 用户输入的尾部字符 = 货号被改掉而无人知道（同族形态见 {@code MoneyScale} 的「静默取整」）。
 *
 * <h2>判「有效长度」用码点，不用 {@code String.length()}</h2>
 * PG 的 {@code varchar(n)} 数的是**字符**（UTF-8 码点），而 Java 的 {@code String.length()} 数的是
 * UTF-16 码元 —— 增补平面字符（emoji、生僻字）前者记 1、后者记 2。用 {@code length()} 会把
 * 「30 个 emoji」这种**库列装得下**的输入误判为超长（边界值假红）。故取
 * {@link String#codePointCount(int, int)}，与列的口径对齐。
 *
 * <h2>边界（如实登记）</h2>
 * 本类只做**准入**（拒绝），**不做**截断 / 归一：值合法时**原样返回**（与 {@code MoneyScale} 同口径）。
 * 它判不了「列长度改小了而调用点没跟着改」—— 那一半由
 * {@code ProductTextColumnAdmissionMetaGuardTest}（现取 {@code information_schema.columns} 对账）承担。
 */
public final class ColumnTextLength {

    private ColumnTextLength() {
    }

    /**
     * 文本**准入**（fail-closed）：长度超过 {@code maxLength} 个字符 ⇒ 抛
     * {@link BusinessException}（{@code 422 VALIDATION_ERROR}，可行动文案）。
     *
     * <p><b>{@code null} = 「本字段未传」⇒ 原样返回 {@code null}</b>：本类判的是长度，不是必填
     * （必填由各自入口的既有判据承担，如 {@code ProductCreateRequest.name} 的 {@code @NotBlank}）。
     * 把 {@code null} 归一成空串会把「不改这个字段」静默改成「清空这个字段」。</p>
     *
     * @param raw       原始值（{@code null} = 未传）
     * @param maxLength 库列上限（{@code varchar(n)} 的 n；**现取 {@code information_schema}**，不许照抄）
     * @param label     出错文案里的字段名（如「商品货号 skuCode」）
     * @return 合法值**原样返回**
     */
    public static String requireWithinOrNull(String raw, int maxLength, String label) {
        String problem = lengthProblemOrNull(raw, maxLength, label);
        if (problem != null) {
            throw BusinessException.validationError(problem);
        }
        return raw;
    }

    /**
     * 与 {@link #requireWithinOrNull} **同一判定**，但把「哪里不合法」作为**可行动文案**返回
     * （合法 / {@code null} ⇒ 返回 {@code null}）—— 供**收集式校验**（逐条错误汇总后一次性 422）的入口复用，
     * 免得它们再写第二份长度判定（理由与 {@code MoneyScale#precisionProblemOrNull} 逐字同源）。
     */
    public static String lengthProblemOrNull(String raw, int maxLength, String label) {
        if (raw == null) {
            return null;
        }
        int actual = raw.codePointCount(0, raw.length());
        if (actual > maxLength) {
            return String.format(
                    "%s 最长 %d 个字符（库列 varchar(%d)），当前 %d 个字符 —— 请缩短到 %d 个字符以内后重试"
                            + "（服务端不截断、不静默丢弃超出部分）",
                    label, maxLength, maxLength, actual, maxLength);
        }
        return null;
    }
}
