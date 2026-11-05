package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.ArrayList;
import java.util.List;

/**
 * 口径卡条件语言 —— **写面校验器**（issue #8175 判据 2）。
 *
 * <p>唯一实现的另一半在 Python 读面（{@code backend/ai-agent-service/app/playbook/condition.py}）。
 * 两处算子表由 {@code tests/unit_ci_workflows/test_playbook_condition_contract.py} 现取对账：
 * 只改一侧 ⇒ 判据红。这不是洁癖 —— 写面比读面宽一格，就是「存进去了但永远不生效」，
 * 而商家看到的是「已保存」，没有任何东西会红。</p>
 *
 * <p><b>为什么自由文本必须在这里就被拒</b>：本仓铁律是「自然语义断言不许只写不判」。
 * 一条口径的 {@code trigger} 若是自然语言，读面无法判定它该不该生效、出口③也生成不出会红的用例
 * ⇒ 那张卡从写进库的那一刻起就是死字段。所以在写面就 422，而不是留给读面静默丢弃。</p>
 */
public final class PlaybookConditionValidator {

    /**
     * 算子白名单 —— 与 backend/ai-agent-service/app/playbook/condition.py::OPS **逐项相同**。
     * 加算子的顺序即安全顺序：Python 侧先加 → 本行同批加 → 跑对账判据。
     */
    public static final List<String> OPS = List.of(
            "eq", "ne", "in", "not_in", "contains", "not_contains", "exists", "not_exists");

    private static final List<String> ARRAY_OPS = List.of("in", "not_in");
    private static final List<String> SUBSTRING_OPS = List.of("contains", "not_contains");
    private static final List<String> NO_VALUE_OPS = List.of("exists", "not_exists");
    private static final List<String> GROUP_KEYS = List.of("all", "any", "not");
    private static final int MAX_DEPTH = 6;

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private PlaybookConditionValidator() {
    }

    /** 从库/请求里的原始文本校验（空 / 非法 JSON ⇒ 问题清单）。 */
    public static List<String> validateJson(String raw) {
        if (raw == null || raw.isBlank()) {
            return List.of("条件是空对象");
        }
        JsonNode node;
        try {
            node = MAPPER.readTree(raw);
        } catch (Exception e) {
            return List.of("条件不是合法 JSON：" + e.getMessage());
        }
        return validate(node, 0);
    }

    /** 结构 + 算子校验。返回**问题清单**（空列表 = 合法）。 */
    public static List<String> validate(JsonNode node, int depth) {
        List<String> problems = new ArrayList<>();
        if (depth > MAX_DEPTH) {
            problems.add("条件嵌套超过 " + MAX_DEPTH + " 层");
            return problems;
        }
        if (node == null || !node.isObject()) {
            problems.add("条件必须是 JSON 对象，实际是 "
                    + (node == null ? "null" : node.getNodeType().toString()));
            return problems;
        }
        if (node.isEmpty()) {
            problems.add("条件是空对象");
            return problems;
        }

        List<String> groups = new ArrayList<>();
        for (String key : GROUP_KEYS) {
            if (node.has(key)) {
                groups.add(key);
            }
        }
        if (!groups.isEmpty()) {
            if (groups.size() > 1) {
                problems.add("一个条件里同时出现多个组合键：" + groups);
                return problems;
            }
            if (node.size() > 1) {
                problems.add("组合键 " + groups.get(0) + " 不得与其它键共存");
                return problems;
            }
            String key = groups.get(0);
            if ("not".equals(key)) {
                problems.addAll(validate(node.get("not"), depth + 1));
                return problems;
            }
            JsonNode children = node.get(key);
            if (children == null || !children.isArray() || children.isEmpty()) {
                problems.add(key + " 必须是非空数组");
                return problems;
            }
            for (int i = 0; i < children.size(); i++) {
                for (String p : validate(children.get(i), depth + 1)) {
                    problems.add(key + "[" + i + "]: " + p);
                }
            }
            return problems;
        }

        // ── 叶子 ──
        JsonNode field = node.get("field");
        if (field == null || !field.isTextual() || field.asText().isBlank()) {
            return List.of("叶子条件缺 field（或 field 不是字符串）");
        }
        JsonNode opNode = node.get("op");
        String op = opNode == null || !opNode.isTextual() ? null : opNode.asText();
        if (op == null || !OPS.contains(op)) {
            return List.of("未知算子 " + op + "（白名单：" + String.join(", ", OPS) + "）");
        }

        boolean hasValue = node.has("value");
        if (NO_VALUE_OPS.contains(op)) {
            if (hasValue) {
                problems.add("算子 " + op + " 不得带 value");
            }
            return problems;
        }
        if (!hasValue) {
            return List.of("算子 " + op + " 必须带 value");
        }
        JsonNode value = node.get("value");
        if (ARRAY_OPS.contains(op)) {
            if (!value.isArray() || value.isEmpty()) {
                problems.add("算子 " + op + " 的 value 必须是非空数组");
            }
        } else if (SUBSTRING_OPS.contains(op)) {
            if (!value.isTextual() || value.asText().isBlank()) {
                problems.add("算子 " + op + " 的 value 必须是非空字符串");
            }
        } else if (value.isObject() || value.isArray()) {
            problems.add("算子 " + op + " 的 value 必须是标量");
        }
        return problems;
    }

    /** 这条条件能不能被机器判？（自由文本 / 结构不合法 ⇒ false） */
    public static boolean isExecutable(String raw) {
        return validateJson(raw).isEmpty();
    }
}
