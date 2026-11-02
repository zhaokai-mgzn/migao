// case_ids: OR-006, OR-055
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 订单状态常量（issue #8198，P2-2a 第一步）：**只加常量，不加枚举**。
 *
 * <p>三条判据（都会红）：
 * <ol>
 *   <li><b>扫面</b>：{@code controller/} 下不许再写裸 {@code "pending"} 等（注释除外）——
 *       红证：把 {@code OrderController} 里一处常量改回字面量 ⇒ 红；</li>
 *   <li><b>值一致</b>：7 个常量逐字等于 DB 存储值，且 == 流转表键集 == 标签表键集 ——
 *       红证：把 {@code PRODUCING} 的值改成 {@code "producingg"} ⇒ 红；</li>
 *   <li><b>三张表未被削弱</b>：流转边逐条相等 + 标签逐条相等 + 可编辑集合不变 ——
 *       红证：删掉 {@code packed → shipped} ⇒ 红。</li>
 * </ol>
 *
 * <p>扫面用的字面量**独立硬编码**（不引用被测常量），否则改常量值会同时改判据 ⇒ 假绿。</p>
 */
@DisplayName("订单状态常量：controller 零裸字面量 + 值与三张表一致 + 状态机未被削弱")
class OrderStatusConstantsTest {

    private static final Path CONTROLLER_DIR = Path.of("src/main/java/com/migao/admin/controller");

    /** DB 存储值（硬编码的独立真值；故意不引用 {@link OrderStatusTransitions} 的常量）。 */
    private static final List<String> DB_STATUS_VALUES = List.of(
            "pending", "confirmed", "producing", "packed", "shipped", "completed", "cancelled");

    private static final Pattern STATUS_LITERAL = Pattern.compile(
            "\"(" + String.join("|", DB_STATUS_VALUES) + ")\"");

    /**
     * 非订单状态的合法同名 JSON 键（逐条写明为什么**不是**订单状态）。
     *
     * <p>现取实测与派单口径「19 处，全在三个订单 controller」不一致：19 个命中行里
     * <b>17 行</b>在 Order/Dashboard/ProductionController（共 21 个状态字面量），另 <b>2 行</b>属于
     * 别的域 —— 知识候选的计数字段名、定时任务的 cancelled 计数键。把它们换成订单状态常量属于
     * <b>错误耦合</b>（值相同纯属巧合）⇒ 按文件 + 字面量豁免，并要求该非订单用法**逐字仍在**
     * （陈旧豁免 / 被误改 ⇒ 红）。</p>
     */
    private static final Map<String, Set<String>> NON_ORDER_STATUS_KEYS = Map.of(
            "KnowledgeCandidateController.java", Set.of("\"pending\""),
            "agent/AgentScheduledTaskController.java", Set.of("\"cancelled\""));

    /** 豁免依据：非订单状态的原始用法（逐字），用来证明豁免不是陈旧的。 */
    private static final Map<String, String> NON_ORDER_STATUS_USAGE = Map.of(
            "KnowledgeCandidateController.java",
            "Map.of(\"pending\", knowledgeCandidateService.pendingCount())",
            "agent/AgentScheduledTaskController.java",
            "Map.of(\"id\", id, \"cancelled\", cancelled)");

    @Test
    @DisplayName("🔴 扫面：controller/ 下零订单状态裸字面量（红证：OrderController 改回 \"shipped\" ⇒ 红）")
    void controllersContainNoBareStatusLiterals() throws IOException {
        Map<String, Integer> violations = new LinkedHashMap<>();
        List<String> scanned = new ArrayList<>();
        try (Stream<Path> files = Files.walk(CONTROLLER_DIR)) {
            for (Path file : files.filter(p -> p.toString().endsWith(".java")).sorted().toList()) {
                String relative = CONTROLLER_DIR.relativize(file).toString();
                scanned.add(relative);
                if (relative.endsWith("OrderStatusTransitions.java")) {
                    continue;
                }
                Set<String> allowed = NON_ORDER_STATUS_KEYS.getOrDefault(relative, Set.of());
                int hits = 0;
                for (String line : Files.readAllLines(file)) {
                    String code = stripComments(line);
                    Matcher matcher = STATUS_LITERAL.matcher(code);
                    while (matcher.find()) {
                        if (!allowed.contains(matcher.group())) {
                            hits++;
                        }
                    }
                }
                if (hits > 0) {
                    violations.put(relative, hits);
                }
            }
        }
        assertThat(violations)
                .as("controller/ 里残留的订单状态裸字面量（文件 → 处数），改用 OrderStatusTransitions.*")
                .isEmpty();
        assertThat(scanned)
                .as("扫面必须真读到三个订单 controller（目录挪了就红，不许空跑）")
                .contains("OrderController.java", "DashboardController.java", "ProductionController.java");
    }

    @Test
    @DisplayName("🔴 值一致：7 个常量逐字等于 DB 存储值，且 == 流转表键集 == 标签表键集")
    void constantsAreExactlyTheDatabaseValues() {
        assertThat(OrderStatusTransitions.PENDING).isEqualTo("pending");
        assertThat(OrderStatusTransitions.CONFIRMED).isEqualTo("confirmed");
        assertThat(OrderStatusTransitions.PRODUCING).isEqualTo("producing");
        assertThat(OrderStatusTransitions.PACKED).isEqualTo("packed");
        assertThat(OrderStatusTransitions.SHIPPED).isEqualTo("shipped");
        assertThat(OrderStatusTransitions.COMPLETED).isEqualTo("completed");
        assertThat(OrderStatusTransitions.CANCELLED).isEqualTo("cancelled");

        assertThat(Set.of(
                OrderStatusTransitions.PENDING,
                OrderStatusTransitions.CONFIRMED,
                OrderStatusTransitions.PRODUCING,
                OrderStatusTransitions.PACKED,
                OrderStatusTransitions.SHIPPED,
                OrderStatusTransitions.COMPLETED,
                OrderStatusTransitions.CANCELLED))
                .as("常量值集合必须就是两张表的键集合（多一个 / 少一个 / 拼错都红）")
                .isEqualTo(OrderStatusTransitions.STATUS_TRANSITIONS.keySet())
                .isEqualTo(OrderStatusTransitions.ORDER_STATUS_LABELS.keySet());
    }

    @Test
    @DisplayName("🔴 三张表未被削弱：流转边逐条相等 + 标签逐条相等 + 可编辑集合不变")
    void stateMachineTablesAreUnchanged() {
        assertThat(OrderStatusTransitions.STATUS_TRANSITIONS).isEqualTo(Map.of(
                "pending", Set.of("confirmed", "cancelled"),
                "confirmed", Set.of("producing", "packed", "shipped", "cancelled"),
                "producing", Set.of("packed", "shipped", "cancelled"),
                "packed", Set.of("shipped"),
                "shipped", Set.of("completed"),
                "completed", Set.of(),
                "cancelled", Set.of()
        ));
        assertThat(OrderStatusTransitions.ORDER_STATUS_LABELS).isEqualTo(Map.of(
                "pending", "待付款",
                "confirmed", "已确认",
                "producing", "生产中",
                "packed", "已打包",
                "shipped", "已发货",
                "completed", "已完成",
                "cancelled", "已取消"
        ));
        assertThat(OrderStatusTransitions.CONTENT_EDITABLE_STATUSES).isEqualTo(Set.of("pending"));

        // 反向护栏：撤销打包**不在**表里（否则商家无理由端点也能退回生产）
        assertThat(OrderStatusTransitions.allowedTargets("packed")).isEqualTo(Set.of("shipped"));
        assertThat(OrderStatusTransitions.isKnownStatus("packed")).isTrue();
    }

    @Test
    @DisplayName("豁免自检：非订单状态的两处同名键逐字仍在（陈旧豁免 / 被误改成常量 ⇒ 红）")
    void nonOrderStatusExemptionsAreNotStale() throws IOException {
        for (Map.Entry<String, String> entry : NON_ORDER_STATUS_USAGE.entrySet()) {
            assertThat(Files.readAllLines(CONTROLLER_DIR.resolve(entry.getKey())))
                    .as("%s 的豁免依据（非订单状态用法）已不存在 ⇒ 更新 allowlist", entry.getKey())
                    .anyMatch(line -> line.contains(entry.getValue()));
        }
    }

    /** 去掉注释（整行注释直接返回空串；行内 `//` 之后截掉，字符串里的 `//` 不截）。 */
    private static String stripComments(String line) {
        String trimmed = line.trim();
        if (trimmed.startsWith("//") || trimmed.startsWith("/*") || trimmed.startsWith("*")) {
            return "";
        }
        boolean inString = false;
        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);
            if (c == '"' && (i == 0 || line.charAt(i - 1) != '\\')) {
                inString = !inString;
            } else if (!inString && c == '/' && i + 1 < line.length() && line.charAt(i + 1) == '/') {
                return line.substring(0, i);
            }
        }
        return line;
    }
}
