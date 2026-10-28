package com.migao.admin.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 裁剪高度的**纯计算**（无 Spring、无 IO）—— 命中推导 + 求和 + 取整。
 *
 * <p>口径（设计单 §2.3）：</p>
 * <pre>
 *   裁剪高度(部位) = 取整( 成品高 + Σ(命中且启用的增量项 × direction) )
 * </pre>
 *
 * <h3>v2（issue #7997；用户 2026-10-28 逐字「要根据特殊选项 + 加工项 + 部位来定高度」「再允许一个默认公共（兜底）裁高参数」）</h3>
 *
 * <p>每个增量项的命中口径从「**一条**触发」升级为「**条件组**」：</p>
 * <pre>
 *   item.position     部位（null = 不限）
 *   item.scope        specific（工序专用，默认）| fallback（公共兜底）
 *   item.conditions   [{kind, values}] —— **跨 kind 与（AND）、组内 values 或（OR）**；空数组 = 恒真
 * </pre>
 *
 * <p><b>兜底是「替换」语义</b>（用户 2026-10-28 裁定 A）：先求全部 {@code specific} 项；
 * <b>只要有一项命中</b>（含「命中但未配置取值」—— 那是要显式报出的缺项，不是没命中）⇒ 兜底组<b>整组不参与</b>；
 * 只有专用项<b>零命中</b>时才求 {@code fallback} 组。⇒ 布绑带 / 接高的单不会把「包布折 / 布贴」那批默认项也算进去。</p>
 *
 * <p><b>命中口径仍复用 {@code production_route_rules} 的触发面</b>（设计单 §1.6）：
 * {@code kind ∈ option / craft / processing_item / shaped} 四档，与订单侧同名取值域
 * （{@code processingInfo.specialOptions[]} / 工艺名 / 加工项名 / 是否定型）<b>逐字</b>比对；
 * 本类<b>不</b>新增第五种触发源（工序本就由特殊选项派生，另立一份工序真值源就会与 route rules 漂）。
 * 判据：出现第二份「条件 → 命中」实现 ⇒ 红（{@code CuttingHeightConfigServiceTest}）。</p>
 *
 * <p><b>未配置取值（{@code value=null}，如壁达的「画线」）不算 0</b>：它进 {@code misses}
 * （{@code reason=unresolved}）且<b>不计入</b>合计 —— 静默按 0 算 = 给机器的值偏小 = 裁短（事故）。</p>
 */
final class CuttingHeightCalculator {

    /** 触发类型闭词表（与 {@code production_route_rules.trigger_kind} 同集合）。 */
    static final List<String> TRIGGER_KINDS = List.of("option", "craft", "processing_item", "shaped");

    /** 部位闭词表（与订单行的部位词表同集合）；{@code null} = 不限部位。 */
    static final List<String> POSITIONS = List.of("布帘", "纱帘", "帘头");

    /** 作用域闭词表：{@code specific} = 工序专用（默认）；{@code fallback} = 公共兜底。 */
    static final List<String> SCOPES = List.of("specific", "fallback");

    /** {@code scope} 缺省值（写面缺键 / 存量 v1 归一都落这里）。 */
    static final String SCOPE_SPECIFIC = "specific";

    /** 公共兜底组。 */
    static final String SCOPE_FALLBACK = "fallback";

    private static final BigDecimal MAX_VALUE = new BigDecimal("10");

    private CuttingHeightCalculator() {
    }

    /** 订单侧的命中输入（逐字取自库/快照，**不在本层重算**）。 */
    record Vars(String position, BigDecimal finishedHeight, String craft,
                List<String> specialOptions, List<String> processingItems, Boolean isShaped) {
    }

    /** 一次命中的增量项。 */
    record Hit(String key, String name, BigDecimal value, String direction, boolean heightJoin) {
    }

    /** 未计入的项：{@code unresolved}（命中但**未配置取值**，如壁达的「画线」）。 */
    record Miss(String key, String name, String reason) {
    }

    record Result(BigDecimal base, BigDecimal cuttingHeight, String mode, int digits,
                  List<Hit> hits, List<Miss> misses) {
    }

    @SuppressWarnings("unchecked")
    static Result compute(Map<String, Object> config, Vars vars) {
        Map<String, Object> rounding = asMap(config.get("rounding"));
        String mode = str(rounding.get("mode"), "half_up");
        int digits = intOf(rounding.get("digits"), 3);

        List<Map<String, Object>> specific = new ArrayList<>();
        List<Map<String, Object>> fallback = new ArrayList<>();
        for (Map<String, Object> item : asList(config.get("items"))) {
            if (Boolean.FALSE.equals(item.get("enabled"))) {
                // 未启用的项**不参与**：既不命中、也不进 misses（那是「有意关掉」，不是「配置缺项」）。
                continue;
            }
            if (SCOPE_FALLBACK.equals(str(item.get("scope"), SCOPE_SPECIFIC))) {
                fallback.add(item);
            } else {
                specific.add(item);
            }
        }

        // ① 专用项：只要有一项命中（含未配置取值那一种），兜底组就整组不参与。
        Pass pass = apply(specific, vars, vars.finishedHeight());
        if (!pass.matched()) {
            // ② 专用项零命中 ⇒ 公共兜底组（替换语义，不是叠加）。
            pass = apply(fallback, vars, vars.finishedHeight());
        }
        return new Result(vars.finishedHeight(), round(pass.total(), mode, digits), mode, digits,
                pass.hits(), pass.misses());
    }

    /** 一组增量项的一次求值。{@code matched} = 有项命中（**无论取值是否配置**）。 */
    private record Pass(BigDecimal total, boolean matched, List<Hit> hits, List<Miss> misses) {
    }

    private static Pass apply(List<Map<String, Object>> items, Vars vars, BigDecimal base) {
        BigDecimal total = base;
        boolean matched = false;
        List<Hit> hits = new ArrayList<>();
        List<Miss> misses = new ArrayList<>();
        for (Map<String, Object> item : items) {
            if (!matches(item, vars)) {
                // 未命中的项**不进** misses：那是常态（一份档案里绝大多数项对某张单都不命中），
                // 报出来只会把「真的缺东西」淹掉。misses 只承载**异常形态**。
                continue;
            }
            matched = true;
            String key = str(item.get("key"), "");
            String name = str(item.get("name"), "");
            BigDecimal value = num(item.get("value"));
            if (value == null) {
                // 命中但**未配置取值**（壁达的「画线」就是这一形态）⇒ 显式报出，不计入、不按 0 算。
                misses.add(new Miss(key, name, "unresolved"));
                continue;
            }
            String direction = str(item.get("direction"), "add");
            boolean heightJoin = Boolean.TRUE.equals(item.get("height_join"));
            hits.add(new Hit(key, name, value, direction, heightJoin));
            total = "subtract".equals(direction) ? total.subtract(value) : total.add(value);
        }
        return new Pass(total, matched, hits, misses);
    }

    /**
     * 命中判定：**部位**（{@code null} = 不限）+ **条件组**（跨 kind AND、组内 values OR）。
     *
     * <p>{@code kind} 决定拿订单侧哪个取值域比：{@code option} ⇒ 特殊选项、{@code craft} ⇒ 安装工艺、
     * {@code processing_item} ⇒ 加工项、{@code shaped} ⇒ 是否定型（取值 {@code "true"}/{@code "false"}）。
     * 未知 kind / 空 values ⇒ <b>该条件不成立</b>（fail-closed：写面已拒，能走到这里的只可能是历史脏数据，
     * 宁可漏不可错）。</p>
     */
    static boolean matches(Map<String, Object> item, Vars vars) {
        if (item == null || item.isEmpty()) {
            return false;
        }
        String position = str(item.get("position"), null);
        if (position != null && !position.equals(vars.position())) {
            return false;
        }
        for (Map<String, Object> condition : asList(item.get("conditions"))) {
            if (!conditionMatches(condition, vars)) {
                return false;
            }
        }
        return true;
    }

    private static boolean conditionMatches(Map<String, Object> condition, Vars vars) {
        String kind = str(condition.get("kind"), "");
        List<String> values = strings(condition.get("values"));
        if (values.isEmpty()) {
            return false;
        }
        return switch (kind) {
            // 特殊选项：逐字相等 ⇒ 命中；规则写**语义名**（`余料带回`）⇒ 按布/纱派生族匹配
            // （issue #8007：配置面只出语义名，订单侧落的是 `-布` / `-纱` 派生键）
            case "option" -> optionAnyOf(values, vars.specialOptions());
            case "craft" -> values.stream().anyMatch(value -> value.equals(vars.craft()));
            case "processing_item" -> anyOf(values, vars.processingItems());
            case "shaped" -> values.stream()
                    .anyMatch(value -> value.equals(String.valueOf(Boolean.TRUE.equals(vars.isShaped()))));
            default -> false;
        };
    }

    /** 特殊选项条件的命中：{@link SpecialOptionNames#ruleValueMatches} 承借口径（语义名按族展开）。 */
    private static boolean optionAnyOf(List<String> values, List<String> pool) {
        List<String> source = pool == null ? List.of() : pool;
        return values.stream().anyMatch(value ->
                source.stream().anyMatch(option -> SpecialOptionNames.ruleValueMatches(value, option)));
    }

    private static boolean anyOf(List<String> values, List<String> pool) {
        List<String> source = pool == null ? List.of() : pool;
        return values.stream().anyMatch(source::contains);
    }

    /** 取整（本仓库唯一一处：配置页与机器下发值必须同源）。 */
    static BigDecimal round(BigDecimal value, String mode, int digits) {
        RoundingMode rm = switch (mode) {
            case "down" -> RoundingMode.DOWN;
            case "up" -> RoundingMode.UP;
            default -> RoundingMode.HALF_UP;
        };
        return value.setScale(Math.max(0, Math.min(3, digits)), rm);
    }

    static boolean isNumeric(Object raw) {
        return raw == null || num(raw) != null;
    }

    static boolean withinRange(BigDecimal value) {
        return value.signum() >= 0 && value.compareTo(MAX_VALUE) <= 0;
    }

    private static BigDecimal num(Object raw) {
        if (raw == null) {
            return null;
        }
        if (raw instanceof BigDecimal bd) {
            return bd;
        }
        if (raw instanceof Number n) {
            return new BigDecimal(n.toString());
        }
        try {
            return new BigDecimal(String.valueOf(raw).trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static String str(Object raw, String fallback) {
        if (raw == null) {
            return fallback;
        }
        String s = String.valueOf(raw).trim();
        return s.isEmpty() ? fallback : s;
    }

    private static int intOf(Object raw, int fallback) {
        try {
            return Integer.parseInt(String.valueOf(raw).trim());
        } catch (RuntimeException e) {
            return fallback;
        }
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object raw) {
        return raw instanceof Map<?, ?> m ? (Map<String, Object>) m : Collections.emptyMap();
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> asList(Object raw) {
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<Map<String, Object>> out = new ArrayList<>(list.size());
        for (Object item : list) {
            if (item instanceof Map<?, ?> m) {
                out.add((Map<String, Object>) m);
            }
        }
        return out;
    }

    /** 字符串数组归一（空白丢弃、去重保序）—— 与订单侧 {@code specialOptions} 同口径。 */
    private static List<String> strings(Object raw) {
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<String> out = new ArrayList<>(list.size());
        for (Object item : list) {
            String text = str(item, null);
            if (text != null && !out.contains(text)) {
                out.add(text);
            }
        }
        return out;
    }

    /** 便于日志/响应：命中列表 → 可序列化结构。 */
    static List<Map<String, Object>> toRows(List<Hit> hits) {
        List<Map<String, Object>> rows = new ArrayList<>(hits.size());
        for (Hit hit : hits) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("key", hit.key());
            row.put("name", hit.name());
            row.put("value", hit.value());
            row.put("direction", hit.direction());
            row.put("height_join", hit.heightJoin());
            rows.add(row);
        }
        return rows;
    }
}
