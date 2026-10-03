package com.migao.admin.validation;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.exception.BusinessException;

import java.util.List;
import java.util.Map;

/**
 * 分页入参（{@code page} / {@code size}）的**单点准入**（issue #6222，P3·读面）。
 *
 * <h2>病（逐字复现，2026-10-03 未修复构建 :8080）</h2>
 * {@code GET /api/admin/orders?page=1&size=-5} ⇒ HTTP 200、{@code data.total=0}、{@code data.items}
 * 长度 359（after-sales 5 / stock-ledger 389）—— 自相矛盾：客户端分页器看 {@code total=0}
 * **立刻认为已到末页** ⇒ 表现为「有数据却显示为空 / 翻不动页」。
 *
 * <h2>机制归因（为什么 {@code total=0} 却返回整页）</h2>
 * MyBatis-Plus 的 {@code PaginationInnerInterceptor} 把**负数 {@code size}**
 * 当作「不分页」的信号：既不追加 LIMIT、也**不执行 count 查询** ⇒ 拦截器只填 {@code records}、
 * 不填 {@code total}。行数不设上界（被 {@code setMaxLimit(500)} 约束的只是**正数** size），
 * 而 {@code total} 停在默认 0。
 *
 * <h2>口径裁定：**显式拒绝（400）**，不是钳到合法下界</h2>
 * 两条都合法，本仓取前者，理由三条（可复核）：
 * <ol>
 *   <li>病根是「非法入参**不静默**」（issue 原文），钳位 = 悄悄改写用户请求 ⇒ **仍是静默**，
 *       只是把「静默给错数据」换成「静默改口径」；</li>
 *   <li>本仓已有**同族显式拒绝范式**：库存侧 {@code StockQuantity.requireOneDecimal}、
 *       退款金额 {@code MoneyScale.requireTwoDecimals}（#6221）、负数数量 400
 *       （{@code WorkerInboundControllerTest} ⇒ 400 {@code VALIDATION_ERROR}）；</li>
 *   <li>钳位会**掩盖**调用方（含 Agent / 前端）的真实缺陷：它永远拿不到「你的入参非法」这个信号。</li>
 * </ol>
 *
 * <h2>为什么是**一个**地方（单点准入，不是每个控制器各写一份）</h2>
 * 分页入口有**两个族**：① 直接 {@code @RequestParam long size} 的控制器方法（现取 20 个方法）；
 * ② 绑查询 DTO 的控制器方法（{@code ProductQueryRequest} / {@code ProcessingItemQueryRequest} /
 * {@code NotificationQueryRequest} 各带独立 {@code page}/{@code size} 字段、**没有共同基类**，
 * 且 DTO 属性名不保证等于 HTTP 参数名——实测 {@code ProductQueryRequest.productId} 对
 * {@code @RequestParam productCode}）。⇒ 在 DTO 面上做准入要么靠 {@code WebDataBinder}
 * 名字启发（**会漏**），要么按属性名校验（**对不上**）。而两个族**都必须**经过同一个 HTTP 参数集
 * ⇒ 唯一真正单点 = **Servlet 层参数闸**（{@link com.migao.admin.security.PaginationParamInterceptor}
 * 在 {@code preHandle} 调用本类）。诚实登记：它**不覆盖**「不经 HTTP 层直接调 service」的内部调用
 * （审计/定时任务/bypass），那属另一条兜底线，不在本单射程（见类级元守卫的覆盖边界）。
 *
 * <h2>白名单（谁必须靠拒绝、谁不在射程）</h2>
 * 只有名为 {@code page} / {@code size}（大小写不敏感）的参数在此判定 ——
 * 这是本仓**全量**分页入口的 HTTP 参数名（现取读数见
 * {@code tests/unit_ci_workflows/pagination_param_gate_ledger.json}）。{@code othersize}、
 * 文件上传部件名里的 {@code size} 等**一律不判**（判了就是新的假红）。
 */
public final class PaginationParamGate {

    /** 页码参数名（HTTP 参数名，大小写不敏感）。 */
    public static final String PAGE = "page";

    /** 每页大小参数名（HTTP 参数名，大小写不敏感）。 */
    public static final String SIZE = "size";

    private PaginationParamGate() {
    }

    /**
     * 判定单个分页参数：合法 ⇒ 什么都不做；非法 ⇒ 抛出 400 {@code VALIDATION_ERROR}。
     *
     * <p>非法 = ① 非整数（含空白 / 空串）② 越界：{@code size < 0} 或 {@code page < 1}（含负数与 0）。
     * 出参形状复用**既有**信封：{@code error.code=VALIDATION_ERROR} +
     * {@code error.details:[{field,message}]}（同 {@code GlobalExceptionHandler} 的
     * 400/422 家族与 {@code PermissionDeniedResponse}）。</p>
     *
     * <p>{@code size=0} 仍合法（不返回任何行、{@code total} 仍是真总数 ⇒ 语义自洽，不产生
     * 「有数据却显示为空」）。注意 {@code Long.parseLong} 对 {@code "+5"} 会成功 ⇒ 显式拒掉
     * 符号前缀，保证「只有十进制数字面量」这一条口径。</p>
     *
     * @param name  参数名（{@code page} / {@code size}，大小写不限）
     * @param value 原始参数值（Servle 层的字符串形态）
     * @throws BusinessException 非法入参 ⇒ 400 {@code VALIDATION_ERROR}
     */
    public static void requireValid(String name, String value) {
        // 白名单**先于**解析：射程外的参数名不判、也不解析（否则 `othersize=-5` 会被误拒 = 新假红）
        if (!isPaginationParamName(name)) {
            return;
        }
        Long parsed = parseDecimal(name, value);
        if (SIZE.equalsIgnoreCase(name) && parsed < 0) {
            throw reject(name, value, "size 不能为负数（会静默返回整页且 total=0，请传 size >= 0）");
        }
        if (PAGE.equalsIgnoreCase(name) && parsed < 1) {
            throw reject(name, value, "page 必须 >= 1");
        }
    }

    /**
     * 该参数名是否属于分页面（**白名单**：只有 {@code page} / {@code size}）。
     *
     * @param name HTTP 参数名
     * @return 是 ⇒ 必须过 {@link #requireValid}
     */
    public static boolean isPaginationParamName(String name) {
        return PAGE.equalsIgnoreCase(name) || SIZE.equalsIgnoreCase(name);
    }

    /**
     * 只认十进制整数字面量（可带**一个**前导 {@code -}）：拒绝 {@code +5} / {@code 1.5} /
     * 空白 / 空串 / 非数字 / 多个符号 —— 负数在这里**能**解析（越界判定在 {@link #requireValid}）。
     */
    private static Long parseDecimal(String name, String value) {
        String text = value == null ? "" : value.trim();
        boolean negative = text.startsWith("-");
        String digits = negative ? text.substring(1) : text;
        if (digits.isEmpty() || !digits.chars().allMatch(Character::isDigit)) {
            throw reject(name, value, name + " 必须是十进制整数");
        }
        try {
            return Long.parseLong(text);
        } catch (NumberFormatException overflow) {
            // 位数超出 long ⇒ 同样属非法入参（不静默落兜底 500）
            throw reject(name, value, name + " 超出取值范围");
        }
    }

    private static BusinessException reject(String name, String value, String reason) {
        // 复用既有信封：400 VALIDATION_ERROR + error.details:[{field,message}]
        // （走 BusinessException 的工厂，不新造异常类型；状态码显式 400 —— 同族既有口径）
        return BusinessException.validationError(
                "分页参数不合法: " + name + "=" + value,
                List.of(new ApiResponse.ErrorDetail(name, reason)),
                null,
                400);
    }

    /**
     * 逐值判定整个 HTTP 参数集的便捷入口（供判据 / 内部直调复用，避免第二份遍历逻辑）。
     *
     * @param params 参数名 → 值数组（{@code HttpServletRequest#getParameterMap()} 的形态）
     * @throws BusinessException 任一分页参数非法 ⇒ 400 {@code VALIDATION_ERROR}
     */
    public static void requireValid(Map<String, String[]> params) {
        for (Map.Entry<String, String[]> entry : params.entrySet()) {
            if (!isPaginationParamName(entry.getKey())) {
                continue;
            }
            for (String value : entry.getValue()) {
                requireValid(entry.getKey(), value);
            }
        }
    }
}
