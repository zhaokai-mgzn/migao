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
 * <p><b>命中口径复用 {@code production_route_rules} 那一份</b>（设计单 §1.6）：本类**不**按名称再比一遍，
 * 只认配置里的 {@code hit.trigger_kind} / {@code hit.trigger_value} / {@code hit.position} 三件，
 * 与订单侧同名的取值域（{@code processingInfo.specialOptions[]} / 工艺名 / 加工项名 / 部位名）**逐字**比对。
 * 判据：出现第二份「选项名 → 命中」实现 ⇒ 红（{@code CuttingHeightConfigServiceTest}）。</p>
 *
 * <p><b>未配置取值（{@code value=null}，如「画线」）不算 0</b>：它进 {@code misses}
 * （{@code reason=unresolved}）且**不计入**合计 —— 静默按 0 算 = 给机器的值偏小 = 裁短（事故）。</p>
 */
final class CuttingHeightCalculator {

    /** 触发类型闭词表（与 {@code production_route_rules.trigger_kind} 同集合）。 */
    static final List<String> TRIGGER_KINDS = List.of("option", "craft", "processing_item", "shaped");

    /** 部位闭词表（与订单行的部位词表同集合）；{@code null} = 不限部位。 */
    static final List<String> POSITIONS = List.of("布帘", "纱帘", "帘头");

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

        BigDecimal total = vars.finishedHeight();
        List<Hit> hits = new ArrayList<>();
        List<Miss> misses = new ArrayList<>();
        for (Map<String, Object> item : asList(config.get("items"))) {
            String key = str(item.get("key"), "");
            String name = str(item.get("name"), "");
            if (!Boolean.FALSE.equals(item.get("enabled"))) {
                if (!matches(asMap(item.get("hit")), vars)) {
                    // 未命中的项**不进** misses：那是常态（一份档案里绝大多数项对某张单都不命中），
                    // 报出来只会把「真的缺东西」淹掉。misses 只承载**异常形态**。
                    continue;
                }
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
        }
        return new Result(vars.finishedHeight(), round(total, mode, digits), mode, digits, hits, misses);
    }

    /**
     * 命中判定：**三件**逐字比对（触发类型 + 触发值 + 部位限定）。
     *
     * <p>{@code trigger_kind} 决定拿订单侧哪个取值域比：{@code option} ⇒ 特殊选项、
     * {@code craft} ⇒ 安装工艺、{@code processing_item} ⇒ 加工项、{@code shaped} ⇒ 是否定型
     * （{@code trigger_value} = {@code "true"}/{@code "false"}）。未知类型 ⇒ **不命中**（fail-closed：
     * 写面已拒，能走到这里的只可能是历史脏数据，宁可漏不可错）。</p>
     */
    static boolean matches(Map<String, Object> hit, Vars vars) {
        if (hit == null || hit.isEmpty()) {
            return false;
        }
        String position = str(hit.get("position"), null);
        if (position != null && !position.equals(vars.position())) {
            return false;
        }
        String value = str(hit.get("trigger_value"), null);
        if (value == null) {
            return false;
        }
        return switch (str(hit.get("trigger_kind"), "")) {
            case "option" -> vars.specialOptions().contains(value);
            case "craft" -> value.equals(vars.craft());
            case "processing_item" -> vars.processingItems().contains(value);
            case "shaped" -> String.valueOf(Boolean.TRUE.equals(vars.isShaped())).equals(value);
            default -> false;
        };
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
